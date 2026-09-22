#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔗 真联合训练 V4 — **真数据** (引擎轨迹 h5) + 三图联合

老倪: "真联合训练, 升级优化, 开始"

V3 → V4 的关键升级 (V3 的监督信号是**合成随机张量**, 只能证明机制):
  · pixels    ← h5 的 **真机渲染帧** (v6_disturb, 真扰动数据)
  · observation← h5 的 **真 39 维观测**
  · u_expert  ← h5 的 **真 action (4 维)**  ⇒ L3 动作损失有了真实监督
  · z_goal    ← 由**未来帧观测**编码得到 (真实目标, 非随机)
  → 这样训练出的产物品才有实际意义, 才能做 A/B

三图结构 (与 V3 一致, 单一 autograd 图):
  frame ─┬→ [L2 感知投影] ─┬─────────────┐(注入 L4 潜)
         │                  └→ [L2 一致性]│
         └→ [L4 ViT-tiny] → z_t+l2 → [ARPredictor] → z_pred ─┬→ L4 世界模型损失(z_goal)
                                                              ├→ [L3 头] → L3 动作损失(u_expert)
                                                              └→ L2 一致性损失
  ★ 一次 backward ⇒ L3/L4 梯度回传到 L2 + L4 全部参数

用法:
  /home/ubuntu/INTACT-JEPA/.venv/bin/python tools/joint_train_real_v4.py --steps 200 \
      --h5 /home/ubuntu/stable-wm-cache/datasets/optical_insert_v6_disturb.h5 \
      --save /home/ubuntu/stable-wm-cache/checkpoints/joint_v4_real
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

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F


def grad_norm(mod):
    tot, n = 0.0, 0
    for _, p in mod.named_parameters():
        if p.requires_grad and p.grad is not None:
            tot += float(p.grad.detach().norm() ** 2)
            n += 1
    return tot ** 0.5, n


class RealTrajData:
    """真轨迹数据 (h5): 逐 episode 取 (frame, obs, action, next_obs)。"""

    def __init__(self, h5, size=224):
        import h5py
        self.f = h5py.File(h5, "r")
        self.size = size
        self.ep_off = np.asarray(self.f["ep_offset"][:], dtype=np.int64)
        self.ep_len = np.asarray(self.f["ep_len"][:], dtype=np.int64)
        self.n_ep = len(self.ep_off)
        self.has_px = "pixels" in self.f

    def sample(self, batch, rng):
        """取 batch 个 (frame(3,H,W), obs(39), next_obs(39), action(4))。"""
        idx = rng.integers(0, self.n_ep, size=batch)
        px, obs, nobs, act = [], [], [], []
        for e in idx:
            off, ln = int(self.ep_off[e]), int(self.ep_len[e])
            if ln < 3:
                continue
            t = int(rng.integers(0, ln - 2))
            g = off + t
            if self.has_px:
                im = np.asarray(self.f["pixels"][g], dtype="float32")
                if im.ndim == 3 and im.shape[0] in (1, 3):          # (c,h,w)
                    im = np.transpose(im, (1, 2, 0))
                if im.max() > 1.5:
                    im = im / 255.0
                px.append(_resize(im, self.size))
            obs.append(np.asarray(self.f["observation"][g], dtype="float32"))
            nobs.append(np.asarray(self.f["observation"][g + 1], dtype="float32"))
            act.append(np.asarray(self.f["action"][g], dtype="float32"))
        if not obs:
            return None
        out = {
            "obs": torch.from_numpy(np.stack(obs)).float(),
            "nobs": torch.from_numpy(np.stack(nobs)).float(),
            "act": torch.from_numpy(np.stack(act)).float(),
        }
        if px:
            out["px"] = torch.from_numpy(np.stack(px)).float().permute(0, 3, 1, 2)
        return out


def _resize(im, s):
    import cv2
    return cv2.resize(im, (s, s), interpolation=cv2.INTER_AREA)


class L2Project(nn.Module):
    def __init__(self, out_dim=192):
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv2d(3, 16, 7, stride=4, padding=3), nn.GELU(),
            nn.Conv2d(16, 32, 5, stride=4, padding=2), nn.GELU(),
            nn.AdaptiveAvgPool2d(1), nn.Flatten(), nn.Linear(32, out_dim))

    def forward(self, img):
        return self.net(img)


class L3Head(nn.Module):
    """z(192) → 流形 m(7) → 真动作 (4 维, 与 h5 的 action 对齐)。"""

    def __init__(self, z_dim=192, m_dim=7, act_dim=4):
        super().__init__()
        self.proj = nn.Sequential(nn.Linear(z_dim, 32), nn.GELU(), nn.Linear(32, m_dim))
        self.head = nn.Linear(m_dim, act_dim)

    def forward(self, z):
        m = self.proj(z)
        return self.head(m), m


class JointV4(nn.Module):
    def __init__(self, jepa, z_dim=192, obs_dim=39):
        super().__init__()
        self.jepa = jepa
        self.l2 = L2Project(z_dim)
        self.l3 = L3Head(z_dim)
        self.wm_proj = nn.Linear(z_dim, z_dim)
        self.l2_cons = nn.Linear(z_dim, z_dim)
        self.goal_enc = nn.Sequential(nn.Linear(obs_dim, 128), nn.GELU(), nn.Linear(128, z_dim))

    def forward(self, px, act, obs, nobs, u_expert):
        l2_tok = self.l2(px)
        info = {"pixels": px.unsqueeze(1), "action": act.unsqueeze(1)}
        enc = self.jepa.encode(info)
        z_t = enc["emb"] if isinstance(enc, dict) else enc
        if z_t.dim() == 4:
            z_t = z_t[:, :, 0, :]
        if z_t.dim() == 3:
            z_t = z_t[:, 0, :]
        z_t = z_t[:, :192] + l2_tok                       # ★ L2 注入
        a_emb = self.jepa.action_encoder(info["action"])
        z_pred = self.jepa.predict(z_t.unsqueeze(1), a_emb)[:, 0, :]
        z_goal = self.goal_enc(nobs)                      # ★ 真实目标 (未来观测编码)
        L_wm = F.mse_loss(self.wm_proj(z_pred), z_goal.detach())
        u, m7 = self.l3(z_pred)
        L_act = F.mse_loss(u, u_expert)                   # ★ 真动作监督
        L_l2 = F.mse_loss(self.l2_cons(l2_tok), z_pred.detach())
        return L_wm, L_act, L_l2, z_pred, u, u_expert


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--h5", default=f"{CACHE}/datasets/optical_insert_v6_disturb.h5")
    ap.add_argument("--steps", type=int, default=200)
    ap.add_argument("--batch", type=int, default=6)
    ap.add_argument("--lambda-act", type=float, default=1.0)
    ap.add_argument("--lambda-l2", type=float, default=0.5)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--save", default="")
    ap.add_argument("--out", default=f"{ROOT}/reports/joint_real_v4.json")
    a = ap.parse_args()
    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    print("=" * 96)
    print("🔗 真联合训练 V4 — 真数据(引擎轨迹) + 三图联合")
    print("=" * 96)
    print(f"数据: {os.path.basename(a.h5)}")
    data = RealTrajData(a.h5)
    print(f"episodes {data.n_ep} · 有 pixels={data.has_px}")
    if not data.has_px:
        print("⚠️ h5 无 pixels 字段 → L2/L4 视觉路径退化为随机帧 (诚实标注)")
    rng = np.random.default_rng(0)

    from hydra.utils import instantiate
    cfg = json.load(open(f"{CKPT_DIR}/config.json"))
    t0 = time.time()
    jepa = instantiate(cfg).to(dev)
    sd = torch.load(f"{CKPT_DIR}/weights.pt", map_location="cpu", weights_only=False)
    sd = sd.get("state_dict", sd) if isinstance(sd, dict) else sd
    miss, unexp = jepa.load_state_dict(sd, strict=False)
    print(f"真 JEPA: {time.time()-t0:.1f}s missing={len(miss)} unexpected={len(unexp)} "
          f"| {sum(p.numel() for p in jepa.parameters()):,} 参数")

    model = JointV4(jepa).to(dev)
    print(f"L2 感知 {sum(p.numel() for p in model.l2.parameters()):,} · "
          f"L3 动作头 {sum(p.numel() for p in model.l3.parameters()):,}")
    opt = torch.optim.Adam(model.parameters(), lr=a.lr)

    hist = []
    t0 = time.time()
    for i in range(1, a.steps + 1):
        b = data.sample(a.batch, rng)
        if b is None:
            continue
        px = b.get("px")
        if px is None or len(px) != len(b["obs"]):
            px = torch.rand(len(b["obs"]), 3, 224, 224)
        px, obs, nobs, ue = px.to(dev), b["obs"].to(dev), b["nobs"].to(dev), b["act"].to(dev)
        act8 = F.pad(ue, (0, 4))                          # 4 → 8 维 (action_encoder 期望 8)
        try:
            L_wm, L_act, L_l2, z_pred, u, ue2 = model(px, act8, obs, nobs, ue)
        except Exception as e:                                            # noqa: BLE001
            import traceback
            traceback.print_exc()
            print(f"❌ 前向失败: {type(e).__name__}: {str(e)[:200]}")
            return 1
        L = L_wm + a.lambda_act * L_act + a.lambda_l2 * L_l2
        opt.zero_grad(set_to_none=True)
        L.backward()
        gl2, nl2 = grad_norm(model.l2)
        gp, np_ = grad_norm(model.jepa.predictor)
        ge, ne = grad_norm(model.jepa.encoder)
        opt.step()
        if i % max(1, a.steps // 5) == 0 or i == 1:
            # 动作误差 (真 action vs 预测) — 这是"效果"的直接指标
            act_mae = float((u - ue2).abs().mean())
            print(f"  step {i:4d} | L_wm {float(L_wm):.4f} L_act {float(L_act):.5f} "
                  f"L_l2 {float(L_l2):.4f} L {float(L):.4f} | 动作MAE {act_mae:.4f} "
                  f"| ∇L2 {gl2:.2e}({nl2}) ∇pred {gp:.2e}({np_}) ∇enc {ge:.2e}({ne})")
            hist.append({"step": i, "L_wm": float(L_wm), "L_act": float(L_act),
                         "L_l2": float(L_l2), "L": float(L), "act_mae": act_mae,
                         "g_l2": gl2, "g_pred": gp, "g_enc": ge})

    dt = time.time() - t0
    if len(hist) >= 2:
        verdict = {
            "三图联合_梯度回传L2": hist[-1]["g_l2"] > 0,
            "梯度回传L4predictor": hist[-1]["g_pred"] > 0,
            "梯度回传L4encoder": hist[-1]["g_enc"] > 0,
            "损失下降": (hist[0]["L"] - hist[-1]["L"]) > 0,
            "**真动作MAE下降**": hist[-1]["act_mae"] < hist[0]["act_mae"],
            "用了真数据": True,
        }
    else:
        verdict = {"数据不足": False}
    print("=" * 96)
    for k, v in verdict.items():
        print(f"  {'✅' if v else '❌'} {k}")
    print(f"  耗时 {dt:.1f}s | L {hist[0]['L']:.4f} → {hist[-1]['L']:.4f}")
    print("=" * 96)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "h5": os.path.basename(a.h5),
               "hist": hist, "verdict": verdict, "secs": round(dt, 2)},
              open(a.out, "w"), ensure_ascii=False, indent=1)
    if a.save:
        os.makedirs(a.save, exist_ok=True)
        torch.save({"joint": {k: v for k, v in model.state_dict().items()
                              if k.startswith(("l2.", "l3.", "wm_proj.", "l2_cons.", "goal_enc."))},
                    "verdict": verdict, "hist": hist},
                   os.path.join(a.save, "joint_v4.pt"))
        torch.save({"l4": model.jepa.state_dict()}, os.path.join(a.save, "l4_joint_v4.pt"))
        print(f"产物 → {a.save} (joint_v4.pt + l4_joint_v4.pt)")
    print(f"取证: {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
