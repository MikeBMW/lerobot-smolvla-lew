#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L3 「模型执行」为什么没真跑 — 抓 _l3_forward 的异常 (老倪: 断点/真执行)

现象 (探针实测): SS_L3=1 跑 12 步 →
  SmolVLALewPolicy.__init__ 12 次 (每步重载 625M, 类级缓存没写上)
  SmolVLALewPolicy.select_action 0 次  ← 模型从未真执行
本脚本把 _l3_forward 包一层, 打印**真实异常与堆栈**。
用法: HF_HUB_OFFLINE=1 CUDA_VISIBLE_DEVICES= python3 tools/diag_l3_load.py [steps]
"""
from __future__ import annotations

import os
import sys
import traceback

ROOT = "/home/ubuntu/lerobot-smolvla-lew"
sys.path[:0] = [ROOT, os.path.join(ROOT, "src"), os.path.join(ROOT, "tools"),
                os.path.join(ROOT, "tools", "gui")]
os.chdir(ROOT)
os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["MUJOCO_GL"] = "egl"
os.environ.setdefault("DISPLAY", ":0")
os.environ.update({"SS_MUSCLE": "0", "SS_MOTOR_HUB": "0", "SS_INTENT": "0", "SS_TDEC": "0",
                   "SS_OBSERVE": "0", "SS_SHADOW": "0", "SS_L3": "1", "SS_L3_EVERY": "1"})

STEPS = int(sys.argv[1]) if len(sys.argv) > 1 else 6
MSGS: list[str] = []

from state_space_sim_real import RealStateSpaceSim  # noqa: E402

sim = RealStateSpaceSim(seed=0, vision=os.environ.get("PROBE_VISION", "0") == "1", mode="insert",
                        log=lambda *a: MSGS.append(" ".join(str(x) for x in a)))

_orig = sim._l3_forward
_errs: list[str] = []


def _wrapped(visual39):
    try:
        r = _orig(visual39)
        print(f"   [L3] _l3_forward 正常返回: {None if r is None else np.shape(r)}")
        return r
    except Exception as e:                                                       # noqa: BLE001
        tb = traceback.format_exc()
        _errs.append(f"{type(e).__name__}: {e}")
        print(f"   [L3] ❌ _l3_forward 抛异常: {type(e).__name__}: {e}")
        print("        " + "\n        ".join(tb.strip().splitlines()[-8:]))
        raise


import numpy as np  # noqa: E402

sim._l3_forward = _wrapped
tr = sim.run(max_steps=STEPS)
print(f"\n步数={len(tr.get('stage', []))} · 引擎 l3_calls={getattr(sim, '_l3_calls', 0)}")
print(f"类级缓存 _L3_CACHE 是否写上: {getattr(RealStateSpaceSim, '_L3_CACHE', None) is not None}")
print(f"策略实例 self._l3_pol: {getattr(sim, '_l3_pol', None) is not None}")
print(f"异常次数: {len(_errs)} · 首个: {_errs[0] if _errs else '-'}")
print("\n引擎日志 (含 ⚠️ 行):")
for m in MSGS:
    if "L3" in m or "⚠" in m or "失败" in m:
        print("   ", m[:300])
