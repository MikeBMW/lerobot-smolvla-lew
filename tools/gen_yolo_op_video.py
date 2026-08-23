#!/usr/bin/env python3
"""YOLO 感知操作视频 — BC policy + 真实 YOLO 检测 (2026-08-23 老倪)
视频画面叠加 YOLO 检测框 (hand/peg/hole), state 用 detect_3d 解算喂 BC → 真机同构操作视频
与训练(data/metaworld_peg --yolo)、评估(eval_yolo_bc.py)同一套 YOLO 感知链
用法:
  DISPLAY=:0 MUJOCO_GL=glfw gui-venv311/bin/python tools/gen_yolo_op_video.py --seed 0
"""
import os, sys, json, argparse, subprocess, tempfile
import numpy as np
import torch
import torch.nn as nn

os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("MUJOCO_GL", "glfw")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "src", "lerobot", "policies", "yolo_3d"))

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
HIDDEN = 512
CKPT = os.path.join(ROOT, "outputs", "bc_yolo", "model.pt")

WEIGHTS_CANDS = [
    "runs/detect/outputs/yolo_peg/peg_v1/weights/best.pt",
    "runs/detect/outputs/yolo_peg/peg_full/weights/best.pt",
    "outputs/yolo_peg/peg_v1/weights/best.pt",
]


class BCMLP(nn.Module):
    def __init__(self, obs_dim=39, act_dim=4, hidden=HIDDEN):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(obs_dim, hidden), nn.ReLU(), nn.Dropout(0.1),
            nn.Linear(hidden, hidden), nn.ReLU(), nn.Dropout(0.1),
            nn.Linear(hidden, hidden), nn.ReLU(),
            nn.Linear(hidden, act_dim))

    def forward(self, x):
        return self.net(x)


def load_stats():
    s = json.load(open(os.path.join(ROOT, "data", "metaworld_peg", "meta", "stats.json")))
    return (np.array(s["observation.state"]["mean"], dtype=np.float32),
            np.array(s["observation.state"]["std"], dtype=np.float32) + 1e-6,
            np.array(s["action"]["mean"], dtype=np.float32),
            np.array(s["action"]["std"], dtype=np.float32) + 1e-6)


def build_aligner():
    import yolo_state_aligner
    w = next((os.path.join(ROOT, c) for c in WEIGHTS_CANDS
              if os.path.isfile(os.path.join(ROOT, c))), None)
    if not w:
        return None, None
    import metaworld
    mt = metaworld.MT1("peg-insert-side-v3")
    env0 = mt.train_classes["peg-insert-side-v3"](render_mode="rgb_array", camera_name="corner2")
    env0._freeze_rand_vec = False
    env0.set_task(mt.train_tasks[0])
    env0.reset(seed=0)
    return yolo_state_aligner.YoloStateAligner(w, env0), w


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--steps", type=int, default=200)
    ap.add_argument("--out", type=str, default=os.path.join(ROOT, "reports", "yolo_perception_op.mp4"))
    args = ap.parse_args()

    print("🎥 YOLO 感知操作视频 · BC policy · 真实 YOLO 检测 (真机同构)")
    # 加载 BC 模型 (data/metaworld_peg YOLO噪声state 训练)
    ck = torch.load(CKPT, map_location=DEVICE, weights_only=False)
    model = BCMLP().to(DEVICE)
    model.load_state_dict(ck["state_dict"])
    model.eval()
    sm, ss, am, asd = load_stats()
    aligner, weights = build_aligner()
    if aligner is None:
        print("❌ YOLO 权重未找到, 无法生成 YOLO 感知视频")
        return
    print(f"[model] BC 权重: {CKPT}")
    print(f"[yolo ] 检测权重: {weights}")

    import metaworld
    import cv2
    mt = metaworld.MT1("peg-insert-side-v3", seed=args.seed)
    env = mt.train_classes["peg-insert-side-v3"](render_mode="rgb_array", camera_name="corner2")
    env.set_task(mt.train_tasks[0])
    obs, _ = env.reset(seed=args.seed)
    peg_z0 = env.data.site_xpos[env.model.site("pegGrasp").id][2]
    hole = env.data.site_xpos[env.model.site("hole").id]

    frames = []
    det_hist = []
    lifted = False
    for i in range(args.steps):
        peg = env.data.site_xpos[env.model.site("pegGrasp").id]
        if peg[2] - peg_z0 > 0.05:
            lifted = True
        img = env.render()  # 480x480 RGB
        # 真实 YOLO 检测 (rot90 + BGR, 与训练/评估同向) → 叠加框可视化 + 3D 解算
        img_rot = np.rot90(img, k=2)
        img_bgr = cv2.cvtColor(img_rot, cv2.COLOR_RGB2BGR)
        res = aligner.model.predict(img_bgr, conf=0.4, verbose=False)[0]
        vis = np.rot90(np.asarray(res.plot()), k=2)  # 转回原方向 (带框)
        det3d = aligner.detect_3d(img)
        det_hist.append(len(det3d))
        st = aligner.align(np.asarray(obs, dtype=np.float32)[:39], det3d).astype(np.float32)[:39]
        st_n = (st - sm) / ss
        with torch.no_grad():
            act = model(torch.from_numpy(st_n).float().to(DEVICE).unsqueeze(0)).cpu().numpy().ravel()
        act = np.clip(act * asd + am, -1.0, 1.0)
        frames.append(np.ascontiguousarray(vis))  # vis 已是 BGR (res.plot 返回 BGR)
        obs, _, term, trunc, _ = env.step(act)
        if term or trunc:
            break
    peg_final = env.data.site_xpos[env.model.site("pegGrasp").id]
    dist_hole = float(np.linalg.norm(peg_final - hole))
    env.close()

    print(f"[run ] seed={args.seed} 抬起={'✅' if lifted else '❌'} "
          f"插入={'✅' if (lifted and dist_hole < 0.05) else '❌'} 距孔={dist_hole:.3f}m "
          f"帧数={len(frames)} 每帧检出={np.mean(det_hist):.2f}类")

    # ffmpeg 合成
    tmpdir = tempfile.mkdtemp(prefix="yolo_op_")
    for i, fr in enumerate(frames):
        cv2.imwrite(os.path.join(tmpdir, f"f{i:05d}.png"), fr)
    out = args.out
    os.makedirs(os.path.dirname(out), exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-framerate", "20", "-i", os.path.join(tmpdir, "f%05d.png"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23", "-loglevel", "error", out], check=True)
    subprocess.run(["rm", "-rf", tmpdir], check=False)
    print(f"✅ YOLO 感知操作视频: {out} ({len(frames)} 帧, 画面叠加 hand/peg/hole 检测框)")


if __name__ == "__main__":
    main()
