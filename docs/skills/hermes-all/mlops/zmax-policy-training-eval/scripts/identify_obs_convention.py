#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨数据集比对前的 obs 口径辨明（必跑，否则会得出假结论）

背景（真实教训，2026-09-23）:
  引擎里有**两个都叫 39 维**的观测:
    tr["obs"]              = 引擎 fuse_sensors(concat([cur18, prev18, target3]), force, tactile4)[:39]
    env._get_obs()[:39]    = metaworld env 原生观测  ← **训练数据集 (v5/v6) 用的是这个**
  我误用 tr["obs"] 造数据/做留出集 → 逐维均值差 0.1793 (正确源只有 0.0286)
  → 拿两套语义不同的数据比对 → 得出"联合训练过拟合/表征被冲垮"的**假结论**（已作废撤回）

本脚本作用:
  跑一次引擎，同一步同时记录两个候选向量，与参考数据集逐维比对均值/std，
  直接告诉哪个候选才与训练数据同源。**不改引擎文件**（monkey-patch 只挂运行时钩子）。

用法:
  # 参考数据集 = 你要与之对齐的训练 h5
  gui-venv311/bin/python identify_obs_convention.py \
      --ref /home/ubuntu/stable-wm-cache/datasets/optical_insert_v6_disturb.h5 \
      --steps 300

输出判读:
  "平均逐维均值差" 小的那个 = 同源口径 → 造数据/评估都用它
  本会话实测: tr['obs']=0.1793  vs  env._get_obs=0.0273  →  env 胜（差 0.15，显著）

关键实现点（改代码时别破坏）:
  · 挂 `sim.perception.fuse_sensors`（每步恰好调 1 次）→ 精确 1:1 对齐轨迹步
    不要挂 env._get_obs（每步被调约 2 次，340 步收到 683 条 → 对不齐）
  · 钩子必须在 sim.run() **之前**安装，run() 之后取回调
"""
import argparse
import os
import sys

import numpy as np


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", required=True, help="参考训练 h5（含 observation）")
    ap.add_argument("--steps", type=int, default=300)
    ap.add_argument("--seed", type=int, default=104)
    a = ap.parse_args()

    ROOT = "/home/ubuntu/lerobot-smolvla-lew"
    sys.path.insert(0, f"{ROOT}/src")
    sys.path.insert(0, f"{ROOT}/tools/gui")
    os.environ.setdefault("LOCAL_DATASET_DIR", "/home/ubuntu/stable-wm-cache")
    os.environ.setdefault("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache")
    os.environ.setdefault("MUJOCO_GL", "egl")

    import h5py

    # 参考数据集的 obs 统计
    f = h5py.File(a.ref, "r")
    n = int(f["observation"].shape[0])
    o_ref = np.asarray(f["observation"][: min(n, 3000)], dtype=np.float64)
    f.close()
    ref_mean, ref_std = o_ref.mean(0), o_ref.std(0)
    print(f"参考 {os.path.basename(a.ref)}: {o_ref.shape} 帧统计完成")

    from state_space_sim_real import RealStateSpaceSim

    sim = RealStateSpaceSim(seed=a.seed, vision=False, log=lambda *x: None)

    # ★ 非侵入式采集: 挂 fuse_sensors（每步 1 次），不改引擎文件
    rec = {"env": []}
    orig_fuse = sim.perception.fuse_sensors

    def patched_fuse(visual39, force, tactile4):
        try:
            rec["env"].append(np.asarray(sim.env._get_obs(), dtype=np.float64).ravel()[:39].copy())
        except Exception:
            pass
        return orig_fuse(visual39, force, tactile4)

    sim.perception.fuse_sensors = patched_fuse
    tr = sim.run(max_steps=a.steps)

    tr_obs = np.asarray(tr["obs"], dtype=np.float64)
    tr_obs = tr_obs.reshape(-1, tr_obs.shape[-1])[:, :39] if tr_obs.ndim > 1 else tr_obs[:39][None]
    env_obs = np.asarray(rec["env"], dtype=np.float64)

    print(f"轨迹步数 {len(tr['obs'])} · 采集到 env 原生 obs {len(env_obs)} 条")
    if len(env_obs) != len(tr["obs"]):
        print("  ⚠️ 采集条数与步数不等 → 钩子挂错位置（应挂 fuse_sensors，非 env._get_obs）")

    print(f"\n{'idx':>4} {'参考mean':>11} {'参考std':>10} {'tr_obs':>10} {'env._get_obs':>13}")
    for i in list(range(min(14, ref_mean.size))):
        e = f"{env_obs[:, i].mean():+.3f}" if env_obs.size else "  n/a"
        print(f"{i:>4} {ref_mean[i]:>+11.3f} {ref_std[i]:>10.3f} {tr_obs[:, i].mean():>+10.3f} {e:>13}")

    d_tr = float(np.abs(tr_obs.mean(0)[:39] - ref_mean[:39]).mean())
    d_env = float(np.abs(env_obs.mean(0)[:39] - ref_mean[:39]).mean()) if env_obs.size else float("inf")
    win = "tr['obs']" if d_tr < d_env else "env._get_obs()[:39]"
    print(f"\n平均逐维均值差:  tr['obs']={d_tr:.4f}   env._get_obs={d_env:.4f}")
    print(f"→ **同源口径 = {win}**  （造数据/评估都必须用这个）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
