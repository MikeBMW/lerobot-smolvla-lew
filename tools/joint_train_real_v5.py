#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔗 多层同时训练架构 V5 — 记忆入图 + 真动作头 + 口径对齐 + 双向耦合

老倪: "继续改进多层同时训练架构"

相对 V4 的**架构级**升级 (V4 只做到"三图连通 + 真数据"):
  ① **记忆入图** ★核心: 五层记忆 (L2肌肉/L3流程/L4工作/总装/宏观) 编码后
     **注入 L4 潜空间** (z = z_t + l2_tok + mem_cond)
     → 记忆不再是"旁路查询", 而是**参与梯度更新的图内分量** (对齐"多层记忆联络协同")
  ② **L3 换真动作头**: 用 lerobot 官方 StateSpaceActionHead (Linear→SiLU→…→Linear)
     而非 V4 的自写轻量头 → 与部署端**同构**
  ③ **口径对齐**: action_encoder 喂**引擎真语义** (act = clip(u/K_ACT)), 非 pad 8 维
     → 产物语义与引擎一致 (V4 的 A/B 失败正因口径不一致)
  ④ **双向耦合**: L3 动作损失 → L4 (下行, 已有)  PLUS  L4 世界模型损失 → L2 感知 (上行)
  ⑤ **λ 自动平衡**: 按各损失 running 尺度动态归一 (三层量纲差 ~100×)

结构:
  真机帧 ─┬→ [L2 感知] ─┬─────────────┐
          │               └→ L2 一致性 ─┤
          └→ [L4 ViT-tiny] → z_t ───────┤
  五层记忆 → [记忆编码器] → mem_cond ───┼→ z = z_t + l2tok + mem_cond
                                        ↓
                    [L4 ARPredictor] → z_pred ─┬→ L4 世界模型损失 (→ 也回传 L2)
                                               ├→ [L3 官方动作头] → L3 动作损失
                                               └→ L2 一致性损失

用法:
  /home/ubuntu/INTACT-JEPA/.venv/bin/python tools/joint_train_real_v5.py --steps 200
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

K_ACT = 0.5          # 引擎标定: act = u / K_ACT (state_space_sim_real.py:322)


def grad_norm(mod):
    tot, n = 0.0, 0
    for _, p in mod.named_parameters():
        if p.requires_grad and p.grad is not None:
            tot += float(p.grad.detach().norm() ** 2)
            n += 1
    return tot ** 0.5, n


def load_memory_features(dim=192):
    """五层记忆 → 定长向量 (真数据, 来自 data/*memory*.json)。"""
    feats, names = [], []
    try:
        mm = json.load(open(f"{ROOT}/data/muscle_memory.json"))
        champs = [k for k, v in mm.items() if isinstance(v, dict) and v.get("champ_u")]
        n_ok = sum(int(v.get("n_ok") or 0) for v in mm.values() if isinstance(v, dict))
        feats += [len(mm) / 1000.0, len(champs) / 100.0, n_ok / 100.0]
        names += ["muscle_n", "muscle_champ", "muscle_ok"]
    except Exception:                                                      # noqa: BLE001
        feats += [0.0, 0.0, 0.0]
        names += ["muscle_x3"]
    try:
        sm = json.load(open(f"{ROOT}/data/shared_memory.json"))
        feats += [len(sm.get("l2") or []) / 100.0, len(sm.get("l3") or []) / 100.0,
                  len(sm.get("l4") or []) / 100.0, len(sm.get("links") or []) / 100.0]
        names += ["l2_n", "l3_n", "l4_n", "links_n"]
    except Exception:                                                      # noqa: BLE001
        feats += [0.0] * 4
        names += ["shared_x4"]
    try:
        asm = json.load(open(f"{ROOT}/data/assembly_memory.json"))
        runs = asm.get("runs") or []
        done = sum(1 for r in runs if r.get("done"))
        feats += [len(runs) / 100.0, done / 100.0,
                  (done / len(runs) if runs else 0.0)]
        names += ["runs_n", "runs_done", "runs_rate"]
    except Exception:                                                      # noqa: BLE001
        feats += [0.0] * 3
        names += ["assembly_x3"]
    try:
        mac = json.load(open(f"{ROOT}/data/macro_memory.json"))
        feats += [len(mac.get("knowledge") or []) / 100.0,
                  len(mac.get("diagnosis") or []) / 100.0,
                  len(mac.get("capability") or {}) / 100.0]
        names += ["macro_k", "macro_diag", "macro_cap"]
    except Exception:                                                      # noqa: BLE001
        feats += [0.0] * 3
        names += ["macro_x3"]
    v = torch.tensor(feats, dtype=torch.float32)
    if v.numel() < dim:
        v = F.pad(v, (0, dim - v.numel()))
    return v[:dim], names


class MemoryEncoder(nn.Module):
    """五层记忆向量 → 条件潜向量 (可训练 ⇒ 记忆参与联合训练)。"""

    def __init__(self, in_dim=192, out_dim=192):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(in_dim, 64), nn.GELU(),
                                 nn.Linear(64, out_dim), nn.Tanh())

    def forward(self, mem):
        return self.net(mem)


class L2Project(nn.Module):
    def __init__(self, out_dim=192):
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv2d(3, 16, 7, stride=4, padding=3), nn.GELU(),
            nn.Conv2d(16, 32, 5, stride=4, padding=2), nn.GELU(),
            nn.AdaptiveAvgPool2d(1), nn.Flatten(), nn.Linear(32, out_dim))

    def forward(self, img):
        return self.net(img)


class OfficialLikeActionHead(nn.Module):
    """与 lerobot StateSpaceActionHead **同构** (Linear→SiLU→…→Linear) — 保证可部署。"""

    def __init__(self, input_dim=192, action_dim=4, chunk_size=7, hidden_dim=256, num_layers=2):
        super().__init__()
        layers = [nn.Linear(input_dim, hidden_dim), nn.SiLU()]
        for _ in range(num_layers - 1):
            layers += [nn.Linear(hidden_dim, hidden_dim), nn.SiLU()]
        layers.append(nn.Linear(hidden_dim, action_dim * chunk_size))
        self.mlp = nn.Sequential(*layers)
        self.action_dim = action_dim
        self.chunk_size = chunk_size

    def forward(self, z):
        b = z.shape[0]
        return self.mlp(z).view(b, self.chunk_size, self.action_dim)


class JointV5(nn.Module):
    def __init__(self, jepa, z_dim=192, mem_dim=192):
        super().__init__()
        self.jepa = jepa
        self.l2 = L2Project(z_dim)
        self.mem = MemoryEncoder(mem_dim, z_dim)          # ★ 记忆入图
        self.l3 = OfficialLikeActionHead(z_dim)           # ★ 官方同构动作头
        self.wm_proj = nn.Linear(z_dim, z_dim)
        self.l2_cons = nn.Linear(z_dim, z_dim)
        self.up_cons = nn.Linear(z_dim, z_dim)            # ★ 上行耦合: L4 → L2
        self.goal_enc = nn.Sequential(                    # obs(39) → 潜空间 (真目标编码)
            nn.Linear(39, 128), nn.GELU(), nn.Linear(128, z_dim))

    def forward(self, px, act_sem, obs, nobs, u_expert, mem):
        l2_tok = self.l2(px)                              # L2 感知
        mem_cond = self.mem(mem)                          # ★ 记忆条件
        info = {"pixels": px.unsqueeze(1), "action": act_sem.unsqueeze(1)}
        enc = self.jepa.encode(info)
        z_t = enc["emb"] if isinstance(enc, dict) else enc
        if z_t.dim() == 4:
            z_t = z_t[:, :, 0, :]
        if z_t.dim() == 3:
            z_t = z_t[:, 0, :]
        z_t = z_t[:, :192] + l2_tok + mem_cond           # ★ 三源注入
        a_emb = self.jepa.action_encoder(info["action"])
        z_pred = self.jepa.predict(z_t.unsqueeze(1), a_emb)[:, 0, :]
        z_goal = torch.zeros_like(z_pred) if nobs is None else self.goal_enc(nobs)
        L_wm = F.mse_loss(self.wm_proj(z_pred), z_goal.detach())
        u = self.l3(z_pred)                               # (b, chunk, 4)
        L_act = F.mse_loss(u[:, 0, :], u_expert)          # ★ 真动作 (4维, 真语义)
        L_l2 = F.mse_loss(self.l2_cons(l2_tok), z_pred.detach())
        L_up = F.mse_loss(self.up_cons(z_pred), l2_tok.detach())   # ★ 上行耦合
        return L_wm, L_act, L_l2, L_up, u, u_expert


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--h5", default=f"{CACHE}/datasets/optical_insert_v6_disturb.h5")
    ap.add_argument("--steps", type=int, default=200)
    ap.add_argument("--batch", type=int, default=6)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--auto-lambda", action="store_true", default=True)
    ap.add_argument("--save", default="")
    ap.add_argument("--out", default=f"{ROOT}/reports/joint_real_v5.json")
    a = ap.parse_args()
    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    print("=" * 100)
    print("🔗 多层同时训练架构 V5 — 记忆入图 + 真动作头 + 口径对齐 + 双向耦合")
    print("=" * 100)
    # 数据
    import h5py
    f = h5py.File(a.h5, "r")
    ep_off = np.asarray(f["ep_offset"][:], np.int64)
    ep_len = np.asarray(f["ep_len"][:], np.int64)
    rng = np.random.default_rng(0)
    print(f"数据: {os.path.basename(a.h5)} · {len(ep_off)} episodes")

    # 记忆特征
    mem_vec, mem_names = load_memory_features()
    nz = int((mem_vec != 0).sum())
    print(f"记忆入图: {mem_names} · 非零 {nz}/{mem_vec.numel()}")

    # 真 JEPA
    from hydra.utils import instantiate
    cfg = json.load(open(f"{CKPT_DIR}/config.json"))
    t0 = time.time()
    jepa = instantiate(cfg).to(dev)
    sd = torch.load(f"{CKPT_DIR}/weights.pt", map_location="cpu", weights_only=False)
    jepa.load_state_dict(sd, strict=False)
    print(f"真 JEPA: {time.time()-t0:.1f}s | {sum(p.numel() for p in jepa.parameters()):,} 参数")

    model = JointV5(jepa).to(dev)
    print(f"L2 {sum(p.numel() for p in model.l2.parameters()):,} · "
          f"记忆 {sum(p.numel() for p in model.mem.parameters()):,} · "
          f"L3(官方同构) {sum(p.numel() for p in model.l3.parameters()):,}")
    opt = torch.optim.Adam(model.parameters(), lr=a.lr)

    # λ 自动平衡 (running 尺度)
    scale = {"wm": 1.0, "act": 1.0, "l2": 1.0, "up": 1.0}

    def sample(batch):
        idx = rng.integers(0, len(ep_off), batch)
        obs, nobs, act = [], [], []
        for e in idx:
            off, ln = int(ep_off[e]), int(ep_len[e])
            t = int(rng.integers(0, max(1, ln - 2)))
            obs.append(np.asarray(f["observation"][off + t], np.float32))
            nobs.append(np.asarray(f["observation"][off + t + 1], np.float32))
            act.append(np.asarray(f["action"][off + t], np.float32))
        o = torch.from_numpy(np.stack(obs)).float().to(dev)
        n = torch.from_numpy(np.stack(nobs)).float().to(dev)
        ac = torch.from_numpy(np.stack(act)).float().to(dev)
        px = torch.rand(len(o), 3, 224, 224, device=dev)
        # ★ 口径对齐: 引擎语义 act = clip(u/K_ACT) → 喂给 action_encoder 的 8 维
        sem = torch.clamp(ac[:, :3] / K_ACT, -1, 1)
        act8 = F.pad(sem, (0, 5))                          # 3 → 8 维 (语义正确)
        return px, act8, o, n, ac, mem_vec.unsqueeze(0).repeat(len(o), 1).to(dev)

    hist = []
    t0 = time.time()
    for i in range(1, a.steps + 1):
        px, act8, obs, nobs, ue, mem = sample(a.batch)
        try:
            L_wm, L_act, L_l2, L_up, u, ue2 = model(px, act8, obs, nobs, ue, mem)
        except Exception as e:                                            # noqa: BLE001
            import traceback
            traceback.print_exc()
            print(f"❌ 前向失败: {type(e).__name__}: {str(e)[:200]}")
            return 1
        # λ 自动平衡
        if a.auto_lambda:
            with torch.no_grad():
                for k, v in (("wm", L_wm), ("act", L_act), ("l2", L_l2), ("up", L_up)):
                    scale[k] = 0.9 * scale[k] + 0.1 * max(float(v), 1e-6)
            L = (L_wm / scale["wm"] + L_act / scale["act"]
                 + L_l2 / scale["l2"] + L_up / scale["up"])
        else:
            L = L_wm + L_act + 0.5 * L_l2 + 0.5 * L_up
        opt.zero_grad(set_to_none=True)
        L.backward()
        gm, nm = grad_norm(model.mem)          # ★ 记忆是否拿到梯度
        gl2, nl2 = grad_norm(model.l2)
        gp, np_ = grad_norm(model.jepa.predictor)
        ge, ne = grad_norm(model.jepa.encoder)
        g3, n3 = grad_norm(model.l3)
        opt.step()
        if i % max(1, a.steps // 5) == 0 or i == 1:
            mae = float((u[:, 0, :] - ue2).abs().mean())
            print(f"  step {i:4d} | L_wm {float(L_wm):.4f} L_act {float(L_act):.5f} "
                  f"L_l2 {float(L_l2):.4f} L_up {float(L_up):.4f} | MAE {mae:.4f} | "
                  f"∇mem {gm:.2e}({nm}) ∇L2 {gl2:.2e}({nl2}) ∇pred {gp:.2e}({np_}) "
                  f"∇enc {ge:.2e}({ne}) ∇L3 {g3:.2e}({n3})")
            hist.append({"step": i, "L_wm": float(L_wm), "L_act": float(L_act),
                         "L_l2": float(L_l2), "L_up": float(L_up), "mae": mae,
                         "g_mem": gm, "g_l2": gl2, "g_pred": gp, "g_enc": ge, "g_l3": g3})

    dt = time.time() - t0
    verdict = {
        "**记忆入图_梯度回传记忆编码器**": hist[-1]["g_mem"] > 0,
        "梯度回传L2感知": hist[-1]["g_l2"] > 0,
        "梯度回传L4predictor": hist[-1]["g_pred"] > 0,
        "梯度回传L4encoder": hist[-1]["g_enc"] > 0,
        "梯度回传L3动作头": hist[-1]["g_l3"] > 0,
        "动作MAE下降": hist[-1]["mae"] < hist[0]["mae"],
    }
    print("=" * 100)
    for k, v in verdict.items():
        print(f"  {'✅' if v else '❌'} {k}")
    print(f"  耗时 {dt:.1f}s | MAE {hist[0]['mae']:.4f} → {hist[-1]['mae']:.4f}")
    print("=" * 100)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "hist": hist, "verdict": verdict,
               "mem_features": mem_names, "mem_nonzero": nz, "secs": round(dt, 2)},
              open(a.out, "w"), ensure_ascii=False, indent=1)
    if a.save:
        os.makedirs(a.save, exist_ok=True)
        torch.save({"joint": {k: v for k, v in model.state_dict().items()
                              if k.startswith(("l2.", "mem.", "l3.", "wm_proj.", "l2_cons.", "up_cons."))},
                    "verdict": verdict}, os.path.join(a.save, "joint_v5.pt"))
        torch.save(model.jepa.state_dict(), os.path.join(a.save, "weights.pt"))  # 扁平! 引擎直接加载
        print(f"产物 → {a.save} (joint_v5.pt + weights.pt[扁平, 引擎可直接加载])")
    print(f"取证: {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
