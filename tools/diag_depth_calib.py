#!/usr/bin/env python3
"""标定 DEPTH_SCALE: 实测 depth_m (模型输出) vs 真实沿光轴深度, 算每类 scale 修正
真实执行多 seed, 输出 hand/光模块/hole 各自需要的 scale (用于 DEPTH_SCALE / DEPTH_SCALE_HAND)
"""
import os, sys, glob, numpy as np
ROOT = "/home/ubuntu/lerobot-smolvla-lew"
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src/lerobot/policies/yolo_3d"))
import yolo_state_aligner

def make_env(seed=0):
    import metaworld
    mt = metaworld.MT1("peg-insert-side-v3")
    env = mt.train_classes["peg-insert-side-v3"](render_mode="rgb_array", camera_name="corner2")
    env._freeze_rand_vec = False
    env.set_task(mt.train_tasks[0])
    env.reset(seed=seed)
    env._freeze_rand_vec = True
    return env

det_w = os.path.join(ROOT, "runs/detect/outputs/yolo_peg/peg_v1/weights/best.pt")
depth_w = os.path.join(ROOT, "outputs/yolo_peg_depth/peg_depth_v1-2/weights/best.pt")

env = make_env(0)
aligner = yolo_state_aligner.YoloStateAligner(det_w, env, depth_weights=depth_w)
cam_pos = env.model.cam_pos[aligner.cam_id].copy()
cam_mat = np.asarray(env.model.cam_mat0[aligner.cam_id]).reshape(3, 3).T
forward = cam_mat.T @ np.array([0.0, 0.0, -1.0]); forward /= np.linalg.norm(forward)
print(f"cam_pos={cam_pos}, forward={forward}")

import cv2
# 真值坐标 (从 _get_obs 的 39D state 取)
# hand[0:3], 光模块[4:7], hole[36:39]
TRUTH_IDX = {"hand": (0, 3), "peg": (4, 7), "hole": (36, 39)}

scales = {"hand": [], "peg": [], "hole": []}
for seed in range(8):
    e = make_env(seed)
    # 复用 aligner 的检测模型和深度模型 (相机参数静态, 与 seed 无关; env 只用于渲染)
    obs = np.asarray(e._get_obs(), dtype=np.float32).ravel()
    img = e.render()
    img_rot = np.rot90(img, k=2)
    img_bgr = cv2.cvtColor(img_rot, cv2.COLOR_RGB2BGR)
    res = aligner.model.predict(img_bgr, conf=0.4, verbose=False)[0]
    da = np.asarray(aligner.depth_model.predict(img_bgr, verbose=False)[0].depth.data.detach().cpu().numpy()).squeeze()
    H, W = img.shape[:2]
    for b in res.boxes:
        cls = res.names[int(b.cls)]
        if cls not in TRUTH_IDX:
            continue
        x1, y1, x2, y2 = [float(v) for v in b.xyxy[0]]
        x1i, y1i = int(np.clip(x1, 0, W-1)), int(np.clip(y1, 0, H-1))
        x2i, y2i = int(np.clip(x2, 0, W-1)), int(np.clip(y2, 0, H-1))
        if x2i > x1i and y2i > y1i:
            depth_m = float(np.median(da[y1i:y2i, x1i:x2i]))
        else:
            depth_m = float(da[int(np.clip((y1+y2)/2,0,H-1)), int(np.clip((x1+x2)/2,0,W-1))])
        # 真实沿光轴深度
        t0, t1 = TRUTH_IDX[cls]
        truth = obs[t0:t1]
        true_depth = float(np.dot(truth - cam_pos, forward))
        if depth_m > 0.1 and true_depth > 0.1:
            scales[cls].append(true_depth / depth_m)
    e.close()
    env.close()

print("\n=== 每类 scale (真实深度/depth_m), 均值 = 新 DEPTH_SCALE ===")
for cls in ["hand", "peg", "hole"]:
    arr = np.asarray(scales[cls])
    if arr.size:
        print(f"{cls}: n={arr.size}, mean={arr.mean():.4f}, std={arr.std():.4f}, 各值={[round(x,3) for x in arr]}")
    else:
        print(f"{cls}: 无有效样本")
