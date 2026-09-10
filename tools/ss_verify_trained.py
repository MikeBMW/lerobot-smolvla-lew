#!/usr/bin/env python3
"""ss_verify_trained.py — 🧮 状态空间训练→仿真闭环验证 (2026-08-20 静静)

加载 outputs/train/left_right_std 训练好的左脑 MLP → 替换状态空间仿真的
前馈加速器 (FeedforwardAccelerator) → 跑插拔仿真 → 验证训练模型能否完成任务。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "gui"))
import numpy as np
import torch

from state_space_sim import StateSpaceSim, X0, DT


def load_left_brain(ckpt_dir):
    """加载训练好的 LeftBrainMLP (model.pt 'left' 权重) + 归一化参数"""
    from lerobot.policies.left_right.modeling_left_right import LeftBrainMLP
    sd = torch.load(os.path.join(ckpt_dir, "pretrained_model", "model.pt"),
                    map_location="cpu", weights_only=False)
    obs_dim, act_dim = int(sd["obs_dim"]), int(sd["act_dim"])
    net = LeftBrainMLP(obs_dim=obs_dim, act_dim=act_dim)
    net.load_state_dict(sd["left"])
    net.eval()
    # 归一化参数: 训练时 preprocessor 从数据集算 (MEAN_STD), 未存 checkpoint → 重算
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    import pandas as pd
    df = pd.read_parquet(os.path.join(root, "data", "ss_insert_lerobot",
                                      "data", "chunk-000", "file-000.parquet"))
    S = np.stack(df["observation.state"].values).astype(np.float32)
    A = np.stack(df["action"].values).astype(np.float32)
    norm = {"sm": S.mean(0), "ss": S.std(0) + 1e-8,
            "am": A.mean(0), "astd": A.std(0) + 1e-8}
    return net, obs_dim, act_dim, norm


def main(ckpt="outputs/train/left_right_std/checkpoints/last", n_episodes=4, seed_base=200):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    net, obs_dim, act_dim, norm = load_left_brain(os.path.join(root, ckpt))
    print(f"🧠 已加载训练模型: obs {obs_dim}D → act {act_dim}D (含归一化)")
    n_ok = 0
    for ep in range(n_episodes):
        sim = StateSpaceSim(log=lambda *a: None)
        np.random.seed(seed_base + ep)
        sim.x = X0 + np.array([np.random.uniform(-0.01, 0.01),
                               np.random.uniform(-0.01, 0.01), 0.0])
        sim.v = np.zeros(3)
        sim.gripper = 0.0
        sim.latent = np.concatenate([sim.x, [0.0]])
        sim.obs_prev = None

        def ff_forward(obs):
            """训练 MLP 前向 — 2026-08-20 实测: 训练用了归一化 (dataset.stats 归一化,
            归一化输入 MSE 0.059 << 原始 0.188); 夹爪 0/1 跳变回归学不好 → 规则控制 (开关量)"""
            with torch.no_grad():
                x = torch.from_numpy(
                    (np.asarray(obs[:39], dtype=np.float32) - norm["sm"]) / norm["ss"])
                u_norm = net(x[None, :])[0].numpy()
            u_xyz = np.clip(u_norm[:3] * norm["astd"][:3] + norm["am"][:3], -0.6, 0.6)
            pos = np.asarray(obs[:3], dtype=float)
            target = np.asarray(obs[36:39], dtype=float)
            dist_h = float(np.linalg.norm(pos[:2] - target[:2]))
            # 夹爪开关量不限幅 (1.0 被 clip(-0.6,0.6) 截成 0.6 → 卡"抓取" 坑已踩)
            u_grip = 1.0 if dist_h < 0.03 else 0.0
            return np.concatenate([u_xyz, [u_grip]])

        sim.accel.forward = ff_forward   # 替换前馈加速器
        tr = sim.run()
        ok = bool(tr["done"][-1])
        n_ok += 1 if ok else 0
        print(f"  ep{ep + 1}: {len(tr['t'])}帧 · {'✅ 完成' if ok else '⚠️ 未完成'} "
              f"({tr['t'][-1]:.1f}s · dist {tr['dist'][-1]:.4f} · 接触 {max(tr['contact_p']):.2f})")
    print(f"\n🏁 训练模型仿真验证: {n_ok}/{n_episodes} 轮完成")
    return n_ok == n_episodes


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
