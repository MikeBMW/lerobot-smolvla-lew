# -*- coding: utf-8 -*-
"""🔬 diag_retreat_reason.py — 解析链插入失败的**触发原因**取证 (2026-09-15)

已证 (diag_insert_depth): seed1 顶壁卡死 depth=31.5mm/力0.98; seed2 插入段仅6帧/力0.03。
本脚本把引擎的决策日志收下来, 按关键词统计"回退/回撤/螺旋/重抓/否决"的触发次数与原文,
定位是哪个判据在把机器人拉回去。
用法: MUJOCO_GL=egl gui-venv311/bin/python tools/diag_retreat_reason.py --seeds 1,2 --steps 600
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter

import numpy as np

os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("DISPLAY", ":0")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUI = os.path.join(ROOT, "tools", "gui")
for _p in (ROOT, os.path.join(ROOT, "src"), os.path.join(ROOT, "tools"), GUI):
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.chdir(GUI)
for k, v in (("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache"),
             ("LOCAL_DATASET_DIR", "/home/ubuntu/stable-wm-cache"),
             ("INTACT_RUNTIME", "root"), ("INTACT_POLICY", "intact_l4_current"),
             ("OMP_NUM_THREADS", "6")):
    os.environ.setdefault(k, v)
os.environ.pop("SS_L4_INTACT", None)
os.environ.pop("SS_L4_INTENT_LINE", None)
KW = ("回撤", "回退", "螺旋", "重抓", "否决", "滑", "丢失", "顶", "遇阻", "偏差", "守卫")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="1,2")
    ap.add_argument("--steps", type=int, default=600)
    a = ap.parse_args()
    for sd in [int(x) for x in a.seeds.split(",") if x.strip()]:
        from state_space_sim_real import RealStateSpaceSim
        logs: list = []
        sim = RealStateSpaceSim(seed=sd, vision=False, mode="insert", log=lambda *x: logs.append(" ".join(map(str, x))))
        tr = sim.run(max_steps=a.steps)
        stg = [str(s).replace("阶段 ", "") for s in (tr.get("stage") or [])]
        hits = [l for l in logs if any(k in l for k in KW)]
        cnt = Counter()
        for l in hits:
            for k in KW:
                if k in l:
                    cnt[k] += 1
        print(f"\n=== seed{sd} === 步数={len(stg)} done={tr.get('done',[False])[-1]} "
              f"阶段={dict(Counter(stg))}")
        print(f"  决策日志 {len(logs)} 条, 其中关键事件 {len(hits)} 条 · 关键词计数 {dict(cnt)}")
        seen = set()
        shown = 0
        for l in hits:
            key = re.sub(r"[-+]?\d+\.\d+", "#", l)[:70]
            if key in seen:
                continue
            seen.add(key)
            print(f"    · {l[:150]}")
            shown += 1
            if shown >= 14:
                break
    return 0


if __name__ == "__main__":
    sys.exit(main())
