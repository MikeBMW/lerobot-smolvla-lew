#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧠 阶段专家 MOE —— 7 阶段 × 专家头 + 先验门控路由（升级自密集四头）

老倪 2026-09-24: "阶段专家MOE升级改造, 全系统模型微调, 开始"

设计动机（有实测依据）:
  密集架构下, 一个头要同时拟合"视觉认知"(L4) 与"接触动力学"(下降/抓取/插入力控相位)
  → 互相干扰。实测: 统一主干在闭环 A/B(n=10) **无差异**, 失败点**同源在接触段**。
  ⇒ 阶段专家: 每个专家只学自己阶段的动力学问 → 分工, 不互相稀释。

结构:
  SigLIP 768d 主干(冻结) → 融合 h
        ↓
  门控 g = softmax( 先验(stage one-hot) * P + 可学习 logits )   ← **先验路由, 抗崩塌**
        ↓
  [E0..E6] 7 个专家 (每个: L4认知预测头 + L3动作头)
        ↓
  out = Σ g_i · E_i(h)      (稠密聚合; 训练时 top-1 稀疏更新 → 专家专注)

阶段序: 接近/对位/下降/抓取/抬起/转移/插入 (与引擎 sched.stage() 一致)
路由信号: 数据自带 skill_ctx[:,13:20] (7 阶段概率), 不依赖引擎额外输入
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from joint_unified_backbone import MODEL, RealH5, make_loader  # noqa: E402

SWM = "/home/ubuntu/stable-wm-cache"
STAGES = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入"]
NS = len(STAGES)


class StageMoE(nn.Module):
    """共享主干 + 阶段专家（先验门控）"""

    def __init__(self, trunk, d=768, obs_dim=39, act_dim=4, chunk=7, mem_dim=13,
                 n_experts=NS, expert_hidden=192, freeze=1, prior_strength=4.0):
        super().__init__()
        self.trunk = trunk
        for p in self.trunk.parameters():
            p.requires_grad_(not freeze)
        self.n_experts = n_experts
        self.obs_dim, self.act_dim, self.chunk = obs_dim, act_dim, chunk

        # 共享融合: 视觉特征 + 本体 → h
        self.fuse = nn.Sequential(nn.Linear(d + obs_dim + mem_dim, 512), nn.SiLU(), nn.Linear(512, 256))

        # 门控: 先验(stage) + 可学习偏置 → logits(7)
        self.gate_prior = nn.Parameter(torch.eye(n_experts) * float(prior_strength))  # (NS, NS) 先验矩阵
        self.gate_mlp = nn.Sequential(nn.Linear(256 + n_experts, 128), nn.SiLU(), nn.Linear(128, n_experts))

        # 专家: 每个 = L4 认知预测 + L3 动作调度
        self.experts = nn.ModuleList()
        for _ in range(n_experts):
            self.experts.append(nn.ModuleDict({
                "l4": nn.Sequential(nn.Linear(256, expert_hidden), nn.SiLU(), nn.Linear(expert_hidden, obs_dim)),
                "l3": nn.Sequential(nn.Linear(256 + obs_dim, expert_hidden), nn.SiLU(),
                                    nn.Linear(expert_hidden, chunk * act_dim)),
            }))
        self.mem_dim = mem_dim

    def forward(self, px, obs, obs_next, mem, stage_p, hard=True, route="prior"):
        """px:(B,3,H,W) obs:(B,39) mem:(B,13) stage_p:(B,7) 先验阶段概率
        route: "prior"=**按阶段先验硬路由**(保证分化, 正解) / "soft"=学习门控(实测坍缩)"""
        feat = self.trunk(pixel_values=px).pooler_output if hasattr(self.trunk, "pooler_output") else None
        if feat is None:
            feat = self.trunk(pixel_values=px).last_hidden_state.mean(1)
        h = self.fuse(torch.cat([feat, obs, mem], dim=1))                 # (B,256)

        if route == "prior":
            # ★ 硬先验路由: 直接按阶段选择专家 (无自由学习 → 不可能坍缩)
            g = stage_p / stage_p.sum(1, keepdim=True).clamp_min(1e-6)
            g = torch.where(g.sum(1, keepdim=True) > 0.5, g,
                            torch.full_like(g, 1.0 / self.n_experts))
        else:
            prior = stage_p @ self.gate_prior
            logits = prior + self.gate_mlp(torch.cat([h, stage_p], dim=1))
            g = F.softmax(logits, dim=1)

        # 专家输出
        outs_o = torch.stack([e["l4"](h) for e in self.experts], dim=1)                     # (B,NS,39)
        hin = torch.cat([h, obs], dim=1)
        outs_a = torch.stack([e["l3"](hin).view(-1, self.chunk, self.act_dim) for e in self.experts], dim=1)  # (B,NS,T,4)

        if hard:      # top-1 稀疏: 只回传选中专家的梯度 → 专家专注自己阶段
            idx = g.argmax(1)
            w = F.one_hot(idx, self.n_experts).float()
            w = w + g - g.detach()           # STE: 前向硬、反向软
        else:
            w = g
        o_hat = (w.unsqueeze(-1) * outs_o).sum(1)                          # (B,39)
        u = (w.view(-1, self.n_experts, 1, 1) * outs_a).sum(1)             # (B,T,4)
        return {"o_hat": o_hat, "u": torch.tanh(u), "gate": g, "expert_id": g.argmax(1)}


def stage_from_ctx(skill_ctx, hard_argmax=True):
    """从 skill_ctx 提取阶段先验 (7,)。实测: dim13:20 即 7 阶段概率
    兼容单样本(24,)与批量(N,24)"""
    s = np.asarray(skill_ctx, dtype=np.float32)[..., 13:20]
    single = (s.ndim == 1)
    if single:
        s = s[None]
    s = np.clip(s, 0, None)
    rs = s.sum(-1, keepdims=True)
    rs[rs < 1e-6] = 1.0
    s = s / rs                                    # 归一成概率
    if hard_argmax:
        idx = s.argmax(-1)
        out = np.zeros_like(s)
        out[np.arange(len(s)), idx] = 1.0
        return out[0] if single else out
    return s[0] if single else s


class RealH5Stage(RealH5):
    """在 RealH5 基础上多返回**阶段先验** (来自 skill_ctx[:,13:20]) —— MOE 路由的信号源"""

    def __getitem__(self, i):
        obs, act, px, obs_next = super().__getitem__(i)
        gi = i
        for k in range(len(self.f)):
            if gi < self.off[k + 1]:
                f, j = self.f[k], gi - self.off[k]
                break
        sc = np.asarray(f["skill_ctx"][j], dtype=np.float32)
        return obs, act, px, obs_next, stage_from_ctx(sc)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=3000)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--wd", type=float, default=0.01)
    ap.add_argument("--stats", type=int, default=300)
    ap.add_argument("--progress-file", default="", help="真·实时进度 JSON（控制台进度条直读）")
    ap.add_argument("--progress-every", type=int, default=10)
    ap.add_argument("--chunk", type=int, default=7)
    ap.add_argument("--route", default="prior", choices=["prior", "soft"], help="prior=按阶段硬路由(推荐)")
    ap.add_argument("--aug", type=int, default=0)
    ap.add_argument("--aug-scale", default="0.90,1.10")
    ap.add_argument("--cache-gb", type=float, default=1.0)
    ap.add_argument("--init", default="", help="从已有统一主干续训专家融合层(可选)")
    ap.add_argument("--holdout", default=f"{SWM}/datasets/v6_holdout_rand.h5")
    ap.add_argument("--files", default=f"{SWM}/datasets/v6_sub25k.h5")
    ap.add_argument("--save", default=f"{SWM}/checkpoints/stage_moe")
    a = ap.parse_args()

    from transformers import AutoModel
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    files = [x for x in a.files.split(",") if x.strip()]

    print("=" * 78)
    print("🧠 阶段专家 MOE 训练 (7 阶段 × 专家头 + 先验门控)")
    print("=" * 78)
    print(f"   阶段: {' / '.join(STAGES)}")
    print(f"   数据: {files} · 留出: {os.path.basename(a.holdout)} · device {dev}")

    trunk = AutoModel.from_pretrained(MODEL, dtype=torch.float32).vision_model
    net = StageMoE(trunk, chunk=a.chunk, freeze=1).to(dev)
    if a.progress_file:
        os.makedirs(os.path.dirname(os.path.abspath(a.progress_file)), exist_ok=True)
    print(f"   🚦 路由模式: **{a.route}**" + (" (按阶段先验硬路由)" if a.route == "prior" else " (学习门控, 实测会坍缩)"))
    if a.init and os.path.isfile(a.init):
        sd0 = torch.load(a.init, map_location="cpu", weights_only=False)
        r = net.load_state_dict(sd0, strict=False)
        print(f"   🔁 续训自 {os.path.basename(a.init)} (missing={len(r.missing_keys)})")
    n_tr = sum(p.numel() for p in net.trunk.parameters())
    n_hd = sum(p.numel() for p in net.parameters() if p.requires_grad)
    print(f"   主干 {n_tr/1e6:.1f}M (冻结) · 专家+门控 {n_hd/1e6:.2f}M 可训")

    # 数据
    RealH5._AUG = int(a.aug)
    _sl, _sh = [float(x) for x in a.aug_scale.split(",")]
    RealH5._AUG_SCALE = (min(_sl, _sh), max(_sl, _sh))
    if a.progress_file:
        os.makedirs(os.path.dirname(os.path.abspath(a.progress_file)), exist_ok=True)
    print(f"   🎨 增强: {'开' if a.aug else '关'} | 缩放 {RealH5._AUG_SCALE}")
    RealH5.build_pixel_cache(files, cap_bytes=(int(a.cache_gb * 1024**3) or None))
    ds = RealH5Stage(files, a.chunk)
    dl = torch.utils.data.DataLoader(ds, batch_size=a.batch, shuffle=True, num_workers=a.workers,
                                     pin_memory=True, drop_last=True, persistent_workers=a.workers > 0)

    # 留出（整块读，快）
    import h5py
    fh = h5py.File(a.holdout, "r")
    Nh = int(fh["observation"].shape[0])
    hi = np.sort(np.random.default_rng(0).choice(Nh, size=min(2000, Nh), replace=False))
    H_O = np.asarray(fh["observation"][hi], dtype=np.float32)
    H_A = np.stack([np.stack([np.asarray(fh["action"][min(int(q) + k, Nh - 1)], dtype=np.float32)
                              for k in range(a.chunk)]) for q in hi])       # (N, chunk, 4)
    H_S = stage_from_ctx(np.asarray(fh["skill_ctx"][hi]))
    H_P = np.asarray(fh["pixels"][hi], dtype=np.uint8)
    fh.close()
    mu_o, mu_a = H_O.mean(0), H_A.mean(0)
    base_o = float(np.mean(np.abs(H_O - mu_o)))
    base_a = float(np.mean(np.abs(H_A - mu_a)))
    print(f"   平凡基线: 观测恒均 {base_o:.4f} · 动作恒均 {base_a:.4f}")

    opt = torch.optim.AdamW([p for p in net.parameters() if p.requires_grad], lr=a.lr, weight_decay=a.wd)
    best = [9e9, 0]
    t0 = time.time()
    it = iter(dl)
    for s in range(1, a.steps + 1):
        try:
            obs, act, px, obs_next, stage_p = next(it)
        except StopIteration:
            it = iter(dl)
            obs, act, px, obs_next, stage_p = next(it)
        obs, act = obs.to(dev), act.to(dev)
        obs_next = obs_next.to(dev)
        px = px.to(dev).float() / 255.0
        px = px.permute(0, 3, 1, 2) if px.shape[-1] == 3 else px
        # ★ 真阶段先验: 来自数据 skill_ctx[:,13:20]（RealH5Stage 提供）
        stage_p = stage_p.to(dev).float()
        mem = torch.zeros(obs.shape[0], 13, device=dev)

        out = net(px, obs, obs_next, mem, stage_p, hard=True, route=a.route)
        L4 = F.mse_loss(out["o_hat"], obs_next)
        L3 = F.mse_loss(out["u"], act)
        L = L4 + L3
        opt.zero_grad(set_to_none=True)
        L.backward()
        gn = nn.utils.clip_grad_norm_([p for p in net.parameters() if p.requires_grad], 1.0)
        opt.step()

        # ★★ 真·实时进度（与 --stats 解耦）
        if a.progress_file and (s % max(1, a.progress_every) == 0 or s == 1):
            try:
                json.dump({"step": s, "total": a.steps, "pct": round(100.0 * s / a.steps, 1),
                           "loss": round(float(L.item()), 6),
                           "sps": round(s / max(1e-6, time.time() - t0), 2),
                           "best_obs": (round(float(best[0]), 6) if best[0] < 9e8 else None),
                           "best_step": best[1], "ts": time.time(), "pid": os.getpid(),
                           "route": a.route, "save": a.save, "running": True},
                          open(a.progress_file, "w", encoding="utf-8"), ensure_ascii=False)
            except Exception as _pe:                                        # noqa: BLE001
                if not getattr(a, "_pf_warned", False):
                    print("  ⚠️ 进度文件写入失败(不影响训练): %s: %s" % (type(_pe).__name__, _pe), flush=True)
                    a._pf_warned = True

        if s % a.stats == 0 or s == 1:
            net.eval()
            with torch.no_grad():
                mo = ma = 0.0
                for b0 in range(0, len(H_O), 64):
                    b1 = min(len(H_O), b0 + 64)
                    hpx = torch.from_numpy(H_P[b0:b1]).to(dev).float().div(255).permute(0, 3, 1, 2)
                    ho = torch.from_numpy(H_O[b0:b1]).to(dev)
                    ha = torch.from_numpy(H_A[b0:b1]).to(dev)
                    hsp = torch.from_numpy(H_S[b0:b1]).to(dev)
                    o2 = net(hpx, ho, ho, torch.zeros(b1 - b0, 13, device=dev), hsp, hard=False, route=a.route)
                    mo += float(F.l1_loss(o2["o_hat"], ho, reduction="sum"))
                    ma += float(F.l1_loss(o2["u"], ha, reduction="sum"))
                mo /= len(H_O) * H_O.shape[1]
                ma /= len(H_O) * H_A[0].size
            net.train()
            if mo < best[0]:
                best = [mo, s]
                if a.save:
                    os.makedirs(a.save, exist_ok=True)
                    torch.save(net.state_dict(), os.path.join(a.save, "moe.pt"))
            print(f"  step {s:6d}/{a.steps} | loss {L.item():.4f} L4 {L4.item():.4f} L3 {L3.item():.4f} "
                  f"| ∇ {float(gn):.2e} | {s/(time.time()-t0):.1f}步/s | 留出 观测 {mo:.4f} 动作 {ma:.4f} "
                  f"(best {best[0]:.4f}@{best[1]}) | 基线 {base_o:.4f}/{base_a:.4f}", flush=True)
    print(f"✅ 完成 {a.steps} 步 / {time.time()-t0:.0f}s")
    if a.progress_file:
        try:
            _d = json.load(open(a.progress_file, encoding="utf-8"))
            _d.update({"running": False, "pct": 100.0, "finished_ts": time.time()})
            json.dump(_d, open(a.progress_file, "w", encoding="utf-8"), ensure_ascii=False)
        except Exception:                                                   # noqa: BLE001
            pass
    if a.save:
        print(f"产物 → {a.save}/moe.pt")


if __name__ == "__main__":
    main()
