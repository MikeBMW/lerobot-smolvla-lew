#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""id 冲突机制的直接测量 (不靠概率猜)

测两件事, 旧随机实现 vs 新自增实现, 各 N 次真加载:
  ① 节点 id 重复数   ② 连线 id 重复数 (连线重复 ⇒ `del_link` 撤销会一次删掉多条)
判据: 旧实现出现重复 ⇒ 修复有实证价值; 都不出现 ⇒ 只能算"保险", 如实写"未复现"
用法: python verify_genid_collision_repro.py [N=10]
"""
import collections
import json
import os
import random
import sys
import time

sys.path.insert(0, "/home/ubuntu/zmax/tools/gui")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5 import QtWidgets                                                      # noqa: E402

app = QtWidgets.QApplication(sys.argv)
import simulink_module as SM                                                     # noqa: E402

FLOW = "/home/ubuntu/zmax/flows/state_space_obs.json"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 10
RND = "abcdefghijklmnopqrstuvwxyz0123456789"
spec = json.load(open(FLOW, encoding="utf-8"))


def link_id_old():
    return "l%d%s" % (int(time.time() * 1000), ''.join(random.choice(RND) for _ in range(2)))


def run(tag):
    dupn = dupl = 0
    worst_n = worst_l = 0
    for _ in range(N):
        m = SM.SimulinkModule()
        m.load_flow_file(FLOW, confirm=False)
        app.processEvents()
        cn = collections.Counter(n["id"] for n in m.nodes)
        cl = collections.Counter(l["id"] for l in m.links)
        worst_n += -(-sum(v - 1 for v in cn.values() if v > 1) // 1) and 0
        dn = sum(v - 1 for v in cn.values() if v > 1)
        dl = sum(v - 1 for v in cl.values() if v > 1)
        if dn:
            dupn += 1
        if dl:
            dupl += 1
        worst_n = max(worst_n, dn)
        worst_l = max(worst_l, dl)
    print("%-14s %d 次加载: 出现重复节点 id 的 %d 次 (最多 %d 个) · 重复连线 id 的 %d 次 (最多 %d 条)"
          % (tag, N, dupn, worst_n, dupl, worst_l))
    return dupn, dupl


new = run("新(自增)")
SM.link_id = link_id_old
SM.gen_id = lambda: "n%d%s" % (int(time.time() * 1000),
                               ''.join(random.choice(RND) for _ in range(3)))
old = run("旧(纯随机)")
print("\n结论: 旧实现重复 → 节点 %d 次 / 连线 %d 次 ; 新实现 节点 %d / 连线 %d"
      % (old[0], old[1], new[0], new[1]))
