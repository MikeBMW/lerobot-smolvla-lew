#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""辨明 obs 口径: 引擎 tr["obs"] vs env._get_obs()[:39], 哪个匹配 v5/v6?

方法: monkey-patch sim.env._get_obs 记录每步 env 原生 obs (不改引擎文件),
      与 tr["obs"] 一起跟 v6 数据集的逐维统计比对。
"""
import os
import sys

import numpy as np

os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("LOCAL_DATASET_DIR", "/home/ubuntu/stable-wm-cache")
os.environ.setdefault("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache")

R = "/home/ubuntu/lerobot-smolvla-lew"
sys.path.insert(0, R + "/src")
sys.path.insert(0, R + "/tools/gui")
os.chdir(R + "/tools/gui")

import h5py
from state_space_sim_real import RealStateSpaceSim

sim = RealStateSpaceSim(seed=104, vision=False, log=lambda *a: None)

# ★ monkey-patch: 每步记录 env 原生 obs (不改引擎文件)
env_rec = []
orig_get_obs = sim.env._get_obs


def patched():
    o = orig_get_obs()
    try:
        env_rec.append(np.asarray(o, dtype=np.float64).ravel()[:39].copy())
    except Exception:
        pass
    return o


sim.env._get_obs = patched

tr = sim.run(max_steps=400)

eng = np.asarray([np.asarray(x, dtype=np.float64).ravel()[:39] for x in tr["obs"]])
envn = np.asarray(env_rec)

v6 = h5py.File("/home/ubuntu/stable-wm-cache/datasets/v6_train_rand.h5", "r")["observation"]
v6s = np.asarray(v6[0:3000], dtype=np.float64)

print(f"样本数: tr['obs']={len(eng)} · env._get_obs={len(envn)} · v6={len(v6s)}")
print(f"均值 |v6 - tr['obs']| 参考: 见下表")
print()
print("idx |    v6 mean±std     |  tr['obs'] mean±std  | env._get_obs mean±std")
for i in list(range(6)) + [7, 8, 9, 10, 11, 12]:
    print(f"{i:3d} | {v6s[:, i].mean():+7.3f}±{v6s[:, i].std():6.3f} | "
          f"{eng[:, i].mean():+7.3f}±{eng[:, i].std():6.3f} | "
          f"{envn[:, i].mean():+7.3f}±{envn[:, i].std():6.3f}")

d_tr = np.abs(v6s.mean(0) - eng.mean(0)).mean()
d_env = np.abs(v6s.mean(0) - envn.mean(0)).mean()
_win = 'tr_obs' if d_tr < d_env else 'env._get_obs()[:39]'
print()
print(f"平均逐维均值差:  tr['obs']={d_tr:.4f}   env._get_obs={d_env:.4f}")
print(f"→ 匹配 v5/v6 约定的是: {_win}")
print(f"  (差 {abs(d_tr - d_env):.4f}, {'显著' if abs(d_tr - d_env) > 0.05 else '接近/需更多样本'})")
