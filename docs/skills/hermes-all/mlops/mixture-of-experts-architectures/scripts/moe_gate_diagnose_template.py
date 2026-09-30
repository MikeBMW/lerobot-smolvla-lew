#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MoE 门控分化诊断 —— 模板（复制后只改 3 处：模型加载 / 数据 / 路由调用）

判据（打印在最后）:
  ① 阶段→专家混淆矩阵   主导占比越高越专一
  ② 路由熵              明显低于 log(k) 才算专一
  ③ 有效专家数          = k（否则有专家饿死）
  ④ 阶段-专家一一对应率 ≥ (k-1)/k（实测 6/7 为健康；要求 k/k 说明先验过强）

用法: python moe_gate_diagnose_template.py
改编点标了「# ← ADAPT」
"""
import numpy as np
import torch
import torch.nn.functional as F

N_EXPERTS = 7                      # ← ADAPT: 专家数
STAGES = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入"]   # ← ADAPT: 阶段名(仅用于打印)


# ─────────── ADAPT 1: 加载模型 ───────────
def load_model(dev):
    """返回已 eval() 的模型（需有 forward(..., stage_prior, hard=False) → dict 含 'gate'）"""
    raise NotImplementedError("把这里换成你的模型加载/权重装载")
    # 例:
    # from transformers import AutoModel
    # trunk = AutoModel.from_pretrained(MODEL, dtype=torch.float32).vision_model
    # net = YourMoE(trunk, freeze=1)
    # r = net.load_state_dict(torch.load(CKPT, map_location="cpu", weights_only=False), strict=False)
    # print("missing=", len(r.missing_keys))
    # return net.eval().to(dev)


# ─────────── ADAPT 2: 数据 + 阶段先验 ───────────
def load_data(data_path, n=3000):
    """返回 (obs, pixels_uint8, stage_prior(N,k), stage_label(N,))

    阶段先验的取法：数据里应有离散分段信号（stage/phase/skill_ctx 之类）。
    本仓库实测: skill_ctx[:,13:20] = 7 阶段概率（行和≈1）。
    """
    import h5py
    f = h5py.File(data_path, "r")
    keys = list(f)
    N = int(f["observation"].shape[0])
    idx = np.sort(np.random.default_rng(1).choice(N, size=min(n, N), replace=False))
    obs = np.asarray(f["observation"][idx], dtype=np.float32)
    px = np.asarray(f["pixels"][idx], dtype=np.uint8)
    # ← ADAPT: 换成你自己的先验提取
    sk = np.asarray(f["skill_ctx"][idx], dtype=np.float32)[:, 13:20]
    sk = np.clip(sk, 0, None)
    rs = sk.sum(-1, keepdims=True); rs[rs < 1e-6] = 1.0
    prior = sk / rs
    f.close()
    return obs, px, prior, prior.argmax(1)


# ─────────── ADAPT 3: 一次前向取门控 ───────────
def gate_of(net, dev, px_u8, obs, prior):
    """返回 (routes(N,), entropy(N,))"""
    routes, ents = [], []
    with torch.no_grad():
        for b0 in range(0, len(obs), 64):
            b1 = min(len(obs), b0 + 64)
            x = torch.from_numpy(px_u8[b0:b1]).to(dev).float().div(255).permute(0, 3, 1, 2)
            o = torch.from_numpy(obs[b0:b1]).to(dev)
            sp = torch.from_numpy(prior[b0:b1]).to(dev)
            # ← ADAPT: 你的模型签名; 关键: hard=False（软门控才能看分布）
            out = net(x, o, o, torch.zeros(b1 - b0, 13, device=dev), sp, hard=False)
            g = out["gate"]
            routes.append(g.argmax(1).cpu().numpy())
            ents.append((-(g * (g + 1e-9).log()).sum(1)).cpu().numpy())
    return np.concatenate(routes), np.concatenate(ents)


def main():
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    net = load_model(dev)
    obs, px, prior, y = load_data("/path/to/holdout.h5")        # ← ADAPT: 数据路径
    routes, ent = gate_of(net, dev, px, obs, prior)

    print("=" * 78)
    print("🔍 MoE 门控分化诊断 (%d 样本)" % len(obs))
    print("=" * 78)
    print("  ① 阶段 → 专家 混淆矩阵 (行=真阶段, 列=专家)")
    print("     阶段     " + "".join("E%-5d" % i for i in range(N_EXPERTS)) + "  主导  占比")
    hits = 0
    for s in range(N_EXPERTS):
        m = (y == s)
        if m.sum() == 0:
            print("     %-8s (无样本)" % STAGES[s]); continue
        row = np.bincount(routes[m], minlength=N_EXPERTS)
        top = int(row.argmax()); share = row[top] / max(1, m.sum())
        hits += int(share > 0.5)
        print("     %-8s " % STAGES[s] + "".join("%-6d" % v for v in row) +
              "  E%-3d %5.1f%%" % (top, share * 100))

    used = len(set(routes.tolist()))
    print("\n  ② 路由熵: 平均 %.3f (上界 %.3f → 越低越专一)" % (ent.mean(), np.log(N_EXPERTS)))
    print("  ③ 有效专家数: %d / %d %s" % (used, N_EXPERTS,
          "✅ 全用上" if used == N_EXPERTS else "⚠️ 有专家饿死"))
    print("  ④ 阶段-专家一一对应率: %d/%d %s" % (hits, N_EXPERTS,
          "✅ 分化成立" if hits >= N_EXPERTS - 1 else "❌ 未分化(退化成单头)"))
    print("=" * 78)
    print("判据: 对应率 ≥(k-1)/k 且 有效专家=k → MoE 分工成立")
    print("注意: 「部分分化」是健康的; 若强行 k/k 全对应, 通常是先验强度过大(僵化)")


if __name__ == "__main__":
    main()
