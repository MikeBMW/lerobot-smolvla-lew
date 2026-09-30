"""
Z-MAX Phase 1: System 1 — 基础功能
M(多模态) + A(Action): 基于VTLA的端到端精细插拔

架构: SmolVLM-SigLIP (视觉编码器) + Expert MLP + DiT-B Action Head
输入: 图像(RGB) + 触觉(力) + 语言指令 + 本体感知
输出: 机械臂末端位姿 + 夹爪开合

依赖: smolvla_lew (纯动作模式)
"""

from .configuration_zmax_sys1 import ZmaxSys1Config
from .modeling_zmax_sys1 import ZmaxSys1Policy

__all__ = ["ZmaxSys1Config", "ZmaxSys1Policy"]
