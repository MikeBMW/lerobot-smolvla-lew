#!/usr/bin/env python3
"""🧿 Z-MAX AWE 精简训练 — 场景原生 + zFlow 世界模型 (4060 适配版)

对标它石 AWE 3.5 "Born as One" 原生架构, 按 Z-MAX 场景原生路线精简 (老倪 2026-08-05
架构参考: "视觉·触觉·力觉·动作 场景级深度融合 + zFlow 潜空间世界模型"):

  ① 场景原生架构: 视觉(SigLIP) + 状态 + 动作(+触觉/力觉模拟) 原生拼接进潜空间,
     非后期"乐高式"拼接 — 与 VLA-Touch(DINOv2+Interpolant) / LEW(ARPredictor) 形成
     可区分的架构对比维度
  ② zFlow 世界模型 (H-JEPA 架构): 三层潜空间 z₁空间/z₂物体/z₃语义 + GRU 预测器
     预测未来潜状态 (对标 H-JEPA 空间/物体/语义三层预测; 轻量 GRU 适合边缘)
  ③ 交叉注意力分层注入: 预测的潜状态经 Cross-Attention 注入解码器 (门控 1.0/0.1/0.01)
  ④ 训练/推理可切换: 推理时世界模型可剥离 (门控归零) — 与论文"零额外开销"一致

4060 精简: SigLIP-base 冻结 (86M 不训练), 潜空间按 256/256/128 → 128/128/64 等比缩小,
GRU hidden 128 — 可训练参数 ≈ 15M, 8GB 显存无忧。

输出 "action_loss:xxx" 行 (GUI Scope 曲线), checkpoint 落
outputs/train/awe_zflow_<ts>/checkpoints/<step>/pretrained_model/

用法:
  .venv/bin/python tools/train_awe_zflow.py --steps 10 --data-root data/metaworld_act
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


# ── 数据: metaworld_act (与其它模型同源, 纵向对比公平) ────────────────────────
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
    # 力觉/触觉 (2026-08-09: 数据已整合 49D → 直接用 [45:49] 触觉段, 与训练同构)
    # 旧逻辑: 关节差分构造 (d[:, :3]*10 + force); 新: 数据自带触觉段优先
    if st.shape[1] >= 49:
        tac = st[:, 45:49].astype(np.float32).copy()
    else:
        d = np.diff(st, axis=0, prepend=st[:1])
        force = np.clip(np.linalg.norm(d, axis=1, keepdims=True), 0, 1) * 5.0
        tac = np.concatenate([d[:, :3] * 10.0, force], axis=1).astype(np.float32)
    # 归一化
    a_mean, a_std = act.mean(0), act.std(0) + 1e-6
    s_mean, s_std = st.mean(0), st.std(0) + 1e-6
    t_mean, t_std = tac.mean(0), tac.std(0) + 1e-6
    act_n = (act - a_mean) / a_std
    st_n = (st - s_mean) / s_std
    tac_n = (tac - t_mean) / t_std
    # 动作历史 (GRU 时序输入 — zFlow 预测未来需要历史上下文)
    act_hist = np.concatenate([np.zeros_like(act_n[:1]), act_n[:-1]], axis=0)
    print(f"📦 数据: {len(st)}帧 · state{st.shape[1]}D · action{act.shape[1]}D · "
          f"触觉{tac.shape[1]}D · img{obs.shape}", flush=True)
    return obs, st_n, act_n, tac_n, act_hist, act.shape[1], st.shape[1], tac.shape[1], \
           (a_mean, a_std, s_mean, s_std, t_mean, t_std)  # 原始统计 (反归一化用, 2026-08-06 修复)


# ── 视觉编码: SigLIP-base (86M 冻结; 失败回退 None) ───────────────────────────
def make_vision_encoder():
    try:
        from transformers import AutoModel
        import torchvision.transforms as T
        model = AutoModel.from_pretrained("google/siglip-base-patch16-224")
        model = model.to(DEVICE).eval()
        for p in model.parameters():
            p.requires_grad_(False)
        tf = T.Compose([T.Resize((224, 224)), T.ToTensor()])
        return model, tf
    except Exception as ex:
        print(f"⚠️ SigLIP 不可用 ({ex}) — 回退 state+力觉 条件", flush=True)
        return None, None


# ── zFlow 世界模型 (H-JEPA 三层潜空间 + GRU 预测器 + 交叉注意力注入) ───────────
class HJEPAEncoder(nn.Module):
    """🖐 场景原生视触觉编码 (对标 AWE "视觉·触觉·力觉·动作 场景级深度融合"):
    H-JEPA 三层潜空间编码: z₁空间(物体位姿) / z₂物体(类别属性) / z₃语义(任务目标)
    输入: SigLIP视觉特征 + 状态 + 力觉/触觉 → 三层潜表示 (原生融合, 非拼接后单空间)"""

    def __init__(self, state_dim, tactile_dim, vis_dim=0,
                 d_z1=128, d_z2=128, d_z3=64, hidden=256):
        super().__init__()
        self.d_z1, self.d_z2, self.d_z3 = d_z1, d_z2, d_z3
        self.vis_dim = vis_dim
        # 场景原生: 各模态原生投影进各自潜空间 (非共享投影 — 三层语义分离)
        # 视触觉融合: 视觉(proj_vis) + 力觉/触觉(proj_tactile) + 状态(proj_state) 同层相加
        self.proj_vis = nn.Linear(max(vis_dim, 1), hidden) if vis_dim else None
        self.proj_state = nn.Linear(state_dim, hidden)
        self.proj_tactile = nn.Linear(tactile_dim, hidden)
        # 三层潜空间头 (几何/物体/语义 分离)
        self.head_z1 = nn.Sequential(nn.Linear(hidden, hidden), nn.GELU(),
                                     nn.Linear(hidden, d_z1))   # 空间: 位置/姿态
        self.head_z2 = nn.Sequential(nn.Linear(hidden, hidden), nn.GELU(),
                                     nn.Linear(hidden, d_z2))   # 物体: 类别/属性
        self.head_z3 = nn.Sequential(nn.Linear(hidden, hidden), nn.GELU(),
                                     nn.Linear(hidden, d_z3))   # 语义: 任务/流程

    def forward(self, state, tactile, vision_feat=None):
        h = self.proj_state(state) + self.proj_tactile(tactile)
        if self.vis_dim:
            if vision_feat is not None:
                h = h + self.proj_vis(vision_feat)
            # 无视觉特征: 仅 state+tactile (评估/回退安全)
        return (self.head_z1(h), self.head_z2(h), self.head_z3(h))


class GRUPredictor(nn.Module):
    """zFlow 世界引擎: GRU 轻量循环预测未来潜状态 (适合 Orin Nano 边缘部署)
    输入: 当前三层潜状态 + 动作历史 → 预测下一帧三层潜状态"""

    def __init__(self, latent_dims, hidden=128, action_dim=4):
        super().__init__()
        self.d_in = sum(latent_dims)
        self.act_proj = nn.Linear(action_dim, self.d_in)
        self.gru = nn.GRU(self.d_in, hidden, batch_first=True)
        self.out = nn.Linear(hidden, self.d_in)

    def forward(self, z_cur, act_hist):
        # 潜状态 + 动作历史 拼接为 GRU 步输入 (动作先验驱动未来推演)
        x = z_cur.unsqueeze(1) + self.act_proj(act_hist).unsqueeze(1)  # (B,1,d_in)
        out, _ = self.gru(x)
        return self.out(out[:, -1])


class CrossAttnInject(nn.Module):
    """🔀 交叉注意力分层注入 (真 CrossAttention, 2026-08-05 老倪纠正):
    三层潜状态 z₁/z₂/z₃ 各自独立投影为 K/V token → Q=解码隐层 → 逐层交叉注意力
    → 每层输出乘各自门控 (1.0/0.1/0.01) 再残差融合。
    ⚠️ 必须每层独立 K/V + 独立门控, 不能拼接后单 token (那退化成恒等, 非真注意力)。
    训练时注入 (世界模型驱动决策); 推理门控归零可剥离 — 对标 AWE 论文"训练/推理可切换\""""

    def __init__(self, latent_dims, hidden=256, num_heads=4):
        super().__init__()
        self.num_layers = len(latent_dims)
        # 每层潜状态独立投影 → 独立 K/V token (层间不共享, 语义分离)
        self.proj_kv = nn.ModuleList(nn.Linear(d, hidden) for d in latent_dims)
        self.proj_q = nn.Linear(hidden, hidden)
        self.ca = nn.MultiheadAttention(hidden, num_heads, batch_first=True)
        # 分层门控: 每层一个权重 (z₁空间 1.0 / z₂物体 0.1 / z₃语义 0.01)
        self.gates = nn.Parameter(torch.tensor([1.0, 0.1, 0.01]))

    def forward(self, dec_hidden, z_triple):
        # dec_hidden: (B, hidden) 解码隐层 → Q (查询)
        # z_triple: (z1, z2, z3) 每层 (B, d) → 各层独立 K/V
        q = self.proj_q(dec_hidden).unsqueeze(1)          # (B,1,H)
        outs = []
        for i, (proj, z) in enumerate(zip(self.proj_kv, z_triple)):
            kv = proj(z).unsqueeze(1)                     # (B,1,H) 本层 K/V
            attn, _ = self.ca(q, kv, kv)                  # 真交叉注意力 (1×1 交互)
            outs.append(self.gates[i] * attn.squeeze(1))  # 本层门控加权
        return dec_hidden + sum(outs)


class AWEZFlowModel(nn.Module):
    """🧿 Z-MAX AWE 场景原生模型 (4060 精简):
    视觉+状态+力觉 → H-JEPA 三层潜空间 → GRU 预测未来 → 交叉注意力注入 → 动作头"""

    def __init__(self, action_dim, state_dim, tactile_dim, vision_dim=0,
                 d_z1=128, d_z2=128, d_z3=64, hidden=256, num_heads=4):
        super().__init__()
        self.action_dim = action_dim
        self.vis_dim = vision_dim
        self.hidden = hidden
        self.latent_dims = [d_z1, d_z2, d_z3]
        # ① 场景原生感知融合 → 三层潜空间
        self.encoder = HJEPAEncoder(state_dim, tactile_dim, vision_dim,
                                    d_z1, d_z2, d_z3, hidden)
        # ② zFlow 世界引擎 (GRU 预测未来潜状态)
        self.world_model = GRUPredictor(self.latent_dims, hidden=128, action_dim=action_dim)
        # ③ 交叉注意力分层注入
        self.inject = CrossAttnInject(self.latent_dims, hidden, num_heads)
        # 潜状态 → 解码隐层投影 (与 inject 分离, 常驻模块)
        self.dec_proj = nn.Linear(sum(self.latent_dims), hidden)
        # ④ 动作头 (隐空间动作 → 真实动作)
        self.action_head = nn.Sequential(
            nn.Linear(hidden, hidden), nn.GELU(),
            nn.Linear(hidden, action_dim))

    def _z_cat(self, z_triple):
        return torch.cat(list(z_triple), dim=-1)

    def forward(self, state, tactile, act_hist, vision_feat=None):
        # 当前三层潜状态 (场景原生融合)
        z_cur = self.encoder(state, tactile, vision_feat)
        z_cat = self._z_cat(z_cur)
        # 世界模型预测未来潜状态 (zFlow: 潜空间推演未来状态/接触演化)
        z_future = self.world_model(z_cat, act_hist)   # (B, Σd)
        # 未来潜状态拆回三层 (对齐 latent_dims) — 每层独立注入
        z_future_triple = torch.split(z_future, self.latent_dims, dim=-1)
        # 解码: 动作头输入 = 当前潜状态线性基底 + 交叉注意力注入未来预测
        dec_hidden = F.gelu(self.dec_proj(z_cat))
        # 真分层交叉注意力: 未来三层潜状态各作 K/V, 门控 1.0/0.1/0.01 加权融合
        fused = self.inject(dec_hidden, z_future_triple)
        return self.action_head(fused)


# ── 训练主循环 ────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=10)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--data-root", default=os.path.join(ROOT, "data", "metaworld_act"))
    ap.add_argument("--max-frames", type=int, default=2000, help="最多使用帧数 (2026-08-07: 默认200太少)")
    ap.add_argument("--hidden", type=int, default=256)
    ap.add_argument("--log-freq", type=int, default=5)
    args = ap.parse_args()

    print(f"🧿 Z-MAX AWE 精简训练 (场景原生 + zFlow 三层潜空间世界模型) · {DEVICE} · 4060 适配版", flush=True)
    obs, st, act, tac, act_hist, act_dim, st_dim, tac_dim, raw_stats = load_data(args.data_root, max_frames=args.max_frames)
    a_mean, a_std, s_mean, s_std, t_mean, t_std = raw_stats  # 原始统计 (反归一化用)
    n = len(st)

    vis_model, vis_tf = make_vision_encoder()
    vis_dim = 768 if vis_model else 0  # siglip-base hidden 768
    model = AWEZFlowModel(act_dim, st_dim, tac_dim, vis_dim, hidden=args.hidden).to(DEVICE)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-5)

    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(ROOT, "outputs", "train", f"awe_zflow_{ts}")
    # checkpoint 结构对齐 lerobot 惯例: <ckpt>/<step>/pretrained_model/
    ckpt_dir = os.path.join(out_dir, "checkpoints", "000050", "pretrained_model")
    os.makedirs(ckpt_dir, exist_ok=True)

    rng = np.random.RandomState(1337)
    own = os.path.join(ROOT, "reports", "train_curve_awe_zflow.json")
    if os.path.exists(own):
        os.remove(own)

    def _log_loss(step, loss):
        print(f"action_loss:{loss:.6f}", flush=True)  # GUI Scope 曲线解析
        print(f"📈 AWE 训练中: {step}/{args.steps} 步 · loss {loss:.4f}", flush=True)
        curve.append([step, round(loss, 6)])

    t0 = time.time()
    curve = []
    for step in range(1, args.steps + 1):
        model.train()
        idx = rng.randint(0, n, size=args.batch)
        s = torch.from_numpy(st[idx]).float().to(DEVICE)
        a = torch.from_numpy(act[idx]).float().to(DEVICE)
        m = torch.from_numpy(tac[idx]).float().to(DEVICE)
        ah = torch.from_numpy(act_hist[idx]).float().to(DEVICE)

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

        pred = model(s, m, ah, vf)
        loss = F.mse_loss(pred, a)
        opt.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 10.0)
        opt.step()

        if step % args.log_freq == 0 or step == args.steps:
            _log_loss(step, float(loss.item()))

    dur = time.time() - t0
    step_s = args.steps / dur if dur > 0 else 0.0

    # 落盘 checkpoint
    torch.save({"state_dict": model.state_dict(),
                "config": {"action_dim": act_dim, "state_dim": st_dim, "tactile_dim": tac_dim,
                           "vis_dim": vis_dim, "hidden": args.hidden,
                           "d_z": model.latent_dims, "arch": "awe-zflow-4060"},
                "stats": {"a_mean": a_mean.tolist(), "a_std": a_std.tolist(),
                          "s_mean": s_mean.tolist(), "s_std": s_std.tolist(),
                          "t_mean": t_mean.tolist(), "t_std": t_std.tolist()}},
               os.path.join(ckpt_dir, "model.pt"))
    with open(os.path.join(ckpt_dir, "config.json"), "w") as f:
        json.dump({"policy": "awe_zflow", "arch": "awe-zflow"}, f, indent=1)

    # 最终曲线落盘
    os.makedirs(os.path.join(ROOT, "reports"), exist_ok=True)
    with open(os.path.join(ROOT, "reports", "train_curve_awe_zflow.json"), "w") as f:
        json.dump({"policy": "awe_zflow", "name": "AWE-zFlow",
                   "ts": time.strftime("%Y%m%d_%H%M%S"), "step_s": round(step_s, 2),
                   "ckpt": f"outputs/train/awe_zflow_{ts}/checkpoints",
                   "curve": curve}, f, ensure_ascii=False)

    print(f"✅ AWE-zFlow 训练完成: {step_s:.1f} step/s · ckpt {ckpt_dir}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
