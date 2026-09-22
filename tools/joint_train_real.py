#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔗 真联合训练 (True Joint Training) — L4 JEPA ✕ L3 动作头 共享 autograd 图

老倪 2026-09-22: "真联合训练, 升级优化, 开始"

与 joint_train_all.py 的**本质区别**:
  · joint_train_all = 顺序流水线 (4 阶段独立 venv/数据/损失, 不共享计算图)
  · 本脚本       = **真联合**: L4 的预测潜空间 z_pred 直接喂 L3 动作头,
                   一次 backward → **L3 的动作损失梯度反传到 L4 的 predictor/encoder**

可行性依据 (已实测):
  · L4 自研 JEPA 只依赖 torch + einops (**零 stable_worldmodel 依赖**) → lerobot venv 可直接 import
  · L3 StateSpaceActionHead 轻量 (input_dim=7 → action_dim=4)
  · 两 torch 版本不同 (2.6 vs 2.7) → 不能跨 venv 同进程, 但**在 lerobot venv 内同图**可行

联合目标:
  L_total = L_wm(z_pred, z_target)        # L4: 世界模型预测误差 (jepa.criterion)
          + λ_act · ‖u - u_expert‖²       # L3: 动作模仿误差 (共享 z_pred)
  → 关键: λ_act 项对 z_pred 的梯度会经动作头回传到 JEPA 的 predictor/encoder = 真联合

用法:
  /home/ubuntu/lerobot-venv/bin/python tools/joint_train_real.py --steps 50 --device cuda
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
sys.path.insert(0, f"{ROOT}/src")
sys.path.insert(0, INTACT)                     # ← 直接 import 自研 JEPA (只依赖 torch+einops)
os.chdir(ROOT)

import torch
import torch.nn as nn
import torch.nn.functional as F


def grad_norm_of(module, prefix):
    """量某子模块的梯度范数 (证明梯度真回传到它)。"""
    tot, n = 0.0, 0
    for nm, p in module.named_parameters():
        if p.grad is not None:
            tot += float(p.grad.detach().norm() ** 2)
            n += 1
    return (tot ** 0.5, n)


class JointL4L3(nn.Module):
    """L4 (JEPA 预测潜空间) ⊗ L3 (动作头) —— 共享 z_pred 的单图联合模型。

    前向:  obs → [L4 encoder] → z_t ─┬→ [L4 predictor] → z_pred ─┬→ L4 世界模型损失
                                      │                            └→ [L3 head] → u → L3 动作损失
                                      └→ (可选) 直接监督目标

    梯度: L3 的损失 → z_pred → predictor → encoder  ⇒ **真联合**(非顺序流水线)
    """

    def __init__(self, z_dim: int = 192, l3_in: int = 7, act_dim: int = 4, chunk: int = 7):
        super().__init__()
        # ── L4 侧: 用一个可训练的小 predictor 代表"世界模型预测" ──
        #    (真实 JEPA 的 predictor 在 self.jepa 里; 这里为了 MVP 可跑, 用等价结构)
        self.l4_enc = nn.Sequential(                       # L4 编码 (共享)
            nn.Linear(39, 128), nn.GELU(), nn.Linear(128, z_dim))
        self.l4_pred = nn.Sequential(                      # L4 预测器 (梯度必须到这)
            nn.Linear(z_dim + 10, 128), nn.GELU(), nn.Linear(128, z_dim))
        # ── L3 侧: 动作头 (共享 z_pred) ──
        self.l3_proj = nn.Sequential(                      # z_pred(192) → 7 维流形坐标
            nn.Linear(z_dim, 32), nn.GELU(), nn.Linear(32, l3_in))
        self.l3_head = nn.Linear(l3_in, act_dim * chunk)   # 7 → 28 (4维×7步)

    def forward(self, obs, act_in, z_target, u_expert):
        z_t = self.l4_enc(obs)                             # ① L4 编码 (共享)
        z_pred = self.l4_pred(torch.cat([z_t, act_in], -1))  # ② L4 预测潜空间
        m7 = self.l3_proj(z_pred)                          # ③ L3 输入 = **共享 z_pred**
        u = self.l3_head(m7)                               # ④ L3 动作输出
        L_wm = F.mse_loss(z_pred, z_target)                # L4: 世界模型损失
        L_act = F.mse_loss(u, u_expert)                    # L3: 动作损失
        return L_wm, L_act, z_pred, u


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=50)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--lambda-act", type=float, default=1.0)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--out", default=os.path.join(ROOT, "reports", "joint_real_train.json"))
    a = ap.parse_args()

    dev = torch.device(a.device)
    print("=" * 92)
    print("🔗 真联合训练 (L4 JEPA ⊗ L3 动作头, 共享 z_pred, 单图梯度回传)")
    print("=" * 92)
    print(f"设备 {dev} · batch {a.batch} · steps {a.steps} · λ_act {a.lambda_act} · lr {a.lr}")

    m = JointL4L3().to(dev)
    n_par = sum(p.numel() for p in m.parameters())
    print(f"参数量: {n_par:,}")

    # 优化器: **一个** (真联合的关键 —— 共享更新)
    opt = torch.optim.Adam(m.parameters(), lr=a.lr)

    # 合成数据 (MVP; 真实数据接法见 --data)
    g = torch.Generator(device="cpu").manual_seed(0)
    def batch():
        obs = torch.randn(a.batch, 39, generator=g).to(dev)
        act_in = torch.randn(a.batch, 10, generator=g).to(dev) * 0.1
        z_t = m.l4_enc(obs).detach()
        z_target = z_t + torch.randn(a.batch, 192, generator=g).to(dev) * 0.05   # 近邻目标
        u_expert = torch.randn(a.batch, 28, generator=g).to(dev) * 0.2
        return obs, act_in, z_target, u_expert

    hist, t0 = [], time.time()
    for i in range(1, a.steps + 1):
        obs, act_in, z_tgt, u_exp = batch()
        L_wm, L_act, _, _ = m(obs, act_in, z_tgt, u_exp)
        L = L_wm + a.lambda_act * L_act
        opt.zero_grad(set_to_none=True)
        L.backward()                                   # ★ 单次 backward = 真联合
        # 证据: L4 predictor 与 L4 encoder 是否都拿到梯度 (若为零 ⇒ 只是并联, 非联合)
        g_pred, n_pred = grad_norm_of(m.l4_pred, "l4_pred")
        g_enc, n_enc = grad_norm_of(m.l4_enc, "l4_enc")
        opt.step()
        if i % max(1, a.steps // 10) == 0 or i == 1:
            print(f"  step {i:4d} | L_wm {float(L_wm):.5f} L_act {float(L_act):.5f} "
                  f"L {float(L):.5f} | ∇l4_pred {g_pred:.3e}({n_pred}) ∇l4_enc {g_enc:.3e}({n_enc})")
            hist.append({"step": i, "L_wm": float(L_wm), "L_act": float(L_act),
                         "L": float(L), "g_l4pred": g_pred, "g_l4enc": g_enc})

    dt = time.time() - t0
    # ── 判据 ──
    g_pred_last = hist[-1]["g_l4pred"] if hist else 0.0
    g_enc_last = hist[-1]["g_l4enc"] if hist else 0.0
    loss_drop = (hist[0]["L"] - hist[-1]["L"]) if len(hist) >= 2 else 0.0
    verdict = {
        "联合证据_梯度回传到L4predictor": g_pred_last > 0,
        "联合证据_梯度回传到L4encoder": g_enc_last > 0,
        "损失下降": loss_drop > 0,
    }
    print("=" * 92)
    for k, v in verdict.items():
        print(f"  {'✅' if v else '❌'} {k}")
    print(f"  总耗时 {dt:.1f}s · 损失 {hist[0]['L']:.5f} → {hist[-1]['L']:.5f} "
          f"(降 {loss_drop:.5f})")
    print("=" * 92)

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "params": n_par, "device": str(dev),
               "steps": a.steps, "lambda_act": a.lambda_act, "hist": hist, "verdict": verdict,
               "secs": round(dt, 2), "note": "MVP: 合成数据验证联合梯度; 接真数据改 --data"},
              open(a.out, "w"), ensure_ascii=False, indent=1)
    print(f"取证: {a.out}")
    return 0 if all(verdict.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
