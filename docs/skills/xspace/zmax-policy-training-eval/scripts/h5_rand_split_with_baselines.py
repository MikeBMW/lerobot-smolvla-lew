#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""h5 随机切分（train/holdout）+ 打印**平凡基线** = 判断"真学到"的标尺

为什么必须做（真实教训，2026-09-23）:
  只看"训练 loss 降到 0.0003"会得出完全错误的结论 —— 实测那时模型输出跑到 ±2.7
  （动作合法域是 [-1,1]），留出 L1 = 2.703，比"恒输出 0"还差。
  补上平凡基线后立刻看清: 0.019 是真学到, 2.703 是假的。
  ⇒ **没有基线的留出 MAE 是无效数字**。

两个设计决策（都踩过）:
  ① **随机切分, 不用"最后 10%"** —— 顺序切有采集顺序泄漏风险
  ② 测"造数据有没有用"要用**造数据的域**当留出(同域留出测不出增量);
     同一份数据要既训练又留出时, 按**变体/集**切, 别按帧切（相邻帧高度相关）

用法:
  gui-venv311/bin/python h5_rand_split_with_baselines.py --src <train.h5> \
      --outdir /home/ubuntu/stable-wm-cache/datasets --frac 0.1

输出: <name>_train_rand.h5 / <name>_holdout_rand.h5 + 三个平凡基线值
注意: 写盘用 lzf 压缩 —— 不加压缩会把 4.1GB 的文件写成 11.3GB（v6 实测 2.7× 膨胀）
      chunk 用 min(256, n)：分块过大（如 512）会让随机读 1 帧要解压整块 75MB，训练饿 GPU
"""
import argparse
import os

import h5py
import numpy as np


def copy_range(f, g, keys, lo, hi):
    n = hi - lo
    for k in keys:
        d = f[k]
        shp = (n,) + d.shape[1:]
        kw = {}
        if d.nbytes > 1e7:                       # 大数组(像素)才压缩
            kw = dict(compression="lzf")         # ★ 不压缩 → 2.7× 膨胀
        g.create_dataset(k, shape=shp, dtype=d.dtype,
                         chunks=(min(256, n),) + d.shape[1:], **kw)   # ★ chunk 别太大
        for s in range(lo, hi, 4096):
            e = min(hi, s + 4096)
            g[k][s - lo:e - lo] = d[s:e]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--outdir", default="/home/ubuntu/stable-wm-cache/datasets")
    ap.add_argument("--frac", type=float, default=0.1, help="留出比例")
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()

    base = os.path.basename(a.src).replace(".h5", "")
    f = h5py.File(a.src, "r")
    N = int(f["observation"].shape[0])
    # 只切按帧的键 (ep_idx/ep_len 等按 episode 的 1 维数组不参与, 否则 shape 不匹配)
    keys = [k for k in f if f[k].ndim >= 2 and f[k].shape[0] == N]
    n_out = max(1, int(N * a.frac))
    hold = np.sort(np.random.default_rng(a.seed).choice(N, size=n_out, replace=False))
    is_hold = np.zeros(N, dtype=bool)
    is_hold[hold] = True
    print(f"{base}: N={N} · 按帧键={keys} · 留出 {n_out} 帧")

    for name, mask in ((f"{base}_holdout_rand", is_hold), (f"{base}_train_rand", ~is_hold)):
        idx = np.flatnonzero(mask)
        g = h5py.File(os.path.join(a.outdir, f"{name}.h5"), "w")
        # 逐段连续拷贝 (保持 h5 顺序读效率)
        p = 0
        while p < len(idx):
            q = p
            while q + 1 < len(idx) and idx[q + 1] == idx[q] + 1:
                q += 1
            copy_range(f, g, keys, int(idx[p]), int(idx[q]) + 1)
            p = q + 1
        g.close()
        print(f"  ✅ {name}: {len(idx)} 帧 "
              f"{os.path.getsize(os.path.join(a.outdir, name + '.h5'))/1048576:.0f}MB")

    # ★ 平凡基线 = 标尺
    o = np.asarray(f["observation"][: min(N, 20000)], dtype=np.float64)
    act = np.asarray(f["action"][: min(N, 20000)], dtype=np.float64)
    f.close()
    aflat, oflat = act.reshape(len(act), -1), o.reshape(len(o), -1)
    print("\n=== 平凡基线（留出 MAE 必须低于对应基线才算真学到）===")
    print(f"动作恒定输出0           : {np.abs(aflat).mean():.4f}")
    print(f"动作恒定输出训练均值     : {np.abs(aflat - aflat.mean(0)).mean():.4f}")
    print(f"观测恒定输出训练均值     : {np.abs(oflat - oflat.mean(0)).mean():.4f}   ← 认知预测的及格线")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
