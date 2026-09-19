#!/usr/bin/env python3
"""vpc_l2_muscle.py — F26: L2 肌肉记忆技能 → ROS2 转发链 (dry-run 校验字节)"""
import glob, json, os, subprocess, sys
R = '/home/ubuntu/lerobot-smolvla-lew'
sk = sorted(glob.glob(os.path.join(R, 'data/skills/l2_muscle/*.json')))
br = os.path.join(R, 'tools/l2_ros2_bridge.py')
assert sk, 'L2 技能库为空'
assert os.path.isfile(br), '缺 l2_ros2_bridge.py'
n = 0
for f in sk:
    d = json.load(open(f, encoding='utf-8'))
    assert d.get('layer') == 'L2' and d['steps'], f
    n += 1
out = subprocess.run([os.path.join(R, 'gui-venv311/bin/python'), br, '--skill',
                      os.path.relpath(sk[0], R), '--dry-run'],
                     capture_output=True, text=True, cwd=R, timeout=180).stdout
assert 'ros2 service call' in out, out[-200:]
print('OK L2技能 %d 个 · 首技能 dry-run 下发字节正常: %s' % (n, sk[0].split('/')[-1]))
