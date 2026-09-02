# -*- coding: utf-8 -*-
"""calibration — 🧮 标定层 (引力/斥力二分超参数 + 平衡点, Drifting Models 思想)

与 datasets/、policies/ 同级的独立模块。回路外元层: 不参与引擎推理,
不改变现有拓扑/流程/架构。入口: CalibrationLayer。
"""
from .calibration_layer import (CalibrationLayer, ATTRACTION_CALIB, REPULSION_CALIB,
                                STAGES, EQ_BAND)

__all__ = ["CalibrationLayer", "ATTRACTION_CALIB", "REPULSION_CALIB", "STAGES", "EQ_BAND"]
