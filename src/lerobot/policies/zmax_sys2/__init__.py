"""
Z-MAX Sys2 · 云端智能体 (web 分支 - 4090 实现)

Sys2 = 云端大模型推理层，运行在 4090 上：
- VTLA: Vision-Touch-Language-Action (触觉VLA, ~450M)
- GR00T: NVIDIA GR00T N1.7 通用机器人模型 (~7B)
- ACT: Action Chunking Transformer fallback (~52M)

通过 gRPC/HTTP API 暴露给 Sys1 (4060) 调用。
Sys1 ACT 模板可通过网络切换到 Sys2 的大模型推理。
"""

from .configuration_zmax_sys2 import ZmaxSys2Config, Sys2ModelType, SubSystemMode
from .modeling_zmax_sys2 import (
    ZmaxSys2Policy,
    VTLAInferenceEngine,
    GR00TInferenceEngine,
    ACTInferenceEngine,
    SimFeedback,
    Sys2InferenceResult,
)

__all__ = [
    "ZmaxSys2Config",
    "ZmaxSys2Policy",
    "Sys2ModelType",
    "SubSystemMode",
    "VTLAInferenceEngine",
    "GR00TInferenceEngine",
    "ACTInferenceEngine",
    "SimFeedback",
    "Sys2InferenceResult",
]
