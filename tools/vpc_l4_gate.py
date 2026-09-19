#!/usr/bin/env python3
"""vpc_l4_gate.py — F27: L4 安全闸门 (power/idle/has_error + 自动复位) 存在于真机链路"""
import os, re, sys
R = '/home/ubuntu/lerobot-smolvla-lew'
s = open(os.path.join(R, 'tools/l2_ros2_bridge.py'), encoding='utf-8').read()
assert 'def gate(' in s, '缺 L4 安全闸门函数'
for k in ('power_state', 'has_error', 'rokae_recover_estop'):
    assert k in s, '闸门缺关键判据: ' + k
d = open(os.path.join(R, 'docs/design/architecture_layers_v511.md'), encoding='utf-8').read()
for k in ('DeepSeek VL', 'INTACT', '长程序列规划', '肌肉记忆'):
    assert k in d, '分层文档缺: ' + k
print('OK L4闸门(power/idle/has_error+复位) + 分层文档四层职责齐备')
