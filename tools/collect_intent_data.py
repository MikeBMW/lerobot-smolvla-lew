#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阶段2 数据: 采集"二态意图 → 专家动作"对 (引擎真跑)

每条样本:
  z7    : 几何潜空间 R7 (夹持后 x→光模块头; 与 L4 predictor 同构口径)
  m_loc : 局部意图 (接触流形切向, 指向阶段目标)
  m_goal: 目标意图 (性能流形负梯度, 指向 η=1)
  a_exp : 专家动作 (引擎六层控制器本帧实际下发的 act[:3], 即"专家演示")
  stage : 阶段名 (用于分组/一致性约束)
  mag   : 意图幅值 (下游按时长标定)

用法: MUJOCO_GL=egl gui-venv311/bin/python tools/collect_intent_data.py [seed ...]
输出: data/intent_pairs_v1.npz
"""
import os
import sys

os.environ.setdefault('MUJOCO_GL', 'egl')
os.environ.setdefault('DISPLAY', ':0')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, 'src'), os.path.join(ROOT, 'tools'), os.path.join(ROOT, 'tools', 'gui')):
    sys.path.insert(0, _p)
os.chdir(ROOT)
for k in ['SS_MUSCLE', 'SS_MOTOR_HUB', 'SS_INTENT', 'SS_TDEC', 'SS_OBSERVE', 'SS_SHADOW', 'SS_L3']:
    os.environ[k] = '0'

import numpy as np  # noqa: E402

from state_space_sim_real import RealStateSpaceSim  # noqa: E402


def _stages(tr):
    return [str(x).replace('阶段 ', '').split('·')[0].strip() for x in tr['stage']]


def collect(seeds, out_path):
    Z, ML, MG, A, STG, MAG = [], [], [], [], [], []
    for sd in seeds:
        sim = RealStateSpaceSim(seed=sd, vision=False, mode='insert', log=lambda *a: None)
        tr = sim.run(max_steps=1200)
        if not bool(tr['done'][-1]):
            print(f'  seed{sd}: 未完成, 跳过 (只采成功轨迹 = 专家演示)')
            continue
        st = _stages(tr)
        z7 = np.asarray(tr['z7_vec'], float)
        ml = np.asarray(tr['m_local'], float)
        mg = np.asarray(tr['m_goal'], float)
        u = np.asarray(tr['u_exec_vec'], float) if 'u_exec_vec' in tr else None
        n = min(len(z7), len(ml), len(mg), len(st), len(u) if u is not None else 10 ** 9)
        if n < 10:
            print(f'  seed{sd}: 数据不足 (n={n}), 跳过')
            continue
        Z.append(z7[:n]); ML.append(ml[:n]); MG.append(mg[:n])
        A.append(u[:n, :3]); STG += st[:n]; MAG.append(np.linalg.norm(ml[:n], axis=1))
        print(f'  seed{sd}: ✔ {n} 帧 (完成)')
    if not Z:
        print('❌ 无数据')
        return
    d = dict(z=np.concatenate(Z), m_local=np.concatenate(ML), m_goal=np.concatenate(MG),
             a_expert=np.concatenate(A), stage=np.array(STG, dtype=object),
             m_local_mag=np.concatenate(MAG))
    np.savez_compressed(out_path, **d)
    print(f'\n✅ 保存 {out_path}')
    _n, _zs, _ms, _as = len(d['z']), d['z'].shape, d['m_local'].shape, d['a_expert'].shape
    print(f'   样本 {_n} · z{_zs} · m_local{_ms} · a{_as}')
    from collections import Counter
    print(f'   阶段分布: {dict(Counter(STG))}')


def z_sh(d):
    return d['z'].shape


def m_sh(d):
    return d['m_local'].shape


if __name__ == '__main__':
    seeds = [int(a) for a in sys.argv[1:] if a.isdigit()] or [104, 7, 9, 0, 6]
    print(f'=== 采集二态意图→专家动作 (seeds={seeds}) ===')
    os.makedirs('data', exist_ok=True)
    collect(seeds, os.path.join('data', 'intent_pairs_v1.npz'))
