#!/usr/bin/env python3
"""YOLO 检测 rollout 视频 — peg-insert 场景逐帧检测叠加框 (2026-08-07)
用法: python tools/yolo_rollout_video.py [--out reports/yolo_detect.mp4] [--seed 2]
"""
import os, sys, numpy as np
os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("MUJOCO_GL", "glfw")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import cv2
from ultralytics import YOLO
from metaworld.policies.sawyer_peg_insertion_side_v3_policy import SawyerPegInsertionSideV3Policy

WEIGHTS = os.path.join(ROOT, "runs/detect/outputs/yolo_peg/peg_v1/weights/best.pt")


def main():
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else os.path.join(ROOT, "reports", "yolo_detect.mp4")
    seed = int(sys.argv[sys.argv.index("--seed") + 1]) if "--seed" in sys.argv else 2

    model = YOLO(WEIGHTS)
    import metaworld
    mt = metaworld.MT1("peg-insert-side-v3")
    env = mt.train_classes["peg-insert-side-v3"](render_mode="rgb_array", camera_name="corner2")
    env._freeze_rand_vec = False
    env.set_task(mt.train_tasks[0])
    obs, _ = env.reset(seed=seed)
    env._freeze_rand_vec = True
    expert = SawyerPegInsertionSideV3Policy()

    frames = []
    for step in range(150):
        img = env.render()
        # 2026-08-07: YOLO 检测原帧 (框坐标正确) → ffmpeg 整体转180 (画面+框一起转)
        res = model.predict(img, conf=0.4, verbose=False)[0]
        vis = np.asarray(res.plot())  # 叠加框 (原帧方向)
        frames.append(cv2.cvtColor(np.ascontiguousarray(vis), cv2.COLOR_RGB2BGR))
        act = expert.get_action(np.asarray(obs, dtype=np.float64).ravel())
        obs, r, term, trunc, _ = env.step(act)
        if term or trunc:
            break
    env.close()

    h, w = frames[0].shape[:2]
    writer = cv2.VideoWriter(out, cv2.VideoWriter_fourcc(*"mp4v"), 20, (w, h))
    for f in frames:
        writer.write(f)
    writer.release()
    print(f"✅ YOLO 检测视频: {out} ({len(frames)} 帧)")


if __name__ == "__main__":
    main()
