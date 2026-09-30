# -*- coding: utf-8 -*-
"""Z-MAX 状态空间工程 (engineering) —— 工程实现与平台代码的统一入口。

按 lerobot 的工程哲学组织 (2026-09-28 从 `tools/gui/node_logic.py` 整体迁移过来):

    lerobot.engineering
    ├── paths.py        路径真源 (仓库根 / 画布 JSON / 逻辑文件) —— 不许再各处上溯 __file__
    ├── registry.py     节点注册表: 语义 key ↔ 节点名关键字 ↔ 真函数 ↔ 所在文件
    ├── runtime.py      执行派发: execute_node_logic / 逐行 trace / 演示播放
    ├── sourceview.py   源码定位与编辑: 查看逻辑 / 改逻辑 / 恢复默认 (GUI 的"双击看源码"后端)
    ├── flows.py        画布/工程 JSON 读写 (package data: flows/state_space_obs.json + 备份/校验)
    ├── levels.py       L2/L3/L4/L5 档位契约 (每层"必须还能干的事" + check() 判据)
    └── nodes/          141 条节点逻辑 (library.py, 唯一真源)

分层原则 (与 Z-MAX 架构一致): **逻辑在包里, GUI 只显示**。
`tools/gui/node_logic.py` 现在只是一层兼容壳, 转手到本包; 任何新节点逻辑写进 `nodes/`,
不要写回 GUI 目录。

典型用法:
    import sys; sys.path.insert(0, "<repo>/src")
    from lerobot.engineering import execute_node_logic, match_node, flows, levels
    d, probs = flows.load_canvas()              # 读画布真源 + 校验
    levels.check()                              # L2/L3/L4/L5 功能契约自检
"""
from . import flows, levels, paths, registry, sourceview, runtime  # noqa: F401
from . import nodes  # noqa: F401  (导入即注册全部节点逻辑)
from .registry import (NODE_LOGIC, NODE_ORDER, _SOURCE_CACHE, get, home_file,  # noqa: F401
                       home_line, keys, logic_globals, match_node, register,
                       register as _reg, set_logic_globals)
from .registry import stats as registry_stats  # noqa: F401
from .runtime import _demo_node_output, _trace_exec, execute_node_logic  # noqa: F401
from .sourceview import (_probe_data_root, explain_node, get_external_source,  # noqa: F401
                         get_node_external_symbol, get_node_location, get_node_source,
                         list_logic, reload_node_logic, restore_default, save_node_logic)

# 141 条节点逻辑本体也挂到包命名空间 (老的 `node_logic.node_intact` 之类调用直接可用)
from .nodes import library as _library  # noqa: E402

for _n in dir(_library):
    if not _n.startswith("__"):
        globals().setdefault(_n, getattr(_library, _n))
del _n
