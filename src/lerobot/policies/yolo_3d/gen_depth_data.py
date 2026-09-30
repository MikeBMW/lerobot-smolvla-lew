#!/usr/bin/env python3
"""深度估计训练数据生成器 — peg-insert 场景 (RGB + 深度图对齐)
2026-08-23 老倪: YOLO 加 depth head → 训练深度估计模型, 让 hand/光模块/hole 的 z 用真实深度(非写死 z_map)

流程: metaworld 渲染 rgbd_tuple(RGB+depth buffer) → depth buffer 反推米制深度 → 存 16-bit PNG
深度反推: depth = A - B/z  (mujoco 透视深度归一化, 实测拟合 A=1.0034 B=0.0290, 残差<0.0005)
         → z(米) = B / (A - depth)
保存: depth PNG value = z_meters * depth_scale (depth_scale=256, 即 1m=256)
"""
import os, sys, numpy as np
os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("MUJOCO_EGL_DEVICE", "0")

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
sys.path.insert(0, ROOT)

from PIL import Image
import cv2
from metaworld.policies.sawyer_peg_insertion_side_v3_policy import SawyerPegInsertionSideV3Policy

# 深度反推常数 (实测拟合, 各 seed 稳定: A=1.0002 B=0.0230, 反推误差 mean≈3cm)
DEPTH_A = 1.0002
DEPTH_B = 0.0230
DEPTH_MAX = 3.0   # 背景/远处反推爆炸处截断 (depth→1 时 1/(A-depth)→∞)
DEPTH_SCALE = 256  # 1 米 = 256 PNG 值


def make_env_rgbd(seed=0):
    import metaworld
    mt = metaworld.MT1("peg-insert-side-v3")
    env = mt.train_classes["peg-insert-side-v3"](render_mode="rgbd_tuple", camera_name="corner2")
    env._freeze_rand_vec = False
    env.set_task(mt.train_tasks[0])
    env.reset(seed=seed)
    env._freeze_rand_vec = True
    return env


def depth_to_meters(depth_buf):
    """mujoco depth buffer (透视归一化 [0,1]) → 米制深度 (背景截断到 DEPTH_MAX)"""
    d = np.clip(depth_buf, 0.0, DEPTH_A - 1e-6)
    z = DEPTH_B / (DEPTH_A - d)
    return np.clip(z, 0.0, DEPTH_MAX)


def main():
    eps = int(sys.argv[sys.argv.index("--eps") + 1]) if "--eps" in sys.argv else 12
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else os.path.join(ROOT, "data", "yolo_peg_depth")
    os.makedirs(f"{out}/images", exist_ok=True)
    os.makedirs(f"{out}/depth", exist_ok=True)

    expert = SawyerPegInsertionSideV3Policy()
    n = 0
    for ep in range(eps):
        env = make_env_rgbd(seed=ep)
        obs, _ = env.reset()
        env._freeze_rand_vec = True
        for step in range(150):
            obs_vec = np.asarray(obs, dtype=np.float64).ravel()
            act = expert.get_action(obs_vec)
            rgbd = env.render()  # (rgb, depth)
            if rgbd is not None and isinstance(rgbd, tuple):
                rgb, depth_buf = rgbd
                rgb = np.asarray(rgb)
                depth_buf = np.asarray(depth_buf, dtype=np.float32)
                z_m = depth_to_meters(depth_buf)
                # rot90(k=2) 与检测数据对齐 (gen_yolo_data.py 同样 rot90)
                rgb_rot = np.rot90(rgb, k=2)
                z_rot = np.rot90(z_m, k=2)
                # 保存 RGB (uint8) + 深度 (uint16 PNG, value = m * scale)
                Image.fromarray(rgb_rot).save(f"{out}/images/ep{ep:03d}_s{step:03d}.png")
                depth_u16 = np.clip(z_rot * DEPTH_SCALE, 0, 65535).astype(np.uint16)
                cv2.imwrite(f"{out}/depth/ep{ep:03d}_s{step:03d}.png", depth_u16)
                n += 1
            obs, r, term, trunc, _ = env.step(act)
            if term or trunc:
                break
        env.close()
        print(f"  ep{ep} 完成", flush=True)

    # data.yaml (depth 任务)
    with open(f"{out}/data.yaml", "w") as f:
        f.write(f"path: {out}\ntrain: images\nval: images\nnc: 1\nnames:\n  0: depth\nchannels: 3\ndepth_scale: {DEPTH_SCALE}\n")
    print(f"✅ 深度数据生成完成: {n} 张 (RGB+depth 对齐) → {out}")


if __name__ == "__main__":
    main()
