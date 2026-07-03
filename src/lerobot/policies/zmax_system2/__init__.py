"""
Z-MAX Phase 4: System 2 — 全系统 (L4级大脑)
Z·M·A·X 全域: 云端智能体 + 多产线调度 + 任务拆解

架构: Phase1-3 子系统编排 + 任务规划器 + 多工位协调
核心: 感知全局 → 拆解任务 → 调度Sys-11/Sys-12 → 全域闭环

依赖: zmax_sys1, zmax_sys11, zmax_sys12
"""

from .configuration_zmax_system2 import ZmaxSystem2Config
from .modeling_zmax_system2 import ZmaxSystem2Policy

__all__ = ["ZmaxSystem2Config", "ZmaxSystem2Policy"]
