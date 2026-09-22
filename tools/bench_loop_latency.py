#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""⚡ 快速性基准: 冷加载 vs 稳态 (定位真正的延迟来源)

闭环实测 ③ INTACT 4.65s / ② 安全闸门 2.05s — 但这些含**首次 import/模型加载**。
稳态 (真机连续调用) 的延迟才是产线关心的。本脚本分离两者:
  · 冷 = 首次 import + 首次 step
  · 热 = 后续 N 次 step 的中位/均值
给优化提供依据 (该缓存什么)。
"""
from __future__ import annotations

import os
import statistics
import sys
import time

ROOT = "/home/ubuntu/lerobot-smolvla-lew"
sys.path.insert(0, f"{ROOT}/src")
sys.path.insert(0, f"{ROOT}/tools/gui")
os.chdir(ROOT)
os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("LOCAL_DATASET_DIR", "/home/ubuntu/stable-wm-cache")
os.environ.setdefault("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache")

import numpy as np

print("=" * 96)
print("⚡ 快速性基准 (冷加载 vs 稳态)")
print("=" * 96)


def bench(name, cold_fn, hot_fn, n_hot=10, unit="ms"):
    t0 = time.time()
    try:
        cold_fn()
        cold = (time.time() - t0) * 1000
    except Exception as e:                                                # noqa: BLE001
        print(f"  ❌ {name}: 冷启动失败 {type(e).__name__}: {e}")
        return
    hs = []
    for _ in range(n_hot):
        t = time.time()
        try:
            hot_fn()
            hs.append((time.time() - t) * 1000)
        except Exception:                                                 # noqa: BLE001
            pass
    if not hs:
        print(f"  ⚠️ {name}: 冷 {cold:8.1f}ms · 热无样本")
        return
    med, mean, mn = statistics.median(hs), statistics.mean(hs), min(hs)
    speedup = cold / med if med > 0 else 0
    print(f"  {name}")
    print(f"     冷(含加载) {cold:8.1f}ms | 热 中位 {med:7.1f}ms 均值 {mean:7.1f}ms 最快 {mn:7.1f}ms"
          f" | **加速 {speedup:.1f}×**")


# ① L4 INTACT 零搜索推理
_node = {}


def _intact_cold():
    from lerobot.manifold.intact_node import IntactNode
    _node["n"] = IntactNode(horizon=8)
    _node["n"].set_data_source("official", task="cube")
    _node["n"].step()


def _intact_hot():
    _node["n"].step()


bench("③ L4 INTACT 零搜索动作块", _intact_cold, _intact_hot, n_hot=10)

# ② L4 安全闸门 (saturate 限幅)
_saf = {}


def _saf_cold():
    import importlib
    _saf["m"] = importlib.import_module("lerobot.policies.left_right.state_space.safety")
    _saf["m"].saturate(np.array([9., -9., .5, .5], np.float32))


def _saf_hot():
    _saf["m"].saturate(np.array([9., -9., .5, .5], np.float32))


bench("② L4 安全闸门 (saturate)", _saf_cold, _saf_hot, n_hot=200)

# ④ L2 感知 2D→3D
_d = {}


def _d3_cold():
    from lerobot.policies.yolo_3d.depth_align import depth_3d_from_box
    _d["f"] = depth_3d_from_box
    _d["dm"] = np.full((480, 640), 0.42, np.float32)
    _d["f"]([300, 220, 340, 260], _d["dm"], [394.06, 0, 318.44, 0, 393.47, 238.66, 0, 0, 1])


def _d3_hot():
    _d["f"]([300, 220, 340, 260], _d["dm"], [394.06, 0, 318.44, 0, 393.47, 238.66, 0, 0, 1])


bench("④ L2 感知 2D→3D 反投影", _d3_cold, _d3_hot, n_hot=200)

# ① L5 规划
_pl = {}


def _pl_cold():
    import importlib.util as _ilu
    _p = os.path.join(ROOT, "src", "lerobot", "policies", "left_right", "state_space", "planner.py")
    _s = _ilu.spec_from_file_location("l5b", _p)
    _m = _ilu.module_from_spec(_s)
    _s.loader.exec_module(_m)
    _cls = next(getattr(_m, c) for c in dir(_m) if "Planner" in c)
    _pl["p"] = _cls()
    _pl["p"].plan("把光模块插入端口并完成AOI检测")


def _pl_hot():
    _pl["p"].plan("把光模块插入端口并完成AOI检测")


bench("① L5 指令→技能序列", _pl_cold, _pl_hot, n_hot=200)

# ⑥⑦ 记忆查询
_gm = {}


def _mem_cold():
    from lerobot.memory.global_memory import GlobalMemory
    _gm["g"] = GlobalMemory()
    _gm["g"].query("插入")


def _mem_hot():
    _gm["g"].query("插入")


bench("⑥ 记忆·全局中枢三层查询", _mem_cold, _mem_hot, n_hot=50)

print("=" * 96)
print("结论: 冷/热差 = 可缓存的加载开销; 热延迟 = 产线真实节拍开销")
print("=" * 96)
