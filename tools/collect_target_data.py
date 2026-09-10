#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""采集 target-decoder 训练数据: 引擎成功轨迹的 (阶段, 几何) → 期望位置 target

标签两套 (同一份数据, 两种监督):
  y_target : 引擎 _stage_target() 的输出 (规则版意图)  → 学"规则意图"
  y_next   : 下一帧实际位置 x_{t+1} (成功轨迹的真实运动) → 学"运动策略"(有增益潜力)

特征 (16D): stage one-hot(8) + 手 xyz(3) + 光模块 xyz(3) + 孔位置 xyz(2 相对) …
  —— 实际: onehot8 + hand3 + peg3 + hole3 = 17D (孔位置每场景常值)

产物: data/target_decoder_data.npz
用法: cd repo && gui-venv311/bin/python tools/collect_target_data.py [seed_start] [seed_end]
"""
import os
import sys

import numpy as np

os.environ.setdefault('MUJOCO_GL', 'egl')
os.environ.setdefault('DISPLAY', ':0')
ROOT = '/home/ubuntu/lerobot-smolvla-lew'
for p in (ROOT, os.path.join(ROOT, 'src'), os.path.join(ROOT, 'tools'), os.path.join(ROOT, 'tools', 'gui')):
    sys.path.insert(0, p)
os.chdir(ROOT)
from state_space_sim_real import RealStateSpaceSim  # noqa: E402

STAGES = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"]
os.environ.update({"SS_MUSCLE": "0", "SS_INTENT": "0", "SS_OBSERVE": "0", "SS_SHADOW": "0"})

a, b = int(sys.argv[1]) if len(sys.argv) > 1 else 100, int(sys.argv[2]) if len(sys.argv) > 2 else 130
X, YT, YN, EP = [], [], [], []
n_ok = 0
for seed in range(a, b + 1):
    sim = RealStateSpaceSim(seed=seed, vision=False, mode="insert", log=lambda *x: None)
    # 🐛 2026-09-10: run() 内部自己做 _reset(self.seed) (line 828) — 外部手工 reset 多余且易不一致, 删掉
    tr = sim.run(max_steps=1200)
    if not (tr.get("done") and tr["done"][-1]):
        print(f"  seed{seed}: 未完成, 跳过", flush=True)
        continue
    try:
        # 🐛 2026-09-10: sim._hole_p() 在 run 后取值失败(返回 0) → 直接读 env site 真值
        #   孔位置场景内固定, run 后读同样正确
        hole = np.asarray(sim.env.data.site_xpos[sim.env.model.site('goal').id], float).copy()
    except Exception:
        hole = np.zeros(3)
    stages = [str(s).replace("阶段 ", "").split("·")[0].strip() for s in tr["stage"]]
    x = np.asarray(tr["x"], float)
    # 🐛 2026-09-10 实锤: 引擎 39D obs 的 [4:7] 是 **速度 self.v** (obs[0:3]=手, [3]=gripper,
    #   [7:10]=peg, [10:13]=goal) — 取 obs[:,4:7] 当 peg = 特征里塞了速度 (~0) → decoder 全崩!
    #   正确来源: tr["peg"] = env o[4:7] (光模块绝对位置), 与推理侧 _peg_cur 同源。
    peg = np.asarray(tr["peg"], float)
    tgt = np.asarray(tr["target"], float)
    n = min(len(stages), len(x), len(peg), len(tgt))
    fs, ts, ns = [], [], []
    for i in range(n):
        oh = np.zeros(len(STAGES), np.float32)
        if stages[i] in STAGES:
            oh[STAGES.index(stages[i])] = 1.0
        fs.append(np.concatenate([oh, x[i], peg[i], hole]).astype(np.float32))
        ts.append(tgt[i][:3].astype(np.float32))
        ns.append((x[i + 1] if i + 1 < n else x[i]).astype(np.float32))
    X.append(np.stack(fs)); YT.append(np.stack(ts)); YN.append(np.stack(ns))
    EP.append(np.full(n, seed, np.int64))
    n_ok += 1
    print(f"  seed{seed}: ✅ {n} 帧 (孔 {hole.round(3)}) [{n_ok}]", flush=True)

if not X:
    print("❌ 无成功轨迹"); sys.exit(1)
out = os.path.join(ROOT, "data", "target_decoder_data.npz")
np.savez_compressed(out, X=np.concatenate(X), Y_target=np.concatenate(YT),
                    Y_next=np.concatenate(YN), episode=np.concatenate(EP), stages=np.array(STAGES))
print(f"\n✅ {n_ok} 轨迹 / {len(np.concatenate(X))} 帧 → {out}")
