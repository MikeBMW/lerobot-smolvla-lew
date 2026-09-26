#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""diag_policy_scale.py — state_space 0% 根因裁决: 归一化/尺度 vs 真弱

数据: /home/ubuntu/stable-wm-cache/datasets/cog_engine_trace_v2.h5 (引擎同源: observation 39D + 专家动作 4D)
做法: 真实例化策略 → 对引擎 obs 出动作 → 与**专家动作**比: 尺度(mean/std/|abs|) + 逐维相关
裁决:
  A) |策略动作| ≈ 0 或 std 远小于专家 → **归一化/尺度问题** (假0%)
  B) std 同量级但逐维相关 ≈ 0 → 学歪/口径不符 (obs 布局或训练不足)
  C) std 同量级且相关 > 0.5 → 策略方向对 → 0% 属闭环/时序问题
"""
from __future__ import annotations

import os
import sys

import h5py
import numpy as np

R = "/home/ubuntu/zmax_rel"
sys.path.insert(0, os.path.join(R, "tools"))
sys.path.insert(0, os.path.join(R, "tools/gui"))
sys.path.insert(0, os.path.join(R, "src"))
os.chdir(R)

import torch                                                                  # noqa: E402
from rollout_video import load_policy                                         # noqa: E402

out = load_policy("state_space")
pol = out[0] if isinstance(out, tuple) else out
print("策略:", type(pol).__name__)
dev = "cuda" if torch.cuda.is_available() else "cpu"
try:
    pol = pol.to(dev).eval()          # 🐛 双脑策略内部子模块可能留在 cpu → 显式搬 + eval
except Exception as _e:               # noqa: BLE001
    print("  (pol.to 失败: %s)" % str(_e)[:80])

DS = "/home/ubuntu/stable-wm-cache/datasets/cog_engine_trace_v2.h5"
with h5py.File(DS, "r") as f:
    obs = np.asarray(f["observation"][:1200], dtype=np.float32)
    act = np.asarray(f["action"][:1200], dtype=np.float32)[:, :4]
print("数据: obs %s · 专家动作 %s" % (obs.shape, act.shape))
print("专家动作: |abs|均值 %s · std %s · 范围 [%s, %s]" %
      (np.round(np.abs(act).mean(0), 4), np.round(act.std(0), 4), np.round(act.min(0), 3), np.round(act.max(0), 3)))

outs = []
with torch.no_grad():
    for i in range(0, len(obs), 64):
        b = {"observation.state": torch.from_numpy(obs[i:i + 64]).float().to(dev)}
        try:
            a = pol.select_action(b)
        except TypeError:
            a = pol.select_action(b, l4_cond=None)
        a = a.detach().cpu().numpy().reshape(len(obs[i:i + 64]), -1)[:, :4]
        outs.append(a)
pred = np.concatenate(outs, 0)
print("策略输出: |abs|均值 %s · std %s · 范围 [%s, %s]" %
      (np.round(np.abs(pred).mean(0), 4), np.round(pred.std(0), 4), np.round(pred.min(0), 3), np.round(pred.max(0), 3)))

corr = [float(np.corrcoef(pred[:, k], act[:, k])[0, 1]) if pred[:, k].std() > 1e-9 and act[:, k].std() > 1e-9 else float("nan")
        for k in range(4)]
ratio = (np.abs(pred).mean(0) + 1e-9) / (np.abs(act).mean(0) + 1e-9)
print("逐维相关 策略 vs 专家:", np.round(corr, 3))
print("尺度比 |策略|/|专家|:", np.round(ratio, 4))

mcorr = np.nanmean(np.abs(corr))
mratio = float(np.mean(ratio))
if mratio < 0.3 or mratio > 3.0:
    verdict = "A) 尺度/归一化问题 (假0% 嫌疑): 尺度比 %.2f 偏离 1 太远" % mratio
elif mcorr < 0.3:
    verdict = "B) 学歪/口径不符: 尺度同量级但逐维相关仅 %.2f" % mcorr
else:
    verdict = "C) 方向对 (相关 %.2f): 0%% 属闭环/时序问题" % mcorr
print("\n裁决:", verdict)

# 反归一化线索: 若策略输出被压到 [-1,1] 而专家在更小尺度 → 打印需要的缩放系数
print("提示: 若裁决 A, 需的缩放 ≈ 专家|abs|/策略|abs| =", np.round(1.0 / (ratio + 1e-12), 3))
