#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ana_l4_dy.py — L4 卡点定量归因 (紧凑版, 不打印 attrs)

回答三问 (全部只读数据):
  Q1 各轴动作的幅度/活跃度 → dy 是不是"瘦"轴?
  Q2 动作到底跟哪个观测对得上? (穷举 corr(action_i, o_j) 与 corr(action_i, o_j - o_k))
      → 既验证 obs 布局, 又判定"动作是不是伺服量"
  Q3 预测难度: 每轴的方差解释度上限 (用最优单维观测做线性回归的 R²)
"""
from __future__ import annotations

import os
import sys

import h5py
import numpy as np

CACHE = "/home/ubuntu/stable-wm-cache/datasets"
AX = ["dx", "dy", "dz", "grip"]
TOPK = 3


def main() -> int:
    files = sys.argv[1:] or [os.path.join(CACHE, "optical_insert_v6_disturb.h5"),
                             os.path.join(CACHE, "optical_insert_v5_disturb.h5")]
    for p in files:
        if not os.path.exists(p):
            print("跳过(不存在) %s" % p)
            continue
        with h5py.File(p, "r") as f:
            a = np.asarray(f["action"], np.float32)
            o = np.asarray(f["observation"], np.float32) if "observation" in f else None
        print("═" * 76)
        print("%s · action%s%s" % (os.path.basename(p), a.shape,
                                   "" if o is None else " obs%s" % (o.shape,)))
        print("\nQ1 各轴动作活跃度")
        print("  %-6s%9s%9s%9s%11s%11s" % ("轴", "mean", "std", "p1", "p99", "|a|>0.05"))
        for i, ax in enumerate(AX):
            c = a[:, i]
            print("  %-6s%9.4f%9.4f%9.4f%9.4f%10.1f%%" % (ax, c.mean(), c.std(),
                                                          np.percentile(c, 1), np.percentile(c, 99),
                                                          100.0 * np.mean(np.abs(c) > 0.05)))
        if o is None:
            continue
        # 观测 39 维先做去常量筛选
        keep = [j for j in range(o.shape[1]) if o[:, j].std() > 1e-6]
        print("\nQ2 动作 ↔ 观测 最佳对应 (穷举 |corr|, 只报 top%d)" % TOPK)
        for i, ax in enumerate(AX[:3]):
            ai = a[:, i]
            if ai.std() < 1e-9:
                continue
            single = sorted(((abs(np.corrcoef(ai, o[:, j])[0, 1]), j) for j in keep), reverse=True)
            print("  %-5s 单维: %s" % (ax, " · ".join("o[%d] %.3f" % (j, c) for c, j in single[:TOPK])))
            pairs = []
            for j in keep:
                for k in keep:
                    if j >= k:
                        continue
                    d = o[:, j] - o[:, k]
                    if d.std() < 1e-6:
                        continue
                    pairs.append((abs(np.corrcoef(ai, d)[0, 1]), j, k))
            pairs.sort(reverse=True)
            print("          差分: %s" % " · ".join("o[%d]-o[%d] %.3f" % (j, k, c) for c, j, k in pairs[:TOPK]))
        print("\nQ3 该轴能被单维观测解释的上限 (最优 R²)")
        for i, ax in enumerate(AX[:3]):
            ai = a[:, i]
            best = max((float(np.corrcoef(ai, o[:, j])[0, 1]) ** 2 for j in keep), default=float("nan"))
            aut = float(np.corrcoef(ai[:-1], ai[1:])[0, 1])
            print("  %-5s 最优单维 R²=%6.3f · 一阶自相关=%.3f   (%s)"
                  % (ax, best, aut, "观测里几乎没有该轴的信息" if best < 0.05 else "有信息可学"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
