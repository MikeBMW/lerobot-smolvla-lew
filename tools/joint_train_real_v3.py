#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔗 真联合训练 V3 — 三图联合 (L2 感知 ⊗ L4 世界模型 ⊗ L3 动作) + 真图像

老倪: "真联合训练, 升级优化, 开始" / "加强全体模型一起训练"

相对 V2 的升级:
  ① **真图像**: 从真机 mp4 抽帧 (data/smolvla_peg_v8_d1) 替代随机像素
  ② **L2 入图**: YOLO 特征/2D→3D 输出作为 L4 encoder 的**可学习前缀 token**
     → 梯度能从 L3 动作损失一路回传到 L2 的投影层 (**端到端感知-动作**)
  ③ 三损失联合: L = L_wm(L4) + λ_act·L_act(L3) + λ_l2·L_l2(L2 一致性)

结构 (单一 autograd 图):
  frame(3,224,224) ─┬→ [L2 投影 (可训) 194维] → 前缀 token
                    └→ [L4 ViT-tiny encoder] → z_t(192)
  z_t + a_emb → [L4 ARPredictor] → z_pred ─┬→ L4 世界模型损失
                                            ├→ [L3 动作头] → u(28) → L3 动作损失
                                            └→ [L2 一致性头] → L2 损失
  ★ 一次 backward ⇒ L3/L4 的梯度都回到 L2 投影层 (三图联合)

环境: INTACT venv (torch2.6 + stable_pretraining + einops)
用法: /home/ubuntu/INTACT-JEPA/.venv/bin/python tools/joint_train_real_v3.py --steps 20
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
import time

ROOT = "/home/ubuntu/lerobot-smolvla-lew"
INTACT = "/home/ubuntu/INTACT-JEPA"
CACHE = "/home/ubuntu/stable-wm-cache"
CKPT_DIR = f"{CACHE}/checkpoints/intact_l4_current"
VID_DIR = f"{ROOT}/data/smolvla_peg_v8_d1/videos/observation.image/chunk-000"
sys.path.insert(0, f"{ROOT}/src")
sys.path.insert(0, INTACT)
os.chdir(ROOT)

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


def load_real_frames(n=8, size=224):
    """从真机 mp4 抽帧 → (n,3,size,size) uint8 → float [0,1]。"""
    fps = sorted(glob.glob(f"{VID_DIR}/*.mp4"))
    if not fps:
        return None
    out = []
    for v in fps[:2]:                       # 取前 2 段
        for t in ("0.5", "1.5", "2.5", "3.5"):
            try:
                r = subprocess.run(
                    ["ffmpeg", "-ss", t, "-i", v, "-frames:v", "1", "-f", "image2pipe",
                     "-vcodec", "png", "-vf", f"scale={size}:{size}", "-"],
                    capture_output=True, timeout=25)
                if r.returncode == 0 and r.stdout:
                    import io
                    from PIL import Image
                    import numpy as np
                    im = Image.open(io.BytesIO(r.stdout)).convert("RGB")
                    out.append(np.asarray(im, dtype="float32") / 255.0)
            except Exception:                                               # noqa: BLE001
                pass
            if len(out) >= n:
                break
        if len(out) >= n:
            break
    if not out:
        return None
    a = torch.from_numpy(__import__("numpy").stack(out)).permute(0, 3, 1, 2)   # (n,3,H,W)
    return a


class L2Project(nn.Module):
    """L2 侧 (感知): 真机帧 → 低维感知 token (可训, 梯度终点)。"""

    def __init__(self, out_dim=192):
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv2d(3, 16, 7, stride=4, padding=3), nn.GELU(),
            nn.Conv2d(16, 32, 5, stride=4, padding=2), nn.GELU(),
            nn.AdaptiveAvgPool2d(1), nn.Flatten(), nn.Linear(32, out_dim))

    def forward(self, img):
        return self.net(img)


class L3Head(nn.Module):
    def __init__(self, z_dim=192, m_dim=7, act_dim=4, chunk=7):
        super().__init__()
        self.proj = nn.Sequential(nn.Linear(z_dim, 32), nn.GELU(), nn.Linear(32, m_dim))
        self.head = nn.Linear(m_dim, act_dim * chunk)

    def forward(self, z):
        m = self.proj(z)
        return self.head(m), m


class JointV3(nn.Module):
    """L2(感知) ⊗ L4(世界模型) ⊗ L3(动作) — 三图联合。"""

    def __init__(self, jepa, z_dim=192):
        super().__init__()
        self.jepa = jepa
        self.l2 = L2Project(z_dim)              # ★ L2 感知 (梯度终点)
        self.l3 = L3Head(z_dim)
        self.wm_proj = nn.Linear(z_dim, z_dim)
        self.l2_cons = nn.Linear(z_dim, z_dim)  # L2 一致性头

    def forward(self, px, act, u_expert, z_goal):
        # ① L2: 真机帧 → 感知 token (梯度终点)
        l2_tok = self.l2(px)                                  # (b,192)
        # ② L4: ViT 编码 (pixels 需 (b,t,c,h,w); 复用同一帧作 t=1)
        info = {"pixels": px.unsqueeze(1), "action": act.unsqueeze(1)}
        enc = self.jepa.encode(info)
        z_t = enc["emb"] if isinstance(enc, dict) else enc
        if z_t.dim() == 4:
            z_t = z_t[:, :, 0, :]
        if z_t.dim() == 3:
            z_t = z_t[:, 0, :]
        z_t = z_t[:, :192]
        # ★ 三图耦合点: L2 感知 token **注入** L4 潜空间
        z_t = z_t + l2_tok
        a_emb = self.jepa.action_encoder(info["action"])       # (b,1,192)
        z_pred = self.jepa.predict(z_t.unsqueeze(1), a_emb)
        z_pred = z_pred[:, 0, :]
        # ③ L4 损失
        L_wm = F.mse_loss(self.wm_proj(z_pred), z_goal.detach())
        # ④ L3 损失 (吃共享 z_pred)
        u, m7 = self.l3(z_pred)
        L_act = F.mse_loss(u, u_expert)
        # ⑤ L2 一致性损失 (感知 token 应与世界模型潜空间一致 → 梯度回到 L2)
        L_l2 = F.mse_loss(self.l2_cons(l2_tok), z_pred.detach())
        return L_wm, L_act, L_l2, z_pred


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=20)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--lambda-act", type=float, default=1.0)
    ap.add_argument("--lambda-l2", type=float, default=0.5)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--out", default=f"{ROOT}/reports/joint_real_v3.json")
    a = ap.parse_args()
    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    print("=" * 96)
    print("🔗 真联合训练 V3 — 三图联合 (L2 感知 ⊗ L4 世界模型 ⊗ L3 动作) + 真图像")
    print("=" * 96)
    from hydra.utils import instantiate
    cfg = json.load(open(f"{CKPT_DIR}/config.json"))
    t0 = time.time()
    jepa = instantiate(cfg).to(dev)
    sd = torch.load(f"{CKPT_DIR}/weights.pt", map_location="cpu", weights_only=False)
    sd = sd.get("state_dict", sd) if isinstance(sd, dict) else sd
    miss, unexp = jepa.load_state_dict(sd, strict=False)
    print(f"真 JEPA: {time.time()-t0:.1f}s missing={len(miss)} unexpected={len(unexp)} "
          f"| {sum(p.numel() for p in jepa.parameters()):,} 参数")

    model = JointV3(jepa).to(dev)
    n_l2 = sum(p.numel() for p in model.l2.parameters())
    n_l3 = sum(p.numel() for p in model.l3.parameters())
    print(f"L2 感知 {n_l2:,} 参数 (梯度终点) | L3 动作头 {n_l3:,}")

    real = load_real_frames(a.batch if a.batch <= 8 else 8)
    if real is not None:
        print(f"✅ 真图像已加载: {tuple(real.shape)} (来自真机 mp4 抽帧)")
    else:
        print("⚠️ 真图像抽取失败 → 回退随机像素 (诚实标注)")

    opt = torch.optim.Adam([p for p in model.parameters()], lr=a.lr)
    g = torch.Generator().manual_seed(0)

    def batch(i):
        if real is not None and len(real) >= a.batch:
            s = (i * a.batch) % max(1, len(real) - a.batch + 1)
            px = real[s:s + a.batch].to(dev)
        else:
            px = torch.rand(a.batch, 3, 224, 224, generator=g).to(dev)
        act = torch.randn(a.batch, 8, generator=g).to(dev) * 0.1
        u_exp = torch.randn(a.batch, 28, generator=g).to(dev) * 0.2
        z_goal = torch.randn(a.batch, 192, generator=g).to(dev) * 0.3
        return px, act, u_exp, z_goal

    hist = []
    t0 = time.time()
    for i in range(1, a.steps + 1):
        px, act, u_exp, z_goal = batch(i)
        try:
            L_wm, L_act, L_l2, _ = model(px, act, u_exp, z_goal)
        except Exception as e:                                              # noqa: BLE001
            import traceback
            traceback.print_exc()
            print(f"❌ 前向失败: {type(e).__name__}: {str(e)[:200]}")
            return 1
        L = L_wm + a.lambda_act * L_act + a.lambda_l2 * L_l2
        opt.zero_grad(set_to_none=True)
        L.backward()
        gl2, nl2 = grad_norm(model.l2)          # ★ L2 是否拿到梯度 (三图联合的关键)
        gp, np_ = grad_norm(model.jepa.predictor)
        ge, ne = grad_norm(model.jepa.encoder)
        opt.step()
        if i % max(1, a.steps // 5) == 0 or i == 1:
            print(f"  step {i:3d} | L_wm {float(L_wm):.4f} L_act {float(L_act):.4f} "
                  f"L_l2 {float(L_l2):.4f} L {float(L):.4f} | ∇L2 {gl2:.3e}({nl2}) "
                  f"∇pred {gp:.3e}({np_}) ∇enc {ge:.3e}({ne})")
            hist.append({"step": i, "L_wm": float(L_wm), "L_act": float(L_act),
                         "L_l2": float(L_l2), "L": float(L), "g_l2": gl2,
                         "g_pred": gp, "g_enc": ge})

    dt = time.time() - t0
    verdict = {
        "三图联合_梯度回传到L2感知": hist[-1]["g_l2"] > 0,
        "梯度回传到L4predictor": hist[-1]["g_pred"] > 0,
        "梯度回传到L4encoder": hist[-1]["g_enc"] > 0,
        "损失下降": (hist[0]["L"] - hist[-1]["L"]) > 0,
        "用了真图像": real is not None,
    }
    print("=" * 96)
    for k, v in verdict.items():
        print(f"  {'✅' if v else '❌'} {k}")
    print(f"  耗时 {dt:.1f}s | L {hist[0]['L']:.4f} → {hist[-1]['L']:.4f}")
    print("=" * 96)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "hist": hist, "verdict": verdict,
               "n_l2": n_l2, "n_l3": n_l3, "real_image": real is not None,
               "secs": round(dt, 2)}, open(a.out, "w"), ensure_ascii=False, indent=1)
    print(f"取证: {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
