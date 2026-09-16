#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧩 ab_l4_l2_compat.py — L4 档「L2 兼容」同口径 A/B (每臂独立进程, 同 seed 同步数)

臂 A (现状): vision=False + 不设 SS_USE_MLP  → 日志 "YOLO 未启动" · MLP 真身 0 次
臂 B (接线): vision=True  + SS_USE_MLP=1    → YOLO 每帧真跑 · MLP 真身真进

判据 (全实测, 不看日志口气): YOLO 出帧数 / n_mlp 真身进入次数 / 终点距离 / done / 墙钟
用法: python tools/ab_l4_l2_compat.py A 120   (臂 B 用 env: SS_USE_MLP=1 且 argv1=B)
"""
from __future__ import annotations

import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "tools"), os.path.join(ROOT, "src")]

import numpy as np  # noqa: E402

ARM = sys.argv[1] if len(sys.argv) > 1 else "A"
STEPS = int(sys.argv[2]) if len(sys.argv) > 2 else 120


def main() -> int:
    sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
    from state_space_sim_real import RealStateSpaceSim  # noqa: PLC0415

    logs: list[str] = []
    vision = (ARM == "B")
    t0 = time.time()
    sim = RealStateSpaceSim(seed=104, vision=vision, vision_every=1, mode="full",
                            log=lambda *a: logs.append(" ".join(str(x) for x in a)))
    acc = sim.accel
    ff_before = getattr(acc, "_ff", None)
    override_before = "forward" in getattr(acc, "__dict__", {})
    tr = sim.run(max_steps=STEPS, cap="l4")
    el = time.time() - t0
    n_mlp, n_guard = int(getattr(acc, "n_mlp", -1)), int(getattr(acc, "n_guard", -1))
    vis = getattr(sim, "_vis", {}) or {}
    shots = int(vis.get("shot", 0) or 0)
    n_det = int(vis.get("n", 0) or 0)
    dmin = float(np.min(tr["dist"])) if tr.get("dist") else float("nan")
    dlast = float(tr["dist"][-1]) if tr.get("dist") else float("nan")
    yolo_lines = [l for l in logs if "YOLO" in l]
    out = {"arm": ARM, "steps": STEPS, "vision": vision,
           "SS_USE_MLP": os.environ.get("SS_USE_MLP"),
           "mlp_loaded": bool(getattr(acc, "loaded", False)), "ff_is_none": ff_before is None,
           "forward_overridden_at_start": override_before,
           "n_mlp": n_mlp, "n_guard": n_guard,
           "yolo_shots": shots, "yolo_dets": n_det,
           "yolo_log_sample": yolo_lines[-1] if yolo_lines else "(无 YOLO 日志行)",
           "dist_min_mm": round(dmin * 1000, 2), "dist_last_mm": round(dlast * 1000, 2),
           "done": bool(tr.get("done", [False])[-1]) if tr.get("done") else None,
           "elapsed_s": round(el, 1)}
    p = os.path.join(ROOT, "reports", f"ab_l4_l2compat_{ARM}.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print(json.dumps(out, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
