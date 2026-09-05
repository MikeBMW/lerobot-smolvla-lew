#!/usr/bin/env python3
"""模拟评估循环: 打印 hand/光模块/d_hp/act_z/contact, 判断左脑是否驱动 hand 接近 光模块 或 act_z 爆炸"""
import os, sys, numpy as np, torch
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

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# 加载模型
d = torch.load("outputs/rl_peg/full_pipeline.pt", weights_only=False, map_location="cpu")
from train_full_pipeline import LeftBrainMLP, RightBrainWM
left = LeftBrainMLP(39, 4); left.load_state_dict(d["left"]); left.to(DEVICE); left.eval()
right = RightBrainWM(39, 4); right.load_state_dict({k: v for k, v in d["right"].items() if not k.startswith("align_head")}, strict=False); right.to(DEVICE); right.eval()
xm = torch.from_numpy(np.asarray(d["xm"])).float().to(DEVICE)
xs = torch.from_numpy(np.asarray(d["xs"])).float().to(DEVICE)
ym = torch.from_numpy(np.asarray(d["ym"])).float().to(DEVICE)
ys = torch.from_numpy(np.asarray(d["ys"])).float().to(DEVICE)

# aligner (深度 + scale)
det_w = "runs/detect/outputs/yolo_peg/peg_v1/weights/best.pt"
depth_w = "outputs/yolo_peg_depth/peg_depth_v1-2/weights/best.pt"
env = make_env(0)
aligner = yolo_state_aligner.YoloStateAligner(det_w, env, depth_weights=depth_w)

def get_obs(e): return np.asarray(e._get_obs(), dtype=np.float32).ravel()
def yolo_state(e, o):
    det = aligner.detect_3d(e.render())
    return aligner.align(o, det).astype(np.float32)[:39]

o = get_obs(env)
o_yolo = yolo_state(env, o)
peg_z0 = float(o_yolo[6])
print(f"初始: hand={o_yolo[0:3]}, peg={o_yolo[4:7]}, d_hp={np.linalg.norm(o_yolo[0:3]-o_yolo[4:7]):.4f}")

for step in range(150):
    hand = o_yolo[0:3]; peg = o_yolo[4:7]
    d_hp = float(np.linalg.norm(hand - peg))
    xin = torch.from_numpy((o_yolo - xm.cpu().numpy()) / xs.cpu().numpy()).float().to(DEVICE)
    with torch.no_grad():
        pred = left(xin.unsqueeze(0)).squeeze(0).cpu().numpy()
    act = pred * ys.cpu().numpy() + ym.cpu().numpy()
    o_r = torch.from_numpy(o_yolo).float().to(DEVICE)
    a_r = torch.from_numpy(act).float().to(DEVICE)
    with torch.no_grad():
        _, pc, _ = right(o_r.unsqueeze(0), a_r.unsqueeze(0))
    contact = float(pc.item())
    if step % 15 == 0 or d_hp < 0.08:
        print(f"step{step:3d}: hand_z={hand[2]:.4f} peg_z={peg[2]:.4f} d_hp={d_hp:.4f} act=[{act[0]:+.3f},{act[1]:+.3f},{act[2]:+.3f},{act[3]:+.3f}] contact={contact:.3f}")
    # 接近逻辑 (同 train_full_pipeline)
    delta = peg - hand
    act[:3] = act[:3] * 0.3 + np.clip(delta * 2.0, -1, 1)
    act[3] = -1.0
    _mx = float(np.abs(act).max()) if len(act) else 1.0
    if _mx > 1.0: act = act / _mx
    env.step(np.clip(act, -1, 1))
    o = get_obs(env)
    o_yolo = yolo_state(env, o)
    if step % 15 == 0:
        print(f"        → 执行后 hand={o_yolo[0:3]}, d_hp={np.linalg.norm(o_yolo[0:3]-o_yolo[4:7]):.4f}")
env.close()
print(f"\n最终 d_hp={d_hp:.4f} (抓取阈 <0.06)")
