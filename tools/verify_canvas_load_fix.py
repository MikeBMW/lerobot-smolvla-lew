#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_canvas_load_fix.py — 复现并验证「状态空间画布加载失败」修复

判据:
  ① 现状根因复现: 用 mac-hw 检出当仓库根 → 老口径路径不存在 (flows 缺失)
  ② 新口径 _flows_path 在"仓库根=mac-hw 检出"时 → 自动回落到 main worktree 并命中真文件
  ③ 画布 JSON 真加载: 节点/连线数 + 关键节点 (n_dsvl / n_web_agent) 在位
  ④ environ ZMAX_FLOWS_DIR 覆盖生效
"""
import json
import os
import sys

sys.path.insert(0, "/home/ubuntu/zmax_rel/tools/gui")
import simulink_module as M  # noqa: E402

MAC = "/home/ubuntu/lerobot-smolvla-lew"
MAIN = "/home/ubuntu/zmax_rel"
ok = []


def chk(n, c, d=""):
    ok.append(bool(c))
    print("  %s %s%s" % ("✅" if c else "❌", n, (" — " + d) if d else ""))


print("① 根因复现 (老口径 = 仓库根/flows/state_space_obs.json)")
old_mac = os.path.join(MAC, "flows", "state_space_obs.json")
old_main = os.path.join(MAIN, "flows", "state_space_obs.json")
chk("mac-hw 检出没有该文件 (这就是加载失败的原因)", not os.path.isfile(old_mac), old_mac)
chk("main worktree 有该文件", os.path.isfile(old_main), "")

print("② 新口径 _flows_path 在『仓库根=mac-hw 检出』时的回落")
orig = M._repo_root_path
M._repo_root_path = lambda: MAC          # 模拟: 从 mac-hw 检出启动控制台
p = M._flows_path("state_space_obs.json")
chk("不改环境变量也能命中", os.path.isfile(p), p)
M._repo_root_path = orig

print("③ 画布真加载 (节点/连线/关键节点)")
d = json.load(open(p, encoding="utf-8"))
ids = [n["id"] for n in d["nodes"]]
chk("节点数 > 80", len(d["nodes"]) > 80, "%d 节点 / %d 连线" % (len(d["nodes"]), len(d["links"])))
chk("DeepSeek 节点在位", "n_dsvl" in ids)
chk("L5 Web 智能体桥节点在位", "n_web_agent" in ids)
chk("库分组也能读到同一文件", M._flows_path("state_space_obs.json") == p)

print("④ ZMAX_FLOWS_DIR 覆盖")
os.environ["ZMAX_FLOWS_DIR"] = os.path.join(MAIN, "flows")
chk("环境变量优先", M._flows_path("state_space_obs.json") == old_main, os.environ["ZMAX_FLOWS_DIR"])
del os.environ["ZMAX_FLOWS_DIR"]

print("\n判据通过: %d/%d" % (sum(ok), len(ok)))
sys.exit(0 if all(ok) else 3)
