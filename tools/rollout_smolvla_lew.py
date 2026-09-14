#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v9 (smolvla_lew) 闭环 rollout — ✅ 引擎同源 env + ✅ 官方 pre/post pipeline

关键修复 (2026-09-10): 旧版手动 mean/std 归一化 = 双重归一化错口径!
  policy 自带 normalizer: STATE=MEAN_STD / **ACTION=MIN_MAX** / VISUAL=IDENTITY
  → 必须传 raw state 给 pre(), 用 post() 反归一化动作。手动 *std+mean 是错的。

用法: cd repo && MUJOCO_GL=egl gui-venv311/bin/python tools/rollout_smolvla_lew.py [seed ...]
"""
import sys, os, json, subprocess
import numpy as np
os.environ.setdefault('MUJOCO_GL', 'egl')
os.environ.setdefault('DISPLAY', ':0')
ROOT = '/home/ubuntu/lerobot-smolvla-lew'
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
sys.path.insert(0, os.path.join(ROOT, 'tools', 'gui'))
os.chdir(ROOT)
import torch
from PIL import Image
from state_space_sim_real import RealStateSpaceSim
from lerobot.policies.smolvla_lew.modeling_smolvla_lew import SmolVLALewPolicy
from lerobot.policies import make_pre_post_processors

CK_REL = 'outputs/train/smolvla_lew_v8/checkpoints/030000/pretrained_model'
pol = SmolVLALewPolicy.from_pretrained(CK_REL, local_files_only=True).cuda().eval()
pre, post = make_pre_post_processors(policy_cfg=pol.config, pretrained_path=CK_REL)
print(f"① v9: {CK_REL} | {sum(x.numel() for x in pol.parameters())/1e6:.1f}M")
print(f"② 官方 pipeline: pre={[type(s).__name__ for s in pre.steps]}")
print(f"   post={[type(s).__name__ for s in post.steps]}")

seeds = [int(s) for s in sys.argv[1:] if s.isdigit()] or [104, 101, 102, 103]
# 🗣 语言指令: 必须用**数据集 tasks.parquet 的真实原串**!
#   2026-09-10 实测纠正: v8 / v8_d1 都是 "metaworld 光模块插拔" (采集脚本代码里写的是别的串,
#   但实际落盘的 parquet 不是 → 硬编码易错, 改成动态读)。
def _task_from_data():
    import pandas as pd
    for _p in ('data/smolvla_peg_v8_d1/meta/tasks.parquet', 'data/smolvla_peg_v8/meta/tasks.parquet'):
        if os.path.exists(_p):
            return str(pd.read_parquet(_p)['task'].iloc[0])
    return 'metaworld 光模块插拔'
TASK = next((s for s in sys.argv[1:] if not s.isdigit()), _task_from_data())
print(f"③ 任务指令 (task): {TASK!r}")
MAX = 400
rows = []
for seed in seeds:
    sim = RealStateSpaceSim(seed=seed, vision=False, mode='insert', log=lambda *a: None)
    env = sim.env
    env._freeze_rand_vec = False
    np.random.seed(seed * 7919 + 13)
    env.reset(seed=seed)
    env._freeze_rand_vec = True
    try:
        pol.reset()          # 清 action 队列 (SmolVLA 有状态)
    except Exception:
        pass
    _ph = env.model.site('pegHead').id
    _gl = env.model.site('goal').id
    frames, dmin, ok = [], 9.9, False
    for i in range(MAX):
        rgb = np.asarray(env.render())
        o = np.asarray(env._get_obs(), dtype=np.float32).ravel()
        d_ins = float(np.linalg.norm(env.data.site_xpos[_ph] - env.data.site_xpos[_gl]))
        dmin = min(dmin, d_ins)
        rgb128 = np.asarray(Image.fromarray(rgb).resize((128, 128), Image.LANCZOS)).transpose(2, 0, 1) / 255.0
        # 官方口径: raw 观测 → pre (内建 MEAN_STD/VISUAL=IDENTITY + device)
        batch = pre({'observation.image': torch.from_numpy(rgb128).float(),
                     'observation.state': torch.from_numpy(o).float()})
        batch['task'] = TASK     # 🗣 语言指令: 与训练同款 (缺它 → 兜底串 → 分布错) 
        with torch.no_grad():
            pred = pol.select_action(batch)
        act = np.asarray(post(pred).detach().cpu().float()).ravel()[:4]
        act[3] = -1.0 if float(np.linalg.norm(o[4:7] - o[:3])) < 0.08 else 0.0   # 夹爪辅助(4D 不触发内置二值化)
        if i < 5:
            pn = np.asarray(pred.detach().cpu().float()).ravel()[:4]
            print(f"   步{i}: norm={pn.round(3)} → act={act.round(3)} | 头-终点 {d_ins*1000:.0f}mm", flush=True)
        env.step(act.astype(float))
        frames.append(rgb)
        if d_ins < 0.006:
            ok = True
            break
        term = trunc = False
    rows.append({'seed': seed, 'steps': len(frames), 'ins_depth_min_mm': round(dmin * 1000, 1), 'success': ok})
    print(f"  seed{seed}: {len(frames)}步 · 头-终点最近 {dmin*1000:.0f}mm · success={ok}", flush=True)
    if frames:
        fd = f'/tmp/v9roll_{seed}'
        os.makedirs(fd, exist_ok=True)
        for j, fr in enumerate(frames[::2]):
            Image.fromarray(fr).save(f'{fd}/{j:05d}.png')
        subprocess.run(['ffmpeg', '-y', '-framerate', '25', '-i', f'{fd}/%05d.png', '-c:v', 'libx264',
                        '-pix_fmt', 'yuv420p', '-crf', '24', '-loglevel', 'error',
                        f'reports/v9_rollout_seed{seed}.mp4'], check=False)

n_ok = sum(1 for r in rows if r['success'])
print(f"\n=== v9 闭环 (引擎同源 env + 官方 pipeline): 成功 {n_ok}/{len(rows)} ===")
for r in rows:
    print('  ', r)
json.dump(rows, open('/tmp/v9_rollout_result.json', 'w'), ensure_ascii=False, indent=1)
print('视频: reports/v9_rollout_seed*.mp4')
