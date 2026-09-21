#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ss_sim_episodes_to_dataset.py — 仿真 episode(npz) → 蒸馏训练集(ss_insert/*.npz) → LeRobot

背景 (2026-09-21): 三级能力测试里 16 条 t_ff_* 全挂 = "训练域 0 帧"。
根因: 前馈/肌肉记忆断言从 `data/ss_insert_lerobot/data/chunk-*/file-*.parquet` 随机取真实 43D 帧,
而该数据集不存在(引擎口径: 训练域由 export_dataset 决定)。
本脚本把 gen_ss_metaworld_episode.py 产出的 episode 转成 build_ss_dataset.py 认的格式:
  states  = obs[:, :39]     (39D: [0:3]末端 [3]夹爪 [36:39]目标; 43D 只是多 4 维触觉尾巴, MLP 只吃 [:39])
  actions = u_ff_vec        (4D 前馈建议动作 = 蒸馏 MLP 的学习目标)
  success = meta.success
用法: gui-venv311/bin/python tools/ss_sim_episodes_to_dataset.py <episodes目录> [输出目录=data/ss_insert]
"""
from __future__ import annotations

import glob
import json
import os
import sys

import numpy as np

EP_DIR = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/zmax_data/ss_sim_20260921")
OUT = sys.argv[2] if len(sys.argv) > 2 else "/home/ubuntu/lerobot-smolvla-lew/data/ss_insert"
os.makedirs(OUT, exist_ok=True)

eps = sorted(glob.glob(os.path.join(EP_DIR, "ep_s*.npz")))
if not eps:
    raise SystemExit("没有 episode: %s/ep_s*.npz" % EP_DIR)
print("输入 episode: %d 个 → %s" % (len(eps), OUT))

n_ok = 0
tot = 0
for i, p in enumerate(eps, 1):
    d = np.load(p, allow_pickle=True)
    obs = np.asarray(d["obs"], dtype=np.float32)
    act = np.asarray(d["u_ff_vec"], dtype=np.float32)
    n = min(len(obs), len(act))
    obs, act = obs[:n], act[:n]
    meta = d["meta"][0] if "meta" in d else {}
    succ = bool(meta.get("success", False)) if isinstance(meta, dict) else False
    if obs.shape[1] < 39 or act.shape[1] != 4 or n < 10:
        print("  ⚠️ %s 跳过: obs%s act%s n=%d" % (os.path.basename(p), obs.shape, act.shape, n))
        continue
    dst = os.path.join(OUT, "sim_ep%02d.npz" % i)
    np.savez_compressed(dst, states=obs[:, :39], actions=act,
                        success=np.array([succ]), src=os.path.basename(p),
                        stage_final=str(meta.get("stage_final", "")))
    tot += n
    n_ok += 1
    print("  ✅ %s → %s  states%s actions%s success=%s 阶段=%s"
          % (os.path.basename(p), os.path.basename(dst), obs[:, :39].shape, act.shape,
             succ, meta.get("stage_final", "")))
print("完成: %d/%d episode · 共 %d 帧 → %s" % (n_ok, len(eps), tot, OUT))
json.dump({"episodes": n_ok, "frames": tot, "src": EP_DIR, "out": OUT},
          open(os.path.join(OUT, "MANIFEST.json"), "w"), ensure_ascii=False, indent=1)
