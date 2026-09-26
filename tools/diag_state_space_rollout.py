#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""diag_state_space_rollout.py — 定位 state_space 策略仿真 0/5 的真因 (假0% vs 真弱)

假0%经典成因 (见 skill robot-policy-eval-pitfalls):
  a) 图像尺寸口径不符 (训练 128 vs 评测 224/256)
  b) 逐维归一化 stats 缺失/错源 → 动作被压缩到 0
  c) 反归一化没做 (输出 -1..1 直接当米制下发)
  d) 夹爪/动作头分离 (action 维拼接顺序错)
判据: 打印策略前若干步原始动作 (min/max/mean/abs) + 与数据集动作统计对比
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

R = "/home/ubuntu/zmax_rel"
sys.path.insert(0, os.path.join(R, "tools"))
sys.path.insert(0, os.path.join(R, "tools/gui"))
sys.path.insert(0, os.path.join(R, "src"))
os.chdir(R)

from rollout_video import load_policy                                             # noqa: E402

print("═══ ① 装载 state_space 策略 ═══")
pol, meta = None, {}
try:
    out = load_policy("state_space")
    pol = out[0] if isinstance(out, tuple) else out
    print("   装载 OK:", type(pol).__name__)
except Exception as e:                                                            # noqa: BLE001
    print("   ❌ 装载失败:", type(e).__name__, str(e)[:200])
    raise SystemExit(1)

print("═══ ② 训练曲线口径 (图像尺寸/归一化/动作维) ═══")
cf = os.path.join(R, "reports/train_curve_state_space.json")
if os.path.isfile(cf):
    print("   ", json.dumps(json.load(open(cf, encoding="utf-8")), ensure_ascii=False)[:400])

print("═══ ③ 引擎里真跑 20 步, 看策略输出动作幅度 ═══")
from state_space_sim_real import RealStateSpaceSim                                # noqa: E402
sim = RealStateSpaceSim(seed=0, vision=False, mode="insert", log=lambda *a: None)
obs = sim.reset() if hasattr(sim, "reset") else None
acts = []
try:
    import torch
    for i in range(20):
        step = sim.step_with_policy(pol) if hasattr(sim, "step_with_policy") else None
        if step is None:
            break
        acts.append(np.asarray(step))
except Exception as e:                                                            # noqa: BLE001
    print("   (无 step_with_policy 接口: %s) → 改用 rollout 脚本内部路径" % str(e)[:80])
# 退路: 直接问 rollout_peg_check 的日志幅度
if not acts:
    import subprocess
    r = subprocess.run([os.path.join(R, "gui-venv311/bin/python"), "tools/rollout_peg_check.py",
                        "--policy", "state_space", "--n", "1", "--steps", "30"],
                       cwd=R, capture_output=True, text=True, timeout=300)
    print("   rollout 输出尾部:")
    for ln in (r.stdout or "").strip().splitlines()[-8:]:
        print("     ", ln[:150])
else:
    a = np.array(acts, dtype=float)
    print("   动作矩阵 %s | min=%.4f max=%.4f mean=%.4f |abs|均值=%.4f" %
          (a.shape, a.min(), a.max(), a.mean(), np.abs(a).mean()))
    print("   逐维 |abs| 均值:", np.round(np.abs(a).mean(0), 4))
print("\n提示: 若 |动作| 近 0 → 假0% (归一化/反归一化/头分离); 若动作正常但拿不到孔 → 真弱 (训练不足)")
