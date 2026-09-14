#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模型接管鲁棒性评估 — 多 seed (引擎真物理, SS_L3=1 模型真接管)

用法:
  cd repo && MUJOCO_GL=egl gui-venv311/bin/python tools/eval_takeover.py [seed ...]
  (不传 seed 默认 104 7 9 0 6; 可用 SS_L3_CK / MODE / MAX_STEPS 环境变量覆盖)

对照基线:
  解析链 (SS_L3=0, mode=insert): 3/5  (seed7/9/104 成功, 11/12 失败 → 仿真物理边界)
  模型接管 (SS_L3=1)           : 本脚本测的

性能: 模型只加载一次 (类级缓存), 比早期版本(每 seed 重载)快数倍。
"""
import os
import sys

os.environ.setdefault('MUJOCO_GL', 'egl')
os.environ.setdefault('DISPLAY', ':0')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, 'src'), os.path.join(ROOT, 'tools'), os.path.join(ROOT, 'tools', 'gui')):
    sys.path.insert(0, _p)
os.chdir(ROOT)

MODE = os.environ.get('MODE', 'insert')
MAX_STEPS = int(os.environ.get('MAX_STEPS', '1500'))
CK = os.environ.get('SS_L3_CK', 'outputs/train/smolvla_lew_v10_1h/checkpoints/004000/pretrained_model')

for k in ['SS_MUSCLE', 'SS_MOTOR_HUB', 'SS_INTENT', 'SS_TDEC', 'SS_OBSERVE', 'SS_SHADOW']:
    os.environ[k] = '0'
os.environ['SS_L3'] = '1'
os.environ['SS_L3_CK'] = CK
os.environ.setdefault('SS_L3_EVERY', '2')

from state_space_sim_real import RealStateSpaceSim  # noqa: E402


def _warm_model_cache():
    """预热: 让第一个 sim 加载模型后, 后续 sim 复用 (把 _l3_pol 提到类级)。"""
    try:
        from state_space_sim_real import RealStateSpaceSim as _R
        _R._L3_SHARED = {}          # 类级共享槽
    except Exception:
        pass


def main():
    seeds = [int(a) for a in sys.argv[1:] if a.isdigit()] or [104, 7, 9, 0, 6]
    print(f'=== 模型接管鲁棒性评估 (SS_L3=1) ===')
    print(f'    mode={MODE} · ck={CK} · max_steps={MAX_STEPS}')
    print(f'    解析链基线: 3/5 (seed7/9/104 OK)\n')
    ok = 0
    for sd in seeds:
        sim = RealStateSpaceSim(seed=sd, vision=False, mode=MODE, log=lambda *a: None)
        tr = sim.run(max_steps=MAX_STEPS)
        d = bool(tr['done'][-1])
        ok += d
        print(f'  seed{sd:>4}: {len(tr["t"]):>4}步 {"OK  " if d else "FAIL"}', flush=True)
    print(f'\n  → 模型接管成功 {ok}/{len(seeds)}')


if __name__ == '__main__':
    main()
