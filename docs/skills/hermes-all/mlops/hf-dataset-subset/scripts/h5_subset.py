#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从超大 h5 数据集切"前 N 回合"子集 (流式写, 峰值内存有界)

用途 (2026-09-12 实测): 官方数据集解压后是 98.9GB 的单个 h5 (dmc/reacher_random.h5),
磁盘红线吃不下 → 只留前 N 回合 (够跑评测/实况), 其余丢弃, 完整文件与归档随后删除。

h5 结构 (stable_worldmodel / OGBench 风格, 顶层平铺):
  action[ R] / observation[R,D] / pixels[R,H,W,3] / reward[R] ...   ← R = 总行数
  ep_idx[R] · step_idx[R] · ep_len[E] · ep_offset[E]                 ← E = 回合数
子集做法: 取前 N 回合 → 行号 ep_offset[i] .. +ep_len[i] → 各数据集按行切片写出, ep_len/ep_offset 重算。
读回校验: 回合数 + 抽样 std (>1 才算真图), 不通过就非零退出 (调用方不要落位)。

依赖: h5py (+ hdf5plugin 若源文件用 blosc: `import hdf5plugin` 且设 HDF5_PLUGIN_PATH)

用法:
  python h5_subset.py --src BIG.h5 --out SMALL.h5 --episodes 100 [--chunk 512]
"""
from __future__ import annotations

import argparse
import os
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--episodes", type=int, default=100)
    ap.add_argument("--chunk", type=int, default=512, help="每次写多少行 (控内存)")
    a = ap.parse_args()

    import h5py
    import numpy as np
    try:
        import hdf5plugin                                    # noqa: F401  (blosc 压缩必需)
    except Exception:
        pass

    with h5py.File(a.src, "r") as f:
        if "ep_offset" not in f or "ep_len" not in f:
            print(f"❌ 源文件缺少 ep_offset/ep_len, 无法切片: {list(f.keys())[:10]}")
            return 2
        off = np.asarray(f["ep_offset"][:], dtype=np.int64)
        ln = np.asarray(f["ep_len"][:], dtype=np.int64)
        n_ep = min(int(a.episodes), len(off))
        total_rows = int(off[-1] + ln[-1])
        keep_rows = int(ln[:n_ep].sum())
        print(f"源: {len(off)} 回合 / {total_rows:,} 行  →  子集: {n_ep} 回合 / {keep_rows:,} 行")

        out = h5py.File(a.out, "w")
        row_sets = [k for k in f.keys() if getattr(f[k], "shape", None)
                    and len(f[k].shape) >= 1 and f[k].shape[0] == total_rows]
        for k in row_sets:
            if k in ("ep_len", "ep_offset"):
                continue
            src = f[k]
            kw = {}
            if src.compression:
                kw = {"compression": src.compression, "compression_opts": src.compression_opts}
            d = out.create_dataset(k, shape=(keep_rows, ) + src.shape[1:], dtype=src.dtype, **kw)
            pos = 0
            for i in range(n_ep):                              # 逐回合逐块写 → 内存有界
                s, e = int(off[i]), int(off[i]) + int(ln[i])
                for c in range(s, e, a.chunk):
                    cc = min(c + a.chunk, e)
                    d[pos:pos + (cc - c)] = src[c:cc]
                    pos += (cc - c)
            print(f"   ✓ {k} → {(keep_rows, ) + src.shape[1:]}")
        new_len = np.asarray(ln[:n_ep], dtype=np.int32)
        new_off = np.concatenate([[0], np.cumsum(new_len)[:-1]]).astype(np.int64)
        if "ep_len" in f:
            out.create_dataset("ep_len", data=new_len)
        if "ep_offset" in f:
            out.create_dataset("ep_offset", data=new_off)
        out.attrs["subset_of"] = os.path.basename(a.src)
        out.attrs["subset_episodes"] = n_ep
        out.close()

    with h5py.File(a.out, "r") as g:                           # 读回校验, 不通过不落位
        n = len(g["ep_len"])
        std = None
        for k in ("pixels", "observation"):
            if k in g and g[k].shape[0] > 10:
                arr = np.asarray(g[k][:20]) if k != "pixels" else np.asarray(g[k][:5, ::8, ::8, :])
                std = float(arr.std())
                break
    ok = (n == n_ep) and (std is None or std > 1.0)
    print(f"校验: 回合 {n}/{n_ep} · 抽样 std={std} → {'✅ OK' if ok else '❌ 异常'}")
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
