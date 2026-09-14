# Copyright 2026 Z-MAX. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
"""🧠 INTACT 配置 (L4 层) — zju3dv/INTACT-JEPA 意图-动作策略。

设计: docs/design/zmax_l4_intact_policy.md
实现: modeling_intact.py (lerobot 策略外壳) + runtime/ (真算法: 跨 venv 子进程桥)

与 lerobot 其它策略的差异 (必须显式知道):
  · 权重不在本仓库 —— 真权重跑在 INTACT-JEPA 的冻结运行时 (paper_runtime) 里，
    经子进程桥访问；因此 forward()/训练 在本策略中**不支持** (诚实报错, 不假装)。
  · 本策略只提供推理接口: select_action / predict_action_chunk / predict_intent。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from lerobot.configs.policies import PreTrainedConfig
from lerobot.configs.types import NormalizationMode


@PreTrainedConfig.register_subclass("intact")
@dataclass
class IntactConfig(PreTrainedConfig):
    """INTACT 意图-动作策略配置 (L4)。

    Args:
        horizon: 一次前向输出的动作块长度 (论文 prior_only: 5; 本工程对齐引擎 receding 5~8)
        action_dim: 动作维 (本工程 4D = dx,dy,dz,gripper; 论文模型实测维数以 runtime 为准并自动对齐)
        intent_mode: 意图模式 — goal_displacement (给 goal 帧) / waypoint (给目标点)
        feature_layout: 特征语法槽位 (four_slot = [z, m_t, z⊙m_t, A(a_{t-1})])
        runtime: 运行时 — auto / root / paper (论文权重必须 paper, 见技能 cross-venv-model-canvas-node §5)
        ckpt: 权重 (相对 $STABLEWM_HOME/checkpoints 或绝对路径); 空 = 用运行时默认
        device: 推理设备 — 与训练共存时用 cpu (ViT-tiny 单步 ~330ms, 够取证)
        l3_prior_weight: 解码后注入 L3 的默认融合权重 (w ∈ [0,1]; 0 = 不注入)
        l3_cond_dim: 注入 L3 的条件向量维度 (流形坐标 6 维 / 潜空间 960 维)
        l3_exclude_stages: 不注入的阶段 (默认排除"插入" —— 精插段引擎恒用解析伺服)
    """

    # ── 抽象属性实现 (lerobot 契约) ──
    n_obs_steps: int = 1
    chunk_size: int = 8
    n_action_steps: int = 8
    normalization_mapping: dict[str, NormalizationMode] = field(
        default_factory=lambda: {
            "VISUAL": NormalizationMode.IDENTITY,
            "STATE": NormalizationMode.MEAN_STD,
            "ACTION": NormalizationMode.MEAN_STD,
        }
    )

    # ── INTACT 专有 ──
    horizon: int = 8
    action_dim: int = 4
    intent_mode: str = "goal_displacement"          # goal_displacement | waypoint
    feature_layout: str = "four_slot"
    policy_variant: str = "direct"                  # direct (零搜索) | 其它留待后续
    runtime: str = "auto"                           # auto | root | paper
    ckpt: str = ""
    intact_device: str = "cpu"                      # INTACT 桥推理设备 (不用 device 键, 避免覆盖基类自动选设备)

    # ── L4 → L3 接入 (decoder) ──
    l3_prior_weight: float = 0.3
    l3_cond_dim: int = 6
    l3_exclude_stages: tuple[str, ...] = ("插入",)

    def validate_features(self) -> None:
        """本策略的特征由数据源 (metaworld 39D 状态 + 224² 渲染帧) 现场给出，不依赖数据集推断。

        不做强制校验: 数据源缺失时由 node/runtime 层给明确 reason (诚实优先于静默)。
        """

    def get_optimizer_preset(self):                                       # type: ignore[override]
        """INTACT 权重训练在外部运行时 (INTACT-JEPA paper_runtime) 里进行，本仓库不提供优化器。

        诚实返回 None (而不是造一个假的优化器配置) —— 若有人拿本策略去 lerobot 训练，
        会在这一步就拿到 None 而不是静默跑一个错的训练。
        """
        return None

    def get_scheduler_preset(self):                                       # type: ignore[override]
        return None

    @property
    def observation_delta_indices(self) -> list | None:
        return None

    @property
    def action_delta_indices(self) -> list | None:
        return None

    @property
    def reward_delta_indices(self) -> list | None:
        return None
