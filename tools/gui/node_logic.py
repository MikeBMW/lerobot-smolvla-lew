# -*- coding: utf-8 -*-
"""⚠️ 兼容壳 (compat shim) —— 节点逻辑已整体迁到 `src/lerobot/engineering/` (2026-09-28)。

本文件**不再包含任何节点逻辑**, 只把包命名空间转发给老调用方, 保证
`import node_logic` / `from node_logic import execute_node_logic, match_node, NODE_LOGIC ...`
这些历史写法继续可用 (控制台 studio.py / simulink_module.py / 各 tools 脚本)。

    · 逻辑真源   : src/lerobot/engineering/nodes/library.py   (141 条节点逻辑, 147 个注册 key)
    · 注册表     : src/lerobot/engineering/registry.py        (key ↔ 节点名关键字 ↔ 函数 ↔ 文件)
    · 执行派发   : src/lerobot/engineering/runtime.py         (execute_node_logic / trace / 演示)
    · 源码定位   : src/lerobot/engineering/sourceview.py      (查看/改逻辑/恢复默认)
    · 画布 JSON  : src/lerobot/engineering/flows/state_space_obs.json   (+ 备份/校验 flows.py)
    · 档位契约   : src/lerobot/engineering/levels.py          (L2/L3/L4/L5 必须还能干的事 + check())

新增或修改节点逻辑: 请改包里那份 (同一处), **不要写回 GUI 目录**。
新代码请直接:  sys.path.insert(0, "<repo>/src");  from lerobot.engineering import execute_node_logic
"""
import os
import sys

_SRC = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))
if _SRC not in sys.path:
    sys.path.append(_SRC)        # 追加而非插最前: 不改动 tools/gui 既有的模块解析顺序

import lerobot.engineering as _E  # noqa: E402

for _n in dir(_E):
    if not _n.startswith("__"):
        globals()[_n] = getattr(_E, _n)

LOGIC_HOME = _E.paths.LOGIC_FILE          # 逻辑真源路径 (提示/VSCode 打开用)
CANVAS_JSON = _E.paths.canvas_json()      # 画布 JSON 真源
__all__ = [n for n in dir(_E) if not n.startswith("_")]
