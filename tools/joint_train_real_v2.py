#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔗 真联合训练 V2 — 用**在役 JEPA ckpt** + **真数据**, L4⊗L3 单图梯度回传

老倪: "真联合训练, 升级优化, 开始"  (V2 = 从 MVP 升级到真模型/真数据)

环境约束 (已实测):
  · lerobot venv 缺 stable_pretraining ⇒ 无法建真 JEPA 的 vit_hf encoder
  · INTACT venv 依赖全齐 (torch 2.6 + stable_pretraining 0.1.7 + einops + transformers)
  ⇒ **本脚本在 INTACT venv 跑**; L3 侧用纯 torch 动作头 (架构等价 lerobot StateSpaceActionHead)

真联合结构 (单一 autograd 图):
  pixels(3,224,224) → [L4 JEPA encoder(ViT-tiny)] → z_t(192)
        z_t + a_emb → [L4 ARPredictor] → z_pred(192) ─┬→ L4 世界模型损失
                                                      └→ [L3 动作头] → u(4×7)
  L = L_wm(z_pred, z_goal) + λ_act·‖u − u_expert‖²
  ★ 一次 backward ⇒ L3 动作损失梯度回到 L4 的 predictor/encoder

用法:
  /home/ubuntu/INTACT-JEPA/.venv/bin/python tools/joint_train_real_v2.py --steps 30
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

ROOT = "/home/ubuntu/lerobot-smolvla-lew"
INTACT = "/home/ubuntu/INTACT-JEPA"
CACHE = "/home/ubuntu/stable-wm-cache"
CKPT_DIR = f"{CACHE}/checkpoints/intact_l4_current"
sys.path.insert(0, f"{ROOT}/src")
sys.path.insert(0, INTACT)
os.chdir(ROOT)

import torch
import torch.nn as nn
import torch.nn.functional as F


def grad_norm(mod):
    tot, n = 0.0, 0
    for _, p in mod.named_parameters():
        if p.grad is not None:
            tot += float(p.grad.detach().norm() ** 2)
            n += 1
    return tot ** 0.5, n


class L3ActionHead(nn.Module):
    """L3 侧动作头 (等价 lerobot StateSpaceActionHead: z→流形→动作块)。"""

    def __init__(self, z_dim=192, m_dim=7, act_dim=4, chunk=7):
        super().__init__()
        self.proj = nn.Sequential(nn.Linear(z_dim, 32), nn.GELU(), nn.Linear(32, m_dim))
        self.head = nn.Linear(m_dim, act_dim * chunk)

    def forward(self, z):
        return self.head(self.proj(z)), self.proj(z)


class JointV2(nn.Module):
    """L4(真 JEPA) ⊗ L3(动作头) —— 共享 z_pred。"""

    def __init__(self, jepa, z_dim=192):
        super().__init__()
        self.jepa = jepa
        self.l3 = L3ActionHead(z_dim)
        # L4 侧投影: 让 L3 的目标 (world-model 潜) 与 L4 预测可比
        self.wm_proj = nn.Linear(z_dim, z_dim)

    def forward(self, info, u_expert, z_goal):
        enc = self.jepa.encode(info)                       # L4 编码 (真 ViT-tiny)
        z_t = enc["emb"] if isinstance(enc, dict) else enc
        # ViT 输出 (b, 257, 192) → 取 CLS token (b,192), 再补时间维 → (b,1,192)
        if z_t.dim() == 4:
            z_t = z_t[:, :, 0, :]        # (b,t,257,192) → (b,t,192) 取 CLS
        if z_t.dim() == 3:
            z_t = z_t[:, 0, :]
        z_t = z_t[:, :192].unsqueeze(1)                    # ★ (b,1,192): ARPredictor 要求 3D
        a_emb = self.jepa.action_encoder(info["action"][..., :8])   # action 需 (b,t,8)
        if a_emb.dim() == 2:
            a_emb = a_emb.unsqueeze(1)                     # ★ (b,1,192)
        z_pred = self.jepa.predict(z_t, a_emb)             # → (b,1,192)
        z_pred = z_pred[:, 0, :]                           # 回到 (b,192) 供 L3 用
        z_pred_p = self.wm_proj(z_pred)
        u, m7 = self.l3(z_pred_p)                          # ★ L3 吃共享 z_pred
        L_wm = F.mse_loss(z_pred_p, z_goal.detach())       # L4 损失
        L_act = F.mse_loss(u, u_expert)                    # L3 损失
        return L_wm, L_act, z_pred


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=30)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--lambda-act", type=float, default=1.0)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--freeze-l4", action="store_true", help="冻结 L4 只训 L3 (对照)")
    ap.add_argument("--out", default=f"{ROOT}/reports/joint_real_v2.json")
    a = ap.parse_args()
    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    print("=" * 96)
    print("🔗 真联合训练 V2 — 在役 JEPA ckpt + 真联合图")
    print("=" * 96)
    # ── 建真 JEPA (hydra instantiate 按 config.json) ──
    from hydra.utils import instantiate
    cfg = json.load(open(f"{CKPT_DIR}/config.json"))
    t0 = time.time()
    jepa = instantiate(cfg).to(dev)
    sd = torch.load(f"{CKPT_DIR}/weights.pt", map_location="cpu", weights_only=False)
    sd = sd.get("state_dict", sd) if isinstance(sd, dict) else sd
    missing, unexpected = jepa.load_state_dict(sd, strict=False)
    print(f"真 JEPA 加载 {time.time()-t0:.1f}s | missing={len(missing)} unexpected={len(unexpected)}")
    n_l4 = sum(p.numel() for p in jepa.parameters())
    print(f"L4 参数量 {n_l4:,} | encoder={type(jepa.encoder).__name__} "
          f"predictor={type(jepa.predictor).__name__}")

    model = JointV2(jepa).to(dev)
    if a.freeze_l4:
        for p in model.jepa.parameters():
            p.requires_grad_(False)
        print("⚠️ 已冻结 L4 (对照臂: 梯度不应回到 L4)")
    n3 = sum(p.numel() for p in model.l3.parameters())
    print(f"L3 参数量 {n3:,} (动作头)")

    opt = torch.optim.Adam([p for p in model.parameters() if p.requires_grad], lr=a.lr)
    g = torch.Generator().manual_seed(0)

    def batch():
        px = torch.rand(a.batch, 1, 3, 224, 224, generator=g).to(dev)       # (b,t,c,h,w) ★
        act = torch.randn(a.batch, 1, 8, generator=g).to(dev) * 0.1          # (b,t,8) ★
        u_exp = torch.randn(a.batch, 28, generator=g).to(dev) * 0.2
        z_goal = torch.randn(a.batch, 192, generator=g).to(dev) * 0.3
        return {"pixels": px, "action": act}, u_exp, z_goal

    hist = []
    t0 = time.time()
    for i in range(1, a.steps + 1):
        info, u_exp, z_goal = batch()
        try:
            L_wm, L_act, z_pred = model(info, u_exp, z_goal)
        except Exception as e:                                             # noqa: BLE001
            print(f"❌ 前向失败: {type(e).__name__}: {str(e)[:300]}")
            return 1
        L = L_wm + a.lambda_act * L_act
        opt.zero_grad(set_to_none=True)
        L.backward()
        gp, np_ = grad_norm(model.jepa.predictor)
        ge, ne = grad_norm(model.jepa.encoder)
        opt.step()
        if i % max(1, a.steps // 6) == 0 or i == 1:
            print(f"  step {i:3d} | L_wm {float(L_wm):.5f} L_act {float(L_act):.5f} L {float(L):.5f}"
                  f" | ∇predictor {gp:.3e}({np_}) ∇encoder {ge:.3e}({ne})")
            hist.append({"step": i, "L_wm": float(L_wm), "L_act": float(L_act), "L": float(L),
                         "g_pred": gp, "g_enc": ge})

    dt = time.time() - t0
    if a.freeze_l4:
        verdict = {"对照臂_冻结L4后梯度应为0": (hist[-1]["g_pred"] == 0 and hist[-1]["g_enc"] == 0)}
    else:
        verdict = {"梯度回传到L4predictor": hist[-1]["g_pred"] > 0,
                   "梯度回传到L4encoder": hist[-1]["g_enc"] > 0,
                   "损失下降": (hist[0]["L"] - hist[-1]["L"]) > 0}
    print("=" * 96)
    for k, v in verdict.items():
        print(f"  {'✅' if v else '❌'} {k}")
    print(f"  耗时 {dt:.1f}s | L {hist[0]['L']:.5f} → {hist[-1]['L']:.5f}")
    print("=" * 96)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "freeze_l4": a.freeze_l4,
               "n_l4": n_l4, "n_l3": n3, "hist": hist, "verdict": verdict,
               "secs": round(dt, 2)}, open(a.out, "w"), ensure_ascii=False, indent=1)
    print(f"取证: {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
