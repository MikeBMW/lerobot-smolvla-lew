#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一主干 vs 在役 L4: 引擎闭环同口径 A/B (同 seed · 完整 episode)

臂 A: IntactNode(在役 intact_l4_current)   — 现有路径
臂 B: UnifiedNode(统一主干 backbone_cont)  — 新路径
判据: done / 插入深度 / 阶段 / 接管步数 (而非"能否完成"单一指标)
"""
import os
import sys

R = "/home/ubuntu/lerobot-smolvla-lew"
sys.path.insert(0, R + "/src")
sys.path.insert(0, R + "/tools/gui")
sys.path.insert(0, R + "/tools")

import numpy as np  # noqa: E402

CKPT_U = "/home/ubuntu/stable-wm-cache/checkpoints/backbone_cont/unified.pt"
SEEDS = [104, 7, 42, 2024, 13, 99]
MAX = 1200


CAPS = [("none", "l3"), ("disturb", "l4")]


def run_arm(kind, seed, cap="l3"):
    from state_space_sim_real import RealStateSpaceSim

    sim = RealStateSpaceSim(seed=seed, vision=True, log=lambda *a: None)
    if kind == "intact":
        from lerobot.manifold.intact_node import IntactNode

        node = IntactNode(horizon=8)
    else:
        from unified_node import UnifiedNode

        node = UnifiedNode(CKPT_U, sim=sim, horizon=8)
    sim.attach_intact(node, None)
    tr = sim.run(max_steps=MAX, cap=cap)
    s = getattr(sim, "_l4_stats", {}) or {}
    depth = abs(float(sim.x[0]) - (-0.2429)) * 1000.0 if hasattr(sim, "x") else float("nan")
    return {
        "seed": seed,
        "cap": cap,
        "steps": len(tr["t"]),
        "done": bool(tr["done"][-1]),
        "stage": sim.sched.stage(),
        "calls": s.get("calls", 0),
        "reuse": s.get("reuse", 0),
        "refused": s.get("refused", 0),
        "src": s.get("src", "-"),
        "w": s.get("w", -1),
        "depth_mm": depth,
    }


def main():
    rows = []
    for kind in ("intact", "unified"):
        for _dn, cap in CAPS:
          for sd in SEEDS:
            os.environ["SS_L4_INTACT"] = "1"
            os.environ["INTACT_RUNTIME"] = "root"
            os.environ["INTACT_POLICY"] = "intact_l4_current"
            try:
                r = run_arm(kind, sd, cap)
            except Exception as e:                                   # noqa: BLE001
                r = {"seed": sd, "err": f"{type(e).__name__}: {str(e)[:110]}"}
            r["arm"] = kind
            r["disturb"] = _dn
            rows.append(r)
            print(f"  {kind:8s} {_dn:7s} seed={sd:4d} -> {r}", flush=True)

    print("\n" + "=" * 92)
    print("  臂       干扰     seed  步数  done  calls refused    w    深度mm")
    for r in rows:
        if "err" in r:
            print(f"  {r['arm']:8s} {r['seed']:5d}  ❌ {r['err']}")
        else:
            print(f"  {r['arm']:8s} {r['seed']:5d} {r['steps']:5d}  {str(r['done'])[:5]:5s} "
                  f"{r['stage']:6s} {r['calls']:5d} {r['reuse']:5d} {r['refused']:7d}  "
                  f"{r['src'][:24]:24s} {r['w']:.2f}  {r['depth_mm']:8.1f}")
    print("=" * 92)


if __name__ == "__main__":
    main()
