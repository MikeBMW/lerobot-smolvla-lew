# -*- coding: utf-8 -*-
"""🌀 ab_spiral.py — 螺旋搜索参数 A/B (解析链, 只改 L2 搜索参数; 2026-09-15)

依据 (diag_insert_depth + diag_retreat_reason):
  seed1 对孔偏差 3.4~5.4mm → 螺旋只覆盖 4.5mm/70帧 ×3 次 → 仍顶壁 → 判"已滑(>5mm)" → 回退死循环
  seed2 抓取滑移 16~19mm → 反复重抓 (非螺旋问题)
本 A/B 只动螺旋 (L2 自己的搜索能力): 现状 vs 宽域 (覆盖到 9mm/更长窗口/更多次)
用法: MUJOCO_GL=egl gui-venv311/bin/python tools/ab_spiral.py --seeds 0,1,2 --steps 900 --arm wide
      (每臂一个进程; AB_JSONL 追加结果)
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
import time

import numpy as np

os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("DISPLAY", ":0")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUI = os.path.join(ROOT, "tools", "gui")
for _p in (ROOT, os.path.join(ROOT, "src"), os.path.join(ROOT, "tools"), GUI):
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.chdir(GUI)
# 🧊 评估纪律 (2026-09-15 实证): 引擎肌肉记忆默认开且跨 run 持久化 (data/muscle_memory.json);
#   热记忆让同一 seed 结果随历史漂移 (seed0 从稳定成功→6/6 确定性失败; 冷/热 = 3/8 vs 4/8),
#   且热记忆下 30~65% 执行帧是记忆回放而非实时计算。A/B 默认隔离成空记忆 (冷口径),
#   AB_HOT_MEM=1 才用共享记忆。
if os.environ.get("AB_HOT_MEM") != "1":
    os.environ.setdefault("SS_MUSCLE_PATH", "/tmp/ab_mem_%d.json" % os.getpid())
for k, v in (("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache"),
             ("LOCAL_DATASET_DIR", "/home/ubuntu/stable-wm-cache"),
             ("INTACT_RUNTIME", "root"), ("INTACT_POLICY", "intact_l4_current"),
             ("OMP_NUM_THREADS", "6")):
    os.environ.setdefault(k, v)
os.environ.pop("SS_L4_INTACT", None)
os.environ.pop("SS_L4_INTENT_LINE", None)
ARMS = {"base": {},                                        # 现状 (默认值)
        "wide": {"SS_SPIRAL_RMAX": "0.009", "SS_SPIRAL_DR": "0.00008",
                 "SS_SPIRAL_FRAMES": "110", "SS_SPIRAL_OMEGA": "0.35", "SS_SPIRAL_TRIES": "5"},
        "slow": {"SS_SPIRAL_FRAMES": "150", "SS_SPIRAL_OMEGA": "0.22",
                 "SS_SPIRAL_DR": "0.00005", "SS_SPIRAL_TRIES": "4"}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="0,1,2")
    ap.add_argument("--steps", type=int, default=900)
    ap.add_argument("--arm", default="base")
    a = ap.parse_args()
    for k, v in ARMS[a.arm].items():
        os.environ[k] = v
    jl = os.environ.get("AB_JSONL")
    for sd in [int(x) for x in a.seeds.split(",") if x.strip()]:
        from state_space_sim_real import RealStateSpaceSim
        logs: list = []
        sim = RealStateSpaceSim(seed=sd, vision=False, mode="insert",
                                log=lambda *x: logs.append(" ".join(map(str, x))))
        _orig = sim._insert_depth
        dl: list = []

        def wrapped(_o=_orig, _l=dl):
            v = _o()
            _l.append(None if v is None else float(v))
            return v
        sim._insert_depth = wrapped
        t0 = time.time()
        tr = sim.run(max_steps=a.steps)
        stg = [str(s).replace("阶段 ", "") for s in (tr.get("stage") or [])]
        arr = np.asarray([np.nan if x is None else x for x in dl], float) if dl else np.zeros(0)
        r = {"arm": a.arm, "seed": sd, "env": ARMS[a.arm], "steps": len(stg),
             "done": bool(tr.get("done", [False])[-1]),
             "mm_hits": int(getattr(sim, "_mm_hits", 0) or 0),
             "mm_on": bool(getattr(sim, "_mm_on", False)),
             "muscle_path": os.environ.get("SS_MUSCLE_PATH") or "(默认 data/muscle_memory.json)",
             "stage_counts": dict(collections.Counter(stg)),
             "depth_min_mm": round(float(np.nanmin(arr)) * 1000, 2) if arr.size else None,
             "depth_end_mm": round(float(arr[-1]) * 1000, 2) if arr.size else None,
             "spirals": sum(1 for l in logs if "螺旋搜索" in l),
             "retreats": sum(1 for l in logs if "回退" in l),
             "slip_events": sum(1 for l in logs if "滑脱" in l or "感知偏差" in l),
             "mstop_events": sum(1 for l in logs if "m_stop 交权" in l),
             "risk_last": float(getattr(sim, "_mani_last", {}).get("risk") or 0.0) if getattr(sim, "_mani_last", None) else None,
             "sec": round(time.time() - t0, 1)}
        print(f"[{a.arm:5s} seed{sd}] done={r['done']} depth最小={r['depth_min_mm']}mm "
              f"螺旋={r['spirals']} 回退={r['retreats']} 滑={r['slip_events']} " \
              f"m_stop={r['mstop_events']} "
              f"记忆快通道命中={r['mm_hits']}帧(共{r['steps']}帧, mm_on={r['mm_on']}) "
              f"阶段={r['stage_counts']} · {r['sec']}s", flush=True)
        if jl:
            with open(jl, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
