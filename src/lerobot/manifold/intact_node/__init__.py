# -*- coding: utf-8 -*-
"""🧠 INTACT 节点 (L4 层) — zju3dv/INTACT-JEPA 能力封装。

设计: docs/design/zmax_intact_node.md
对外: IntactNode.set_data_source / set_goal / attach_robot / step
"""
from .contracts import (DEFAULT_FEATURE_LAYOUT, FEATURE_LAYOUTS, HISTORY_SIZE, IMG_SIZE,
                        IntactInput, IntactOutput, build_info_dict, zero_action_history)
from .action_adapter import IntactActionAdapter
from .data_source import (L4EpisodeSource, OfficialIntactSource, download_intact_dataset,
                          registry)
from .model_adapter import IntactRuntime
from .node import NODE_LAYER, NODE_NAME, IntactNode
from .robot_io import HardwareRobotIO, RobotIO, SimRobotIO

__all__ = [
    "IntactNode", "NODE_NAME", "NODE_LAYER",
    "IntactRuntime", "RobotIO", "SimRobotIO", "HardwareRobotIO",
    "registry", "L4EpisodeSource", "OfficialIntactSource", "download_intact_dataset",
    "IntactInput", "IntactOutput", "build_info_dict", "zero_action_history",
    "HISTORY_SIZE", "IMG_SIZE", "FEATURE_LAYOUTS", "DEFAULT_FEATURE_LAYOUT",
    "IntactActionAdapter",
]
