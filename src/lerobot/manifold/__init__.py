# -*- coding: utf-8 -*-
"""manifold 层 — 🧮 流形层: 接触流形 / 性能流形 (回路外几何分析元层)

与 calibration (标定层) 同级: src/lerobot/manifold/manifold_layer.py
"""
from .manifold_layer import ContactManifold, PerformanceManifold

__all__ = ["ContactManifold", "PerformanceManifold"]
