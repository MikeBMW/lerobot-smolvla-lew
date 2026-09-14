#!/usr/bin/env python3
"""Metaworld 渲染自检 — 验证 WSL 渲染是否出真图 (黑屏诊断用)
用法: .venv/bin/python scripts/check_mujoco_render.py
期望输出: render var≈4375 unique≈256 (真图); 若 var≈0 即黑屏需查 render_mode/GL env
"""
import os, sys

# 必须在 import mujoco/metaworld 之前设置!
os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("MUJOCO_GL", "glfw")
os.environ.setdefault("MUJOCO_EGL_DEVICE", "0")

import numpy as np
import metaworld
from metaworld.env_dict import ALL_V3_ENVIRONMENTS

TASK = sys.argv[1] if len(sys.argv) > 1 else "push-v3"

# 方式1: render_mode="rgb_array" (推荐)
try:
    env = ALL_V3_ENVIRONMENTS[TASK](render_mode="rgb_array")
    mt1 = metaworld.MT1(TASK, seed=0)
    env.set_task(mt1.train_tasks[0])
    env.reset(seed=0)
    rgb = np.asarray(env.render())
    print(f"[rgb_array] {TASK}: shape={rgb.shape} var={rgb.var():.1f} unique={len(np.unique(rgb))}")
    ok = rgb.var() > 1000 and len(np.unique(rgb)) > 50
    print("✅ 真渲染" if ok else "❌ 黑屏! 检查: 1) render_mode 参数 2) DISPLAY/MUJOCO_GL 是否在 import 前设置")
except Exception as ex:
    print(f"[rgb_array] 失败: {ex}")

# 方式2: 默认模式 (对照 — 通常黑屏)
try:
    env2 = ALL_V3_ENVIRONMENTS[TASK]()
    mt1 = metaworld.MT1(TASK, seed=0)
    env2.set_task(mt1.train_tasks[0])
    env2.reset(seed=0)
    rgb2 = np.asarray(env2.render())
    print(f"[default] {TASK}: var={rgb2.var():.1f} unique={len(np.unique(rgb2))} (对照, 通常黑)")
except Exception as ex:
    print(f"[default] 失败: {type(ex).__name__}: {ex}")
