# Copyright 2026 Z-MAX. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
"""🧠 INTACT 策略包 (L4 层) — zju3dv/INTACT-JEPA 的 lerobot 化封装。

迁移记录 (老倪 2026-09-13): 原 `lerobot.manifold.intact_node/` 的实现**整体迁入**
本包 (runtime/ 子包, 实现一字未改, 仅移动 + 更新包内相对导入)。旧路径由
`lerobot/manifold/intact_node/__init__.py` 兼容转发, 现有工具/引擎/桥零改动。

层次:
  · runtime/           真算法 (跨 venv 子进程桥, 权重跑在 INTACT-JEPA 冻结运行时)
  · configuration_intact.py  lerobot 配置 (IntactConfig, 注册名 "intact")
  · modeling_intact.py       lerobot 策略外壳 (IntactPolicy: select_action / predict_intent)
  · decoder.py               L4 → L3 意图解码器 (u_ff 先验 + 流形条件; 未标定诚实拒绝)

连线 (docs/design/zmax_l4_intact_policy.md):
  metaworld 数据源 → IntactPolicy → IntactIntentDecoder → L3 (SmolVLA-Lew VLM+DiT)
"""
from . import runtime as runtime
from .configuration_intact import IntactConfig
from .decoder import DecodedIntent, IntactIntentDecoder
from .modeling_intact import IntactPolicy
from .runtime import MetaWorldSource, registry

__all__ = ["IntactConfig", "IntactPolicy", "IntactIntentDecoder", "DecodedIntent",
           "MetaWorldSource", "registry", "runtime"]
