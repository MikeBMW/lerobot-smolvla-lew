#!/usr/bin/env python3
"""诊断: 深度反投影 3D vs 真值 (评估 0/8 卡"接近"的根因)
真实执行, 打印 hand/peg/hole 的深度反投影坐标 vs 真值 + 深度模型原始输出范围
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

# 找检测权重 (普通 YOLO) — 含 runs_dir 坑的 runs/detect/ 路径
det_cands = [
    "runs/detect/outputs/yolo_peg/peg_v1/weights/best.pt",
    "outputs/yolo_peg/peg_v1/weights/best.pt",
]
det_w = next((os.path.join(ROOT, c) for c in det_cands if os.path.isfile(os.path.join(ROOT, c))), None)
depth_w = os.path.join(ROOT, "outputs/yolo_peg_depth/peg_depth_v1-2/weights/best.pt")
print(f"检测权重: {det_w}")
print(f"深度权重: {depth_w} (存在={os.path.isfile(depth_w)})")

env = make_env(0)
aligner = yolo_state_aligner.YoloStateAligner(det_w, env, depth_weights=depth_w)
print(f"DEPTH_SCALE 环境变量: {os.environ.get('DEPTH_SCALE', '(未设, 默认1.0)')}")
print(f"aligner._depth_scale={aligner._depth_scale}, _hand_scale={aligner._hand_scale}")

obs = np.asarray(env._get_obs(), dtype=np.float32).ravel()
det = aligner.detect_3d(env.render())

print("\n=== 真值 state (39D 关键段) ===")
print(f"hand 真值: xyz=({obs[0]:.4f},{obs[1]:.4f},{obs[2]:.4f})")
print(f"peg  真值: xyz=({obs[4]:.4f},{obs[5]:.4f},{obs[6]:.4f})")
print(f"hole 真值: xyz=({obs[36]:.4f},{obs[37]:.4f},{obs[38]:.4f})")

print("\n=== 深度反投影 3D ===")
for k in ["hand", "peg", "hole"]:
    if k in det:
        v = det[k]
        print(f"{k}: xyz=({v[0]:.4f},{v[1]:.4f},{v[2]:.4f})")
    else:
        print(f"{k}: 未检出!")

print("\n=== z 值对比 (深度 vs 真值) ===")
for k, idx in [("hand", 2), ("peg", 6), ("hole", 38)]:
    truth = obs[idx]
    d = det.get(k)
    dz = d[2] if d is not None else float('nan')
    print(f"{k}: 真值 z={truth:.4f}  深度 z={dz:.4f}  差={dz-truth:+.4f}")

if "hand" in det and "peg" in det:
    d_hp = float(np.linalg.norm(np.asarray(det["hand"]) - np.asarray(det["peg"])))
    print(f"\n=== hand-peg 距离 (深度) = {d_hp:.4f} m (抓取阈 <0.06) ===")
    t_hp = float(np.linalg.norm(obs[0:3] - obs[4:7]))
    print(f"hand-peg 距离 (真值) = {t_hp:.4f} m")

print("\n=== 深度模型原始输出范围 (判断自动校准 b=0.604 是否已应用) ===")
import cv2
img = env.render()
img_rot = np.rot90(img, k=2)
img_bgr = cv2.cvtColor(img_rot, cv2.COLOR_RGB2BGR)
dp = aligner.depth_model.predict(img_bgr, verbose=False)[0]
da = np.asarray(dp.depth.data.detach().cpu().numpy()).squeeze()
print(f"depth map: shape={da.shape}, min={da.min():.4f}, median={np.median(da):.4f}, max={da.max():.4f}")
print(f"(真实深度应约 0.5~2.5m; 若全<0.1 说明输出未校准/尺度塌缩)")

# 手动取各类框内中位数深度, 看校准前后
print("\n=== 各类框内中位数深度 (depth_m, 乘 scale 前) ===")
res = aligner.model.predict(img_bgr, conf=0.4, verbose=False)[0]
W, H = img.shape[:2]
for b in res.boxes:
    cls = res.names[int(b.cls)]
    x1, y1, x2, y2 = [float(v) for v in b.xyxy[0]]
    x1i, y1i = int(np.clip(x1, 0, W - 1)), int(np.clip(y1, 0, H - 1))
    x2i, y2i = int(np.clip(x2, 0, W - 1)), int(np.clip(y2, 0, H - 1))
    if x2i > x1i and y2i > y1i:
        dm = float(np.median(da[y1i:y2i, x1i:x2i]))
    else:
        dm = float(da[int(np.clip((y1+y2)/2, 0, H-1)), int(np.clip((x1+x2)/2, 0, W-1))])
    sc = aligner._hand_scale if cls == "hand" else aligner._depth_scale
    print(f"  {cls}: depth_m={dm:.4f} (乘 scale {sc} → {dm*sc:.4f})")
