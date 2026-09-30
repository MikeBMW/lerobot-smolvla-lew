# -*- coding: utf-8 -*-
"""📊 从官方 h5 数据集直接算动作归一化统计 (与 INTACT train.py get_column_stats 同口径)

为什么要有这个: 闭环侧要把模型输出的**归一化动作**还原成真动作 (a_raw = z·std + mean),
这两个常值必须与训练时用的**完全同源** —— 只能从训练数据集的 action 列现算, 不许手写/拍脑袋。

口径: 只统计 finite 行, ddof=1 (与 INTACT get_column_stats 一致)。

用法 (INTACT venv, 有 h5py):
  /home/ubuntu/INTACT-JEPA/.venv/bin/python tools/action_stats_from_h5.py \
      --h5 /home/ubuntu/stable-wm-cache/datasets/optical_insert_v4.h5 \
      --action-space u --out reports/optical_insert_v4_action_stats.json

action-space 记录进 json 的 "action_space" 字段, 供闭环侧选反变换约定:
  · env = env.step 收到的 4D 动作 (±1, 夹爪阈值化后)
  · u   = 引擎实际控制向量 sim._u_vec (xyz 速度 m/s + 夹爪 [-1..1]) ← v4 用
    ⚠️ u 口径闭环时必须做引擎自有的 u→act 约定 (state_space_sim_real.py:1183/1198):
       act[:3] = clip(u[:3]/K_ACT, ±1) · act[3] = CLOSE if u[3] > 0.5 else OPEN
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--h5", required=True)
    ap.add_argument("--action-space", default="u", choices=["u", "env"],
                    help="动作列语义标注 (只影响 json 里记录的 action_space 字段)")
    ap.add_argument("--key", default="action")
    ap.add_argument("--names", default="dx,dy,dz,gripper")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    import h5py                       # noqa: PLC0415  (必须在 INTACT venv 跑)
    try:
        import hdf5plugin             # noqa: F401,PLC0415
    except Exception:
        pass

    if not os.path.isfile(a.h5):
        print(f"❌ 数据集不存在: {a.h5}")
        return 2
    with h5py.File(a.h5, "r") as f:
        if a.key not in f:
            print(f"❌ h5 里没有 '{a.key}' 列 (有: {list(f.keys())})")
            return 2
        act = np.asarray(f[a.key][:], np.float64)
        n_tot = int(act.shape[0])
        ep = int(f["ep_len"].shape[0]) if "ep_len" in f else -1

    fin = np.isfinite(act).all(axis=1)
    A = act[fin]
    mean = A.mean(axis=0)
    std = A.std(axis=0, ddof=1)
    names = [x.strip() for x in a.names.split(",")][: A.shape[1]]
    out = a.out or os.path.join("reports", os.path.splitext(os.path.basename(a.h5))[0]
                                + "_action_stats.json")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    json.dump({
        "source": os.path.abspath(a.h5),
        "method": "get_column_stats 同口径 (finite 行, ddof=1)",
        "action_space": a.action_space,
        "action_space_note": ("env 级动作 (±1, env.step 实收)" if a.action_space == "env" else
                              "引擎控制向量 sim._u_vec (xyz 速度 m/s, 夹爪 [-1..1])"),
        "n_finite": int(A.shape[0]), "n_total": n_tot, "episodes": ep,
        "key_order": f"[{', '.join(names)}]",
        "mean": [float(x) for x in mean],
        "std": [float(x) for x in std],
        "per_axis": {nm: {"mean": float(mean[j]), "std": float(std[j]),
                          "min": float(A[:, j].min()), "max": float(A[:, j].max())}
                     for j, nm in enumerate(names)},
        "written": time.strftime("%F %T"),
    }, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"✅ {out}")
    print(f"   数据集 {os.path.basename(a.h5)} · finite 行 {A.shape[0]}/{n_tot} · 回合 {ep} "
          f"· action_space={a.action_space}")
    for j, nm in enumerate(names):
        print(f"   {nm:<8} mean={mean[j]:+.5f} std={std[j]:.5f} "
              f"range=[{A[:, j].min():+.4f},{A[:, j].max():+.4f}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
