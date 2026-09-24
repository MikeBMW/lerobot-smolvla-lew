#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔬 obs_step_delta.py — 引擎流 vs 采集集: 逐帧位移量对比 (解释"持久基线为何在引擎上极强")

背景 (2026-09-24): MOE 一步预测 MAE 在引擎流 0.0121 / 持久基线 0.00042 (差 29×);
同源留出集 0.0099 vs 0.0030 (差 3.3×)。差异是否来自**帧间位移尺度** (节拍/子采样)?
本脚本给硬数字: 两个域各自 |Δobs| 的 均值/p50/p95 + 每维分解 (位置维 vs 其余维)。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SWM = "/home/ubuntu/stable-wm-cache"
DIMNAME = (["hand_x", "hand_y", "hand_z", "grip"] * 9)[:39]     # 仅打印前几维辅助解读


def stats(d: np.ndarray) -> dict:
    return {"n": int(d.size), "mean": round(float(d.mean()), 6), "p50": round(float(np.percentile(d, 50)), 6),
            "p95": round(float(np.percentile(d, 95)), 6), "max": round(float(d.max()), 6)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine-json", default=os.path.join(ROOT, "reports", "moe_bypass_20260924.json"))
    ap.add_argument("--data", default=f"{SWM}/datasets/v6_holdout_rand.h5")
    ap.add_argument("--n", type=int, default=20000)
    a = ap.parse_args()

    out = {"ts_note": "engine vs h5 frame-to-frame |Δobs|"}
    # ① 引擎流: 从旁路日志逐帧 obs 重算 (真跑过引擎的那批帧)
    ej = json.load(open(a.engine_json, encoding="utf-8"))
    fr = next(iter(ej["runs"]["bypass"].values()))["moe_frames"] if "moe_frames" in \
        next(iter(ej["runs"]["bypass"].values())) else None
    if fr is None:
        # moe_frames 未落盘 (体积考虑) → **真跑一小段引擎**取 tr["obs"] 逐帧序列
        # (零回退已证: 挂不挂旁路 obs 序列逐位相同 → 这段就是引擎流的真实帧间位移)
        os.environ.setdefault("MUJOCO_GL", "egl")
        os.environ.setdefault("DISPLAY", ":0")
        for _p in (os.path.join(ROOT, "tools", "gui"), os.path.join(ROOT, "tools"), ROOT):
            if _p not in sys.path:
                sys.path.insert(0, _p)
        os.environ.setdefault("STABLEWM_HOME", SWM)
        os.environ.setdefault("LOCAL_DATASET_DIR", SWM)
        os.environ.setdefault("INTACT_RUNTIME", "root")
        import state_space_sim_real as SSR                                   # noqa: PLC0415
        _sim = SSR.RealStateSpaceSim(seed=104, vision=False, mode="insert", log=lambda *x: None)
        _tr = _sim.run(max_steps=60)
        O = np.asarray(_tr["obs"], float)[:, :39]        # 引擎 tr['obs'] 是 43D(fuse_sensors) → 取前 39 与 h5 observation 同口径
        d = np.abs(np.diff(O, axis=0)).mean(1)
        out["engine"] = stats(d)
        out["engine"]["src"] = "真跑引擎 seed104 60 步 tr['obs'][:39] (旁路日志未存逐帧 obs)"
        out["engine"]["per_dim_top5"] = {DIMNAME[i] if i < len(DIMNAME) else f"dim{i}":
                                         round(float(np.abs(np.diff(O[:, i])).mean()), 6)
                                         for i in np.argsort(-np.abs(np.diff(O, axis=0)).mean(0))[:5]}
    else:
        O = np.asarray([f["obs"] for f in fr if f.get("ok")], float)
        d = np.abs(np.diff(O, axis=0)).mean(1)
        out["engine"] = stats(d)
        out["engine"]["per_dim_top5"] = {DIMNAME[i]: round(float(np.abs(np.diff(O[:, i])).mean()), 6)
                                         for i in np.argsort(-np.abs(np.diff(O, axis=0)).mean(0))[:5]}

    # ② 采集集 (h5): 同一 episode 内相邻帧 (跨 episode 边界会污染 → 用中位数对比)
    import h5py
    f = h5py.File(a.data, "r")
    N = int(f["observation"].shape[0])
    idx = np.sort(np.random.default_rng(0).choice(max(N - 2, 1), size=min(a.n, N - 2), replace=False))
    O2 = np.asarray(f["observation"][idx], float)
    O2n = np.asarray(f["observation"][idx + 1], float)
    f.close()
    d2 = np.abs(O2n - O2).mean(1)
    out["h5"] = stats(d2)
    mp = np.abs(O2n - O2).mean(0)
    out["h5"]["per_dim_top5"] = {DIMNAME[i]: round(float(mp[i]), 6) for i in np.argsort(-mp)[:5]}
    out["ratio_h5_over_engine"] = (round(out["h5"]["p50"] / out["engine"]["p50"], 2)
                                   if "p50" in out.get("engine", {}) else None)

    print(json.dumps(out, ensure_ascii=False, indent=1))
    p = os.path.join(ROOT, "reports", "obs_step_delta_engine_vs_h5.json")
    json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"→ {p}")
    print("STEP_DELTA_DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
