# -*- coding: utf-8 -*-
"""🧠 INTACT 节点 (L4 层) — 【已迁移】兼容转发层。

2026-09-13 老倪: "将 L4 节点的 INTACT 代码迁移到 src/lerobot 的 policies 文件夹"。
实现已整体迁至 **`lerobot.policies.intact`** (lint 见 docs/design/zmax_l4_intact_policy.md):
  · 真算法      → lerobot/policies/intact/runtime/   (桥/契约/数据源/机器人IO/自检)
  · lerobot 策略 → lerobot/policies/intact/modeling_intact.py  (IntactPolicy)
  · L4→L3 解码   → lerobot/policies/intact/decoder.py           (IntactIntentDecoder)
  · metaworld 源 → lerobot/policies/intact/runtime/metaworld_source.py

本文件只做**转发**, 不改行为 —— 让既有引用 (tools/intact_*.py · 引擎 · 桥 · cron) 零改动继续工作。
新代码请直接 `from lerobot.policies.intact import IntactNode, IntactPolicy, ...`。
"""
from __future__ import annotations

from lerobot.policies.intact.runtime import (  # noqa: F401
    DEFAULT_FEATURE_LAYOUT,
    FEATURE_LAYOUTS,
    HISTORY_SIZE,
    IMG_SIZE,
    NODE_LAYER,
    NODE_NAME,
    HardwareRobotIO,
    IntactActionAdapter,
    IntactInput,
    IntactNode,
    IntactOutput,
    IntactRuntime,
    L4EpisodeSource,
    MetaWorldSource,
    OfficialIntactSource,
    RobotIO,
    SimRobotIO,
    build_info_dict,
    download_intact_dataset,
    registry,
    zero_action_history,
)

__all__ = [
    "IntactNode", "NODE_NAME", "NODE_LAYER",
    "IntactRuntime", "RobotIO", "SimRobotIO", "HardwareRobotIO",
    "registry", "L4EpisodeSource", "OfficialIntactSource", "MetaWorldSource",
    "download_intact_dataset",
    "IntactInput", "IntactOutput", "build_info_dict", "zero_action_history",
    "HISTORY_SIZE", "IMG_SIZE", "FEATURE_LAYOUTS", "DEFAULT_FEATURE_LAYOUT",
    "IntactActionAdapter",
]
