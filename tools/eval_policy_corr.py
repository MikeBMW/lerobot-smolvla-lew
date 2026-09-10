#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""策略-专家一致性"照妖镜" — 在真实引擎轨迹上量化 ckpt 到底学没学会

比"任务成功率"敏感得多: 成功率只有 0/8 或 8/8 两态, 而相关性/符号一致率能看到
"正在学会"还是"完全无关"。

口径 (全部与训练侧同源, 见技能 robot-policy-eval-pitfalls ⑦⑧):
  state  : 引擎构造 39D (visual39) — 数据集 stats 实测 [4:7]=速度, [7:10]=peg
  image  : 128×128 LANCZOS (同训练采集)
  task   : "peg-insert-side-v3" (数据集 tasks.parquet 原串)
  expert : 引擎实际执行动作 (帧钩子 act 参数 = 训练标签)
  pred   : policy 输出经官方 postprocessor 反归一化

输出: MAE(每维) / Pearson 相关 / 符号一致率 / gripper 二值一致率 / 有效动作占比
用法: cd repo && SS_L3_CK=<ckpt> gui-venv311/bin/python tools/eval_policy_corr.py [seed] [every]
"""
import json
import os
import sys

import numpy as np

os.environ.setdefault('MUJOCO_GL', 'egl')
os.environ.setdefault('DISPLAY', ':0')
ROOT = '/home/ubuntu/lerobot-smolvla-lew'
for _p in (ROOT, os.path.join(ROOT, 'src'), os.path.join(ROOT, 'tools'), os.path.join(ROOT, 'tools', 'gui')):
    sys.path.insert(0, _p)
os.chdir(ROOT)
import torch                                            # noqa: E402
from PIL import Image                                   # noqa: E402
from state_space_sim_real import RealStateSpaceSim      # noqa: E402
from lerobot.policies.smolvla_lew.modeling_smolvla_lew import SmolVLALewPolicy  # noqa: E402
from lerobot.policies import make_pre_post_processors   # noqa: E402

os.environ.update({"SS_MUSCLE": "0", "SS_INTENT": "0", "SS_TDEC": "0",
                   "SS_OBSERVE": "0", "SS_SHADOW": "0", "SS_L3": "0"})
CK = os.environ.get('SS_L3_CK', 'outputs/train/smolvla_lew_v8/checkpoints/030000/pretrained_model')
TASK = os.environ.get('SS_L3_TASK', 'peg-insert-side-v3')
SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 104
EVERY = int(sys.argv[2]) if len(sys.argv) > 2 else 4

pol = SmolVLALewPolicy.from_pretrained(CK, local_files_only=True).cuda().eval()
pre, post = make_pre_post_processors(policy_cfg=pol.config, pretrained_path=CK)
print(f"🧪 ckpt: {CK}\n   task: {TASK!r} | seed {SEED} | 每 {EVERY} 步一帧")

sim = RealStateSpaceSim(seed=SEED, vision=False, mode="insert", log=lambda *a: None)
imgs, experts = [], []


def sink(_s, act, _o, *_a):
    try:
        imgs.append(np.asarray(sim.env.render()))
    except Exception:
        imgs.append(np.zeros((480, 480, 3), np.uint8))
    experts.append(np.asarray(act, np.float32).ravel()[:4].copy())


sim._frame_sink = sink
tr = sim.run(max_steps=1200)
done = bool(tr["done"][-1]) if tr.get("done") else False
n = min(len(imgs), len(experts), len(tr.get("obs", [])))
print(f"   引擎轨迹 {n} 步 · done={done}")

P, E = [], []
for i in range(0, n, EVERY):
    st = np.asarray(tr["obs"][i], np.float32).ravel()[:39]
    img128 = np.asarray(Image.fromarray(imgs[i]).resize((128, 128), Image.LANCZOS)
                        ).transpose(2, 0, 1) / 255.0
    b = pre({'observation.image': torch.from_numpy(img128).float(),
             'observation.state': torch.from_numpy(st).float()})
    b['task'] = TASK
    try:
        pol.reset()
    except Exception:
        pass
    with torch.no_grad():
        pred = pol.select_action(b)
    P.append(np.asarray(post(pred).detach().cpu().float()).ravel()[:4])
    E.append(experts[i])
P = np.stack(P); E = np.stack(E)
k = len(P)
print(f"   有效样本 {k}\n")

names = ['x', 'y', 'z', 'gripper']
res = {'ckpt': CK, 'seed': SEED, 'n': k, 'engine_done': done, 'per_dim': {}}
print(f"{'维':>8} | {'MAE':>8} {'专家幅度':>9} {'MAE/幅度':>9} {'相关':>7} {'符号一致':>8}")
for d in range(4):
    mae = float(np.abs(P[:, d] - E[:, d]).mean())
    amp = float(np.abs(E[:, d]).mean())
    corr = float(np.corrcoef(P[:, d], E[:, d])[0, 1]) if P[:, d].std() > 1e-9 else 0.0
    sgn = float((np.sign(P[:, d]) == np.sign(E[:, d])).mean())
    res['per_dim'][names[d]] = {'mae': round(mae, 4), 'expert_amp': round(amp, 4),
                                'mae_over_amp': round(mae / (amp + 1e-9), 3),
                                'corr': round(corr, 3), 'sign_agree': round(sgn, 3)}
    print(f"{names[d]:>8} | {mae:8.4f} {amp:9.4f} {mae/(amp+1e-9):9.2f} {corr:7.3f} {sgn:8.3f}")
# gripper 二值一致
gb = float((P[:, 3] < 0).mean())
gb2 = float((E[:, 3] < 0).mean())
res['gripper_close_ratio'] = {'model': round(gb, 3), 'expert': round(gb2, 3)}
xyz_corr = np.mean([abs(res['per_dim'][d]['corr']) for d in ('x', 'y', 'z')])
res['xyz_mean_abs_corr'] = round(float(xyz_corr), 4)
print(f"\n  夹爪闭合比例: 模型 {gb:.2f} vs 专家 {gb2:.2f}")
print(f"  ★ xyz 平均|相关| = {xyz_corr:.3f}   (>0.5 才算学到; ≈0 = 输出与输入无关)")
print("  判读: MAE/幅度 ≈1 且 |相关|≈0 → 模型在'猜均值'; |相关|>0.5 → 真在跟")
os.makedirs('reports', exist_ok=True)
out = f"/tmp/policy_corr_{os.path.basename(os.path.dirname(os.path.dirname(CK)))}.json"
json.dump(res, open(out, 'w'), ensure_ascii=False, indent=1)
print(f"→ {out}")
