# -*- coding: utf-8 -*-
"""状态空间工程的节点逻辑 (nodes) —— 每个节点背后的真实代码都在这里。

导入本包即完成注册 (library 里的 `_reg(...)` 会把 141 条语义 key 灌进 `..registry`)。
GUI / 脚本 / web agent 想执行节点, 一律走 `lerobot.engineering.runtime.execute_node_logic`,
不要再在各处 import GUI 文件。
"""
from . import library  # noqa: F401  (导入即注册)

__all__ = ["library"]
