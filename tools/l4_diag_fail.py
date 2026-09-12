# -*- coding: utf-8 -*-
"""🔍 L4 失败模式分类 (针对那 75% 卡死回合) — 先定位根因, 再决定调什么

为什么: align_xy_fine 配对复验里 12/16 个 seed **两臂都失败** → 说明失败主因不是对位阈值,
必须把失败拆成类别才知道该动哪个环节。本工具逐 seed 记录:
  · 每阶段步数分布 (tr['stage']) → 卡在哪个阶段
  · 最终插入深度 (tr['dist'][-1]) 与是否超时
  · 引擎日志里的重试事件 (回撤/重对孔/重抓/滑脱/遇阻/死局) 计数
用法: gui-venv311/bin/python tools/l4_diag_fail.py --seeds 1,2,3,4,5 --max-steps 600
"""
import argparse
import json
import os
import re
import sys
import time
from collections import Counter

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
os.environ.setdefault("MUJOCO_GL", os.environ.get("MUJOCO_GL", "egl"))
_CACHE = os.environ.get("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache")
if os.path.isdir(_CACHE):
    os.environ.setdefault("STABLEWM_HOME", _CACHE)
    os.environ.setdefault("LOCAL_DATASET_DIR", _CACHE)

EVENTS = ["回撤", "重对孔", "重抓", "滑脱", "遇阻", "死局", "换新干扰布局", "回接近", "重试"]


def one(seed, max_steps, params=None):
    from state_space_sim_real import RealStateSpaceSim     # noqa: PLC0415
    logbuf = []
    sim = RealStateSpaceSim(seed=seed, vision=False, mode="insert",
                            log=lambda *a: logbuf.append(" ".join(str(x) for x in a)))
    if params:
        sys.path.insert(0, TOOLS)
        from l4_tune import _apply_params                    # noqa: PLC0415
        _orig = sim._reset

        def _p(seed_, *a, **kw):
            r = _orig(seed_, *a, **kw)
            _apply_params(sim, dict(params))
            return r

        sim._reset = _p
    tr = sim.run(max_steps=max_steps)
    stg = [s.replace("阶段 ", "") for s in (tr.get("stage") or [])]
    cnt = Counter(stg)
    ev = {e: sum(1 for ln in logbuf if e in ln) for e in EVENTS}
    ev = {k: v for k, v in ev.items() if v}
    return {"seed": seed, "done": bool(tr["done"][-1]), "steps": len(tr["t"]),
            "insert_mm": round(float(tr["dist"][-1]) * 1000, 1),
            "last_stage": stg[-1] if stg else "?", "stage_steps": dict(cnt),
            "events": ev, "log_tail": [ln for ln in logbuf if any(e in ln for e in EVENTS)][-4:]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="1,2,3,4,5")
    ap.add_argument("--max-steps", type=int, default=600)
    ap.add_argument("--set", default="")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    sys.path.insert(0, TOOLS)
    from l4_tune import parse_set                            # noqa: PLC0415
    params = parse_set(a.set) if a.set else None
    seeds = [int(s) for s in a.seeds.split(",") if s.strip()]
    rows = []
    for seed in seeds:
        r = one(seed, a.max_steps, params)
        rows.append(r)
        top = sorted(r["stage_steps"].items(), key=lambda kv: -kv[1])[:4]
        print(f"  seed{seed}: done={r['done']} 步={r['steps']} 插入={r['insert_mm']}mm "
              f"→ 停[{r['last_stage']}] · 阶段步数Top{top} · 事件={r['events']}", flush=True)
    print("\n═══ 失败模式汇总 (未完成回合) ═══")
    fails = [r for r in rows if not r["done"]]
    agg = Counter(r["last_stage"] for r in fails)
    for k, v in agg.most_common():
        print(f"  卡在[{k}]: {v} 例")
    evagg = Counter()
    for r in fails:
        evagg.update(r["events"])
    print(f"  重试类事件合计: {dict(evagg)}")
    out = a.out or os.path.join(ROOT, "reports", f"l4_fail_diag_{time.strftime('%Y%m%d_%H%M%S')}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"seeds": seeds, "max_steps": a.max_steps, "params": params, "rows": rows},
                  f, ensure_ascii=False, indent=2)
    print(f"  → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
