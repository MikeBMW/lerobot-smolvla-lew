#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""随机切分 v6 -> train/holdout (排除时序泄漏) + 平凡基线对比"""
import h5py
import numpy as np
import os

SRC = "/home/ubuntu/stable-wm-cache/datasets/optical_insert_v6_disturb.h5"
OUT = "/home/ubuntu/stable-wm-cache/datasets"

f = h5py.File(SRC, "r")
N = int(f["observation"].shape[0])
keys = [k for k in f if f[k].ndim >= 2 and f[k].shape[0] == N]
print("v6 N =", N, "| 按帧键:", keys, flush=True)

rng = np.random.default_rng(2026)
perm = rng.permutation(N)
n_ho = int(N * 0.1)
ho = np.sort(perm[:n_ho])
tr = np.sort(perm[n_ho:])
print(f"随机切分: train {len(tr)} / holdout {len(ho)}", flush=True)

for name, idx in (("v6_train_rand", tr), ("v6_holdout_rand", ho)):
    path = os.path.join(OUT, name + ".h5")
    g = h5py.File(path, "w")
    n = len(idx)
    for k in keys:
        d = f[k]
        shp = (n,) + d.shape[1:]
        kw = {}
        if d.chunks is not None or d.nbytes > 1e7:
            kw = dict(compression="lzf")   # ★ 保持与原文件同量级 (v6 是压缩存的, 不压会膨胀 3×)
        g.create_dataset(k, shape=shp, dtype=d.dtype,
                         chunks=(min(512, n),) + d.shape[1:], **kw)
        for s in range(0, n, 4096):
            e = min(n, s + 4096)
            g[k][s:e] = d[idx[s:e]]
    g.close()
    print(f"  OK {name}: {n} 帧 {os.path.getsize(path)/1048576:.0f}MB", flush=True)

# 平凡基线 (在随机留出集上)
print("\n=== 平凡基线 (随机留出集) ===", flush=True)
act_ho = f["action"][ho]
obs_ho = f["observation"][ho]
print(f"动作恒定输出0 的 MAE      : {np.abs(act_ho).mean():.4f}")
print(f"观测恒定输出训练均值的 MAE : {np.abs(obs_ho - f['observation'][tr].mean(0)).mean():.4f}")
print(f"动作恒定输出训练均值的 MAE : {np.abs(act_ho - f['action'][tr].mean(0)).mean():.4f}")
f.close()
