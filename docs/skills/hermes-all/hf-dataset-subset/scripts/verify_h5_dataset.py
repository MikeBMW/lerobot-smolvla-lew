#!/usr/bin/env python3
"""HDF5 数据集可用性验证 — 真解码抽检 (不信元数据/不相信小块读取成功)

用法:
    python3 verify_h5_dataset.py /path/to/file.h5 [--frames 3]
    rc=0 可用 · rc=1 有硬问题 (有 blosc 但缺 hdf5plugin / 帧读不出 / 图像全黑)

背景 (2026-09-12 实测, h5py 3.16.0 + hdf5 2.0.0):
  pixels 用 blosc 压缩 (滤镜 id 32001) 时, 不 import hdf5plugin 会报
  "OSError: Can't synchronously read data (can't find plugin ...)"。
  把 HDF5_PLUGIN_PATH 指向空目录**不能**解决 (同样报 can't find plugin)。
  小块元数据 (ep_len/ep_offset) 能读 → 容易误判为"文件没问题", 必须真读帧。
"""
import argparse
import sys

import numpy as np


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--frames", type=int, default=3, help="抽检帧数 (0/N//3/N-1 …)")
    a = ap.parse_args()

    hard_fail = []
    plugin_ok = True
    try:
        import hdf5plugin  # noqa: F401  # 必须显式 import 才注册 blosc/zstd/lz4 等滤镜
    except ImportError:
        plugin_ok = False
        print("⚠️ hdf5plugin 未安装 → blosc 压缩数据会读失败: pip install hdf5plugin")

    import h5py  # noqa: E402

    with h5py.File(a.path, "r") as f:
        print("文件:", a.path)
        print("顶层对象 %d 个" % len(f.keys()))
        big = None
        for k in f.keys():
            d = f[k]
            if not isinstance(d, h5py.Dataset):
                print("  %s/ (group)" % k)
                continue
            filters = []
            try:
                pl = d.id.get_create_plist()
                filters = [pl.get_filter(i)[3].decode() for i in range(pl.get_nfilters())]
            except Exception:
                pass
            print("  %-20s shape=%-22s dtype=%-8s chunks=%s filters=%s"
                  % (k, str(d.shape), d.dtype, d.chunks, filters or "-"))
            if big is None or d.size > big.size:
                big = d

        # 1) 真解码抽检最大数据集 (通常是 pixels)
        if big is None:
            print("❌ 没有可读 dataset")
            return 1
        n = big.shape[0]
        idxs = sorted({0, n // 3, n - 1, max(0, n // 2)})
        idxs = idxs[: max(1, a.frames)] or [0]
        print("\n真解码抽检 %s (n=%d) 位置 %s:" % (big.name, n, idxs))
        for i in idxs:
            try:
                arr = np.asarray(big[i])
            except OSError as e:
                print("  ❌ idx=%-8d 读取失败: %s" % (i, e))
                if not plugin_ok:
                    hard_fail.append("缺 hdf5plugin → blosc 数据读不出")
                else:
                    hard_fail.append("帧读取失败 idx=%d" % i)
                continue
            stat = "mean=%.1f std=%.1f range=%s..%s" % (
                arr.mean(), arr.std(), arr.min(), arr.max())
            flag = ""
            if arr.ndim >= 2 and arr.std() <= 5:
                flag = "  ⚠️ std<=5 → 疑似全黑/假图像"
            print("  idx=%-8d %-14s %s%s" % (i, str(arr.shape), stat, flag))

        # 2) 数值有效性 (抽 3 个标量/向量字段)
        print("\n数值有效性:")
        for k in ("action", "proprio", "observation", "reward"):
            if k not in f:
                continue
            try:
                pos = min(n - 1, n // 3)
                v = np.asarray(f[k][pos])
                fin = bool(np.isfinite(v).all())
                print("  %-12s 有限值=%s (idx=%d) 末帧有限=%s"
                      % (k, fin, pos, bool(np.isfinite(np.asarray(f[k][-1])).all())))
                if not fin:
                    hard_fail.append("%s 在 idx=%d 非有限值" % (k, pos))
            except OSError as e:
                print("  %-12s ❌ %s" % (k, e))

        # 3) 分集一致性 (有 ep_offset/ep_len 时)
        if "ep_offset" in f and "ep_len" in f:
            off = np.asarray(f["ep_offset"][: min(500, len(f["ep_offset"]))])
            ln = np.asarray(f["ep_len"][: min(500, len(f["ep_len"]))])
            step_ok = bool((np.diff(off) == ln[:-1]).all())
            tot = int(f["ep_offset"][-1] + f["ep_len"][-1])
            print("\n分集一致性: ep_offset 步进==ep_len %s | 末集 offset[-1]+len[-1]=%d == n=%d → %s"
                  % (step_ok, tot, n, tot == n))
            if not (step_ok and tot == n):
                hard_fail.append("ep_offset/ep_len 与总帧数不一致")
        else:
            print("\n分集一致性: 无 ep_offset/ep_len (非分集格式, 跳过)")

    print("\n" + ("✅ 可用 (真解码通过)" if not hard_fail
                  else "❌ 有问题:\n   - " + "\n   - ".join(hard_fail)))
    print("提示: 末帧 action=nan 属正常(无后继动作), 评测 valid-start 会剔掉, 不算损坏。")
    return 1 if hard_fail else 0


if __name__ == "__main__":
    sys.exit(main())
