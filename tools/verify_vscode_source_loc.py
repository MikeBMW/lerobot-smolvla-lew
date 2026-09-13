# -*- coding: utf-8 -*-
"""验证「右键 → VSCode 定位」是否跳到节点声明的真实实现 (老倪: VEH.5.022 右键还开 GUI 原文件)。

节点源码定位规则 (v5.5.44): ① 节点 params.source (+ params.source_symbol 动态搜行号) 优先
② 没写 source 才走 node_logic 的 _EXTERNAL_LOC 映射 ③ 都没有才退回 node_logic.py (= GUI 文件)。

两段验证:
  ① node_logic 映射: match_node / get_node_location → 必须是 src/lerobot/policies/intact/service.py
  ② 真方法 open_in_vscode: 打桩 Popen/which 捕获命令 → 必须含 "-g <policy 路径>:<行>"
用法: QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_vscode_source_loc.py [节点名...]
"""
import json
import os
import shutil
import subprocess
import sys

ROOT = "/home/ubuntu/lerobot-smolvla-lew"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)

import node_logic                                                       # noqa: E402
from PyQt5.QtWidgets import QApplication                                # noqa: E402

app = QApplication(sys.argv)
import simulink_module as sm                                            # noqa: E402

FLOW = json.load(open(os.path.join(ROOT, "flows", "state_space_obs.json"), encoding="utf-8"))
NODES = {n["id"]: n for n in FLOW["nodes"]}
if len(sys.argv) > 1:            # 传节点名 → 任意节点都能查
    TARGETS = [(nid, str(NODES[nid].get("name", ""))) for nid in sys.argv[1:]]
else:
    TARGETS = [("ssintact_dec", "🎯 INTACT 意图解码器 (L4 → L3 条件)"),
               ("ssintact", "🎯 INTACT 策略 (L4: metaworld → 零搜索 意图→动作)")]

print("① node_logic 映射 (get_node_location)")
ok1 = True
for nid, name in TARGETS:
    key = node_logic.match_node(name)
    path, line, _ = node_logic.get_node_location(key) if key else (None, None, False)
    good = bool(path) and "src/lerobot/policies/intact" in path
    ok1 &= good
    print(f"  {'✅' if good else '❌'} {name[:22]:<24} key={key} → {path}:{line}")

print("\n② 真方法 open_in_vscode (打桩 Popen/which)")
CAP = {}


class _FakePopen:
    def __init__(self, cmd, *a, **kw):
        CAP.setdefault("cmds", []).append(cmd)


shutil_which = shutil.which
subprocess_popen = subprocess.Popen
shutil.which = lambda x, *a, **kw: "/usr/bin/code" if x == "code" else shutil_which(x, *a, **kw)
subprocess.Popen = _FakePopen
try:
    m = sm.SimulinkModule()
    m.resize(1600, 1000)
    ok2 = True
    for nid, name in TARGETS:
        CAP.pop("cmds", None)
        node = NODES[nid]
        m.open_in_vscode(node)
        cmds = CAP.get("cmds", [])
        got = [c for c in cmds if isinstance(c, (list, tuple)) and "-g" in c]
        loc = got[0][got[0].index("-g") + 1] if got else "(无)"
        good = "src/lerobot/policies/intact/service.py" in str(loc) and "node_logic.py" not in str(loc)
        ok2 &= good
        print(f"  {'✅' if good else '❌'} {name[:22]:<24} code -g {loc}")
finally:
    subprocess.Popen = subprocess_popen
    shutil.which = shutil_which

print("\n判据: ① 映射指向 policies/intact ② VSCode 命令定位同一文件且不含 node_logic.py")
print("verdict:", "PASS" if (ok1 and ok2) else "FAIL")
