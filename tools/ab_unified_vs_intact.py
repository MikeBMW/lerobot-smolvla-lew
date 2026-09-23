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

CKPT_U = os.environ.get("AB_CKPT", "/home/ubuntu/stable-wm-cache/checkpoints/unified_v13/unified.pt")
SEEDS = [104, 7, 2024]
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
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="只跑某个臂 (intact/unified)")
    ap.add_argument("--caps", default="", help="逗号分隔 (l3,l4)")
    ap.add_argument("--seeds", default="", help="逗号分隔")
    ap.add_argument("--max-n", type=int, default=0, help="最多跑几局 (0=不限)")
    _a = ap.parse_args()
    _kinds = [_a.only] if _a.only else ["intact", "unified"]
    _caps = ([(("none", "l3"), ("disturb", "l4"))[i] for i in range(2)] if not _a.caps
             else [((("none", "l3") if x.strip() == "l3" else ("disturb", "l4"))) for x in _a.caps.split(",")])
    _seeds = [int(x) for x in _a.seeds.split(",")] if _a.seeds else SEEDS
    _done = 0
    rows = []
    for kind in _kinds:
        for _dn, cap in _caps:
          for sd in _seeds:
            if _a.max_n and _done >= _a.max_n:
                break
            os.environ["SS_L4_INTACT"] = "1"
            os.environ["INTACT_RUNTIME"] = "root"
            os.environ["INTACT_POLICY"] = "intact_l4_current"
            try:
                r = run_arm(kind, sd, cap)
            except Exception as e:                                   # noqa: BLE001
                r = {"seed": sd, "err": f"{type(e).__name__}: {str(e)[:110]}"}
            r["arm"] = kind
            r["disturb"] = _dn
            _done += 1
            rows.append(r)
            print(f"  {kind:8s} {_dn:7s} seed={sd:4d} -> {r}", flush=True)
            # ★ 局间清理: 引擎每局重建 sim + 加载两个模型, 不释放 → 内存累积 OOM
            import gc as _gc
            _gc.collect()
            try:
                import torch as _t
                _t.cuda.empty_cache()
            except Exception:
                pass

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
