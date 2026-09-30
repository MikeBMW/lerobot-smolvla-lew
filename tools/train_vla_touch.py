#!/usr/bin/env python3
"""🖐 VLA-Touch 精简训练 — 触觉增强控制器 (4060 适配版)

对标 VLA-Touch (RA-L 2026, github.com/jxbi1010/VLA-Touch) 的 Manipulation 层:
  base VLA π(a|s,I) 生成动作块 → Interpolant 策略 π_I(â|s,a,m) 用触觉信号精炼动作。

4060 精简改造 (对比官方):
  · base VLA: 不加载 RDT-1B (7B 太大) → 用轻量 DiT-B 同构 (hidden 256, 1层) 冻结, 或纯控制器模式
  · 视觉: DINOv2-small (22M, 可加载即用; 无网/显存紧 → 自动回退 state-only)
  · 触觉: GelSight marker 跟踪模拟 — metaworld 无真触觉, 用 state 差分构造低维力信号 m_t
  · 核心: StochasticInterpolants 桥式扩散 (官方 bridge_model.py 精简: velocity_loss + q_sample)

输出: 与 lerobot 训练日志兼容的 "action_loss:xxx" 行 (GUI Scope 曲线直接可用),
      checkpoint 落 outputs/train/vla_touch_<ts>/checkpoints/ (pretrained_model 结构供评估复用)

用法:
  .venv/bin/python tools/train_vla_touch.py --steps 10 --data-root data/metaworld_act
"""
import argparse
import json
import os
import sys
import time

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


# ── 数据: metaworld_act (与三模型对比同源, 公平可比) ─────────────────────────
def load_data(root, max_frames=200):
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    ds = LeRobotDataset("lerobot/pusht", root=root)
    n = len(ds)
    # 🐛 2026-08-06 修复: len(ds) 按 meta 帧数(4500) 但 hf 表只有 3600 行 →
    #   索引 ≥3600 越界 (3608 out of bounds); 用 hf 实际行数截断
    try:
        n = min(n, len(ds._ensure_reader().hf_dataset))
    except Exception:
        pass
    step = max(1, n // max_frames)
    idxs = list(range(0, n, step))[:max_frames]
    states, actions, imgs = [], [], []
    for i in idxs:
        item = ds[i]
        states.append(item["observation.state"].numpy().astype(np.float32))
        actions.append(item["action"].numpy().astype(np.float32))
        imgs.append(item["observation.image"].numpy().astype(np.float32))
    obs = np.stack(imgs)
    st = np.stack(states)
    act = np.stack(actions)
    # 触觉信号 (2026-08-09: 数据已整合 49D → 直接用 [45:49] 触觉段, 与训练同构)
    # 旧逻辑: 关节差分构造 (d[:, :3]*10 + force); 新: 数据自带触觉段优先
    if st.shape[1] >= 49:
        tactile = st[:, 45:49].astype(np.float32).copy()
    else:
        d = np.diff(st, axis=0, prepend=st[:1])
        force = np.clip(np.linalg.norm(d, axis=1, keepdims=True), 0, 1) * 5.0
        tactile = np.concatenate([d[:, :3] * 10.0, force], axis=1).astype(np.float32)
    # 归一化
    a_mean, a_std = act.mean(0), act.std(0) + 1e-6
    s_mean, s_std = st.mean(0), st.std(0) + 1e-6
    t_mean, t_std = tactile.mean(0), tactile.std(0) + 1e-6
    act_n = (act - a_mean) / a_std
    st_n = (st - s_mean) / s_std
    tac_n = (tactile - t_mean) / t_std
    print(f"📦 数据: {len(st)}帧 · state{st.shape[1]}D · action{act.shape[1]}D · "
          f"触觉{tactile.shape[1]}D · img{obs.shape}", flush=True)
    return obs, st_n, act_n, tac_n, act.shape[1], st.shape[1], tactile.shape[1]


# ── 视觉编码: DINOv2-small (22M, 4060 无压力; 失败回退 None) ──────────────────
def make_vision_encoder():
    try:
        from transformers import AutoModel
        import torchvision.transforms as T
        model = AutoModel.from_pretrained("facebook/dinov2-small")
        model = model.to(DEVICE).eval()
        for p in model.parameters():
            p.requires_grad_(False)
        tf = T.Compose([T.Resize((224, 224)), T.ToTensor()])
        return model, tf
    except Exception as ex:
        print(f"⚠️ DINOv2 不可用 ({ex}) — 回退 state-only 条件", flush=True)
        return None, None


# ── Interpolant 控制器 (官方 StochasticInterpolants 精简: velocity net) ──────
class StateEncoder(nn.Module):
    """官方 bridge_controller.state_encoder: Linear→GELU×3 → hidden"""

    def __init__(self, obs_dim, hidden=256):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(obs_dim, hidden), nn.GELU(),
            nn.Linear(hidden, hidden), nn.GELU(),
            nn.Linear(hidden, hidden), nn.GELU(),
        )

    def forward(self, x):
        return self.net(x)


class VelocityNet(nn.Module):
    """桥式扩散速度网络: 输入 (x_t, t, cond) → 速度场 v

    官方 bridge_model.py velocity_loss: v_net 学习 interpolant 的速度场"""

    def __init__(self, action_dim, hidden=256, cond_dim=256):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(action_dim + 1 + cond_dim, hidden), nn.GELU(),
            nn.Linear(hidden, hidden), nn.GELU(),
            nn.Linear(hidden, hidden), nn.GELU(),
            nn.Linear(hidden, action_dim),
        )

    def forward(self, x_t, t, cond):
        return self.net(torch.cat([x_t, t, cond], dim=-1))


class InterpolantPolicy(nn.Module):
    """StochasticInterpolants 桥式扩散 (4060 精简):
    x0 = VLA 动作(用 x1 加噪近似, 或 base 动作) → x1 = 专家动作; cond = 视觉+触觉+状态"""

    def __init__(self, action_dim, state_dim, tactile_dim, vision_dim=0, hidden=256):
        super().__init__()
        self.action_dim = action_dim
        self.vis_dim = vision_dim
        self.cond_dim = hidden + vision_dim  # state_encoder(hidden) + 视觉特征(可选)
        # StateEncoder 编码 state+tactile → hidden; 视觉特征在 _cond 里拼接
        self.state_encoder = StateEncoder(state_dim + tactile_dim, hidden)
        self.velocity_net = VelocityNet(action_dim, self.cond_dim, self.cond_dim)

    def _cond(self, state, tactile, vis_feat):
        parts = [self.state_encoder(torch.cat([state, tactile], dim=-1))]
        if self.vis_dim:
            # 视觉条件: 有特征用之, 无则补零 (结构与训练一致, 评估/无网回退安全)
            if vis_feat is not None:
                parts.append(vis_feat)
            else:
                parts.append(torch.zeros(state.shape[0], self.vis_dim, device=state.device))
        return torch.cat(parts, dim=-1)

    def q_sample(self, x0, x1, t, gamma=0.01):
        """插值 + 噪声 (官方 interpolant: x_t = (1-t)x0 + t*x1 + γ·N(0,1))"""
        eps = torch.randn_like(x1)
        xt = (1 - t) * x0 + t * x1 + gamma * eps
        return xt, eps

    def velocity_loss(self, x0, x1, cond):
        """官方 velocity_loss: ‖v_net(x_t,t,cond) - (x1-x0)‖²  (gamma→0 极限)"""
        t = torch.rand(x0.shape[0], 1, device=x0.device)
        xt, _ = self.q_sample(x0, x1, t)
        target = x1 - x0
        pred = self.velocity_net(xt, t, cond)
        return F.mse_loss(pred, target)

    @torch.no_grad()
    def sample(self, x0, cond, diffuse_steps=10):
        """确定性 ODE 采样 (官方 sde_vs / sample): 从 VLA 动作走向专家动作"""
        x = x0.clone()
        dt = 1.0 / diffuse_steps
        for i in range(diffuse_steps):
            t = torch.full((x.shape[0], 1), i * dt, device=x.device)
            v = self.velocity_net(x, t, cond)
            x = x + v * dt
        return x


# ── 训练主循环 ────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=10)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--data-root", default=os.path.join(ROOT, "data", "metaworld_act"))
    ap.add_argument("--hidden", type=int, default=256)
    ap.add_argument("--log-freq", type=int, default=5)
    args = ap.parse_args()

    print(f"🖐 VLA-Touch 精简训练 (Interpolant 触觉控制器) · {DEVICE} · 4060 适配版", flush=True)
    obs, st, act, tac, act_dim, st_dim, tac_dim = load_data(args.data_root)
    n = len(st)

    vis_model, vis_tf = make_vision_encoder()
    vis_dim = 384 if vis_model else 0  # dinov2-small hidden
    policy = InterpolantPolicy(act_dim, st_dim, tac_dim, vis_dim, args.hidden).to(DEVICE)
    opt = torch.optim.AdamW(policy.parameters(), lr=args.lr, weight_decay=1e-5)

    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(ROOT, "outputs", "train", f"vla_touch_{ts}")
    # checkpoint 结构对齐 lerobot 惯例: <ckpt>/<step>/pretrained_model/ (find_ckpt glob 兼容)
    ckpt_dir = os.path.join(out_dir, "checkpoints", "000050", "pretrained_model")
    os.makedirs(ckpt_dir, exist_ok=True)

    rng = np.random.RandomState(1337)
    # 只重置自己的旧曲线 (与 on_train 语义一致)
    own = os.path.join(ROOT, "reports", "train_curve_vla_touch.json")
    if os.path.exists(own):
        os.remove(own)

    def _log_loss(step, loss):
        print(f"action_loss:{loss:.6f}", flush=True)  # GUI Scope 曲线解析
        print(f"📈 VLA-Touch 训练中: {step}/{args.steps} 步 · loss {loss:.4f}", flush=True)

    t0 = time.time()
    for step in range(1, args.steps + 1):
        policy.train()
        # 采样 batch (x0=VLA动作≈x1+噪声, 官方桥式: 从 VLA 粗动作精炼到专家动作)
        idx = rng.randint(0, n, size=args.batch)
        s = torch.from_numpy(st[idx]).float().to(DEVICE)
        a = torch.from_numpy(act[idx]).float().to(DEVICE)
        m = torch.from_numpy(tac[idx]).float().to(DEVICE)

        # 视觉特征 (可选): DINOv2 编码 batch 图像
        vf = None
        if vis_model:
            try:
                from PIL import Image
                batch_imgs = []
                for i in idx:
                    im = obs[i].transpose(1, 2, 0)
                    im = (im - im.min()) / (im.max() - im.min() + 1e-6)
                    im = (im * 255).astype(np.uint8)
                    batch_imgs.append(vis_tf(Image.fromarray(im)).to(DEVICE))
                vimg = torch.stack(batch_imgs)
                with torch.no_grad():
                    vf = vis_model(pixel_values=vimg).last_hidden_state.mean(dim=1)
            except Exception as ex:
                if step == 1:
                    print(f"⚠️ 视觉编码失败 ({ex}) — 本步跳过视觉条件", flush=True)

        cond = policy._cond(s, m, vf)
        # x0 = x1 + 噪声 (模拟 VLA 粗动作) — 桥式扩散起点
        x0 = a + torch.randn_like(a) * 0.1
        loss = policy.velocity_loss(x0, a, cond)
        opt.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(policy.parameters(), 10.0)
        opt.step()

        if step % args.log_freq == 0 or step == args.steps:
            _log_loss(step, float(loss.item()))

    dur = time.time() - t0
    step_s = args.steps / dur if dur > 0 else 0.0

    # 落盘 checkpoint (pretrained_model 结构, 与 lerobot HubMixin 兼容)
    ckpt = ckpt_dir
    os.makedirs(ckpt, exist_ok=True)
    torch.save({"state_dict": policy.state_dict(),
                "config": {"action_dim": act_dim, "state_dim": st_dim, "tactile_dim": tac_dim,
                           "vis_dim": vis_dim, "hidden": args.hidden, "diffuse_steps": 10,
                           "arch": "interpolant-vla-touch-4060"},
                "stats": {"a_mean": act.mean(0).tolist(), "a_std": act.std(0).tolist()}},
               os.path.join(ckpt, "model.pt"))
    with open(os.path.join(ckpt, "config.json"), "w") as f:
        json.dump({"policy": "vla_touch", "arch": "interpolant"}, f, indent=1)

    # 最终曲线落盘 (GUI Scope / 对比评估数据源)
    import re as _re
    os.makedirs(os.path.join(ROOT, "reports"), exist_ok=True)
    with open(os.path.join(ROOT, "reports", "train_curve_vla_touch.json"), "w") as f:
        json.dump({"policy": "vla_touch", "name": "VLA-Touch",
                   "ts": time.strftime("%Y%m%d_%H%M%S"), "step_s": round(step_s, 2),
                   "ckpt": f"outputs/train/vla_touch_{ts}/checkpoints"}, f, ensure_ascii=False)

    print(f"✅ VLA-Touch 训练完成: {step_s:.1f} step/s · ckpt {ckpt_dir}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
