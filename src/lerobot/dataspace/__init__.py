#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🌐 Z-MAX 全局数据空间 — 数据包

  topics.py   映射表(单一真源): 话题/类型/QoS/频率/生产者/消费者/质量规则 + 闭环流程 + 遥测模式
  quality.py  全面数据质量管理: 规则求值(纯函数, 不依赖 DDS, 控制台/守护/巡检共用)
  probe.py    全链路 topic 可视化探针: 订阅全空间话题 → 实测频率/帧龄/字段值 + 质量裁决 → JSON

分层口径(老倪): 本包只做「数据空间的映射 + 质量 + 可观测」, 不含模型算法
(算法在 src/lerobot/policies/), 不含业务编排(在 src/lerobot/engineering/)。
"""

from . import quality, topics                                     # noqa: F401

__all__ = ["topics", "quality"]
