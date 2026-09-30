#!/usr/bin/env python3
"""skills 包 — Z-MAX 原子技能库 (集中放置原子技能真实源码)

权威定义在 atomic_skills.py (SK01-08 模板类 + SKILLS 注册表)。
画布 SK01-08 节点右键源码 → atomic_skills.py 对应技能类。
"""
from .atomic_skills import (  # noqa: F401
    AtomicSkill,
    SK01Approach, SK02Align, SK03Descend, SK04Grasp,
    SK05Lift, SK06Transfer, SK07Insert, SK08Complete,
    SKILLS, SKILL_BY_STAGE, SKILL_BY_CODE, list_skills,
)

__all__ = [
    "AtomicSkill",
    "SK01Approach", "SK02Align", "SK03Descend", "SK04Grasp",
    "SK05Lift", "SK06Transfer", "SK07Insert", "SK08Complete",
    "SKILLS", "SKILL_BY_STAGE", "SKILL_BY_CODE", "list_skills",
]
