# -*- coding: utf-8 -*-
"""🧠 INTACT 节点契约 (intact_node.contracts) — 依据 zju3dv/INTACT-JEPA 源码定义的硬边界。

来源 (读源码, 非转述):
  · jepa.py::JEPA.get_action(info, horizon)  ← 部署主入口 (零搜索)
  · jepa.py::JEPA._encode_goal(info)         ← goal_* 前缀键改写规则
  · jepa.py::JEPA._coerce_action_history     ← 动作历史必须 raw 零初始化 (normalizer 之前)
  · module.py::IntentActionActor             ← 四槽语法 [z, m_t, z⊙m_t, A(a_{t-1})]

本文件只放**契约**(数据类/常量/信息字典构造), 不放模型实现 —— 模型在 model_adapter.py。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

# ── 官方训练配置 (config/train/intact_goal.yaml) ──
IMG_SIZE = 224            # 观测/目标帧边长
HISTORY_SIZE = 3          # 潜空间上下文长度 (predictor pos_embedding)
NUM_FRAMES = 8            # 训练片段长度
EMBED_DIM = 192           # 潜空间宽度
INTENT_MODES = ("goal_displacement", "waypoint")

# ── 四槽/五槽语法 (module.py::IntentActionActor.VALID_FEATURE_LAYOUTS) ──
FEATURE_LAYOUTS = {"four_slot": "[z, m_t, z*m_t, A(a_{t-1})]",
                   "five_slot": "[z, m_t, 0, z*m_t, A(a_{t-1})]"}
DEFAULT_FEATURE_LAYOUT = "four_slot"

PolicyName = Literal["direct", "guarded_a"]
GoalKind = Literal["frame", "waypoint"]


@dataclass
class IntactInput:
    """节点每步的输入 (由数据源层提供)。pixels 必须含至少 HISTORY_SIZE 帧。"""
    pixels: np.ndarray               # [T, C, H, W] float32 in [0,1] (或 uint8, adapter 归一化)
    goal: np.ndarray | None = None    # [C, H, W] 目标帧 (frame 模式)
    waypoint: np.ndarray | None = None  # [D_w] 目标坐标 (waypoint 模式)
    action_history: np.ndarray | None = None  # [T, D] **raw 零初始化**, 之后为真实下发动作
    proprio: np.ndarray | None = None  # [P] 本体状态 (透传 encode)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class IntactOutput:
    """节点每步的输出: 零搜索得到的 action chunk + 诊断 (可审计)。"""
    chunk: np.ndarray                # [H, D] 待下发动作块
    horizon: int
    action_dim: int
    diagnostics: dict[str, float] = field(default_factory=dict)
    policy: str = "direct"
    trained: bool = False            # ⚠️ 权重缺失时必须为 False (诚实标注)
    source: str = ""                 # 数据源名 (溯源)


def build_info_dict(inp: IntactInput, intent_mode: str = "goal_displacement",
                    device: str = "cpu"):
    """把节点输入转成 INTACT 官方 `info` 字典 (逐键与 jepa.py 对齐)。

    · pixels → [1, T, C, H, W]
    · goal   → [1, C, H, W]      (waypoint 模式放 goal_waypoint, 由 _encode_goal 改写)
    · action → [1, T, D]  (缺省 = raw 零, 与 reset 语义一致)
    """
    import torch

    px = np.asarray(inp.pixels, dtype=np.float32)
    if px.ndim == 4:                      # [T,C,H,W]
        px = px[None]
    if px.dtype != np.float32:
        px = px.astype(np.float32)
    if px.max() > 1.5:                    # uint8 域 → [0,1]
        px = px / 255.0
    info: dict[str, Any] = {"pixels": torch.from_numpy(px).to(device)}

    if intent_mode == "waypoint":
        if inp.waypoint is None:
            raise ValueError("waypoint 模式需要 waypoint")
        info["goal_waypoint"] = torch.from_numpy(
            np.asarray(inp.waypoint, dtype=np.float32)).reshape(1, -1).to(device)
    else:
        if inp.goal is None:
            raise ValueError("goal_displacement 模式需要 goal 帧")
        g = np.asarray(inp.goal, dtype=np.float32)
        if g.ndim == 3:
            g = g[None]
        if g.max() > 1.5:
            g = g / 255.0
        # ★ goal 必须是 5 维 [B,T,C,H,W]: 模型内部 goal["pixels"]=goal 直接进 ViT 编码器,
        #   编码器按 (b t) c h w 展平 → 传 4 维会炸
        #   "batch_size, num_channels, height, width = pixel_values.shape (expected 4, got 3)"
        if g.ndim == 4:
            g = g[:, None]
        info["goal"] = torch.from_numpy(g).to(device)

    if inp.action_history is not None:
        a = np.asarray(inp.action_history, dtype=np.float32)
        if a.ndim == 2:
            a = a[None]
        info["action"] = torch.from_numpy(a).to(device)
    if inp.proprio is not None:
        info["proprio"] = torch.from_numpy(
            np.asarray(inp.proprio, dtype=np.float32)).reshape(1, -1).to(device)
    for k, v in inp.extra.items():
        if isinstance(v, np.ndarray):
            info[k] = torch.from_numpy(v).to(device)
        else:
            info[k] = v
    return info


def zero_action_history(seq_len: int, action_dim: int) -> np.ndarray:
    """reset 语义: 动作历史必须是 **raw 零** (jepa.py::_coerce_action_history 硬约束)。"""
    return np.zeros((int(seq_len), int(action_dim)), dtype=np.float32)
