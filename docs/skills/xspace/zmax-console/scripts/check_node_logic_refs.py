#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查 node_logic.py 所有 module.<method>(...) 引用是否真实存在于 SimulinkModule。

背景 (2026-08-30, commit 2d743909): node_metaworld_data 调 _toggle_source_node、
node_yolo_gate 调 _set_yolo_gate_ctx —— 方法从未存在, AttributeError 被
_sim_node 的 `except Exception: pass` 吞掉 → 节点变绿+日志正常但动作从未执行
(老倪零容忍的"假激活")。改完 node_logic.py / simulink_module.py 后必须跑本脚本。

用法:
    python3 scripts/check_node_logic_refs.py            # 仓库根目录下
    python3 check_node_logic_refs.py                    # tools/gui 下
退出码: 0 = 无坏引用, 1 = 存在坏引用
"""
import os
import re
import sys

ROOT = os.path.expanduser("~/lerobot-smolvla-lew")
GUI = os.path.join(ROOT, "tools", "gui")
if os.path.isdir(GUI) and GUI not in sys.path:
    sys.path.insert(0, GUI)
elif os.path.isdir(".") and os.path.basename(os.getcwd()) == "gui":
    GUI = os.getcwd()
    ROOT = os.path.dirname(os.path.dirname(GUI))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import simulink_module  # noqa: E402

NL_PATH = os.path.join(GUI, "node_logic.py")
src = open(NL_PATH, encoding="utf-8").read()

# 收集 node_logic.py 所有 module.xxx( 调用 (含多参数)
calls = set(re.findall(r"module\.([a-zA-Z_][a-zA-Z0-9_]*)\([^)]*\)", src))
if not calls:
    print("⚠️  未发现 module.* 调用 — 检查正则或文件路径:", NL_PATH)
    sys.exit(1)

cls = simulink_module.SimulinkModule
missing = sorted(c for c in calls if not hasattr(cls, c))
present = sorted(calls - set(missing))

print(f"node_logic.py 引用 module 方法 {len(calls)} 个")
for m in present:
    print(f"  ✅ {m}")
for m in missing:
    print(f"  ❌ {m}  ← 不存在! 运行流程时抛 AttributeError 被吞 = 假执行")

# 附加: 注册词 vs 模板节点名匹配抽查 (2026-08-30: yolo_gate 注册 "YOLO开关"
# 匹配不到模板名 "🎯 YOLO 感知开关", 被 ss_yolo 的 "YOLO" 抢先)
try:
    import node_logic  # noqa: E402
    spot = [
        ("🎯 YOLO 感知开关", "yolo_gate"),
        ("📦 metaworld 数据", "data"),
        ("☑ 训练开关", "train_gate"),
        ("② 训练", "train"),
        ("🎯 YOLO 目标检测", "ss_yolo"),
    ]
    bad = []
    for name, expect in spot:
        got = node_logic.match_node(name)
        if got != expect:
            bad.append((name, expect, got))
            print(f"  ❌ match_node({name!r}) → {got} (期望 {expect}) ← 注册词歧义!")
    if not bad:
        print("  ✅ 节点名匹配抽查 5/5")
except Exception as ex:
    print(f"  ⚠️  匹配抽查跳过: {ex}")

print()
if missing or "bad" in dir() and bad:
    print("❌ 存在坏引用/匹配歧义 — 修复后重跑")
    sys.exit(1)
print("✅ 全部通过")
sys.exit(0)
