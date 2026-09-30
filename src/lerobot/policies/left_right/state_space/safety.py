"""safety.py — 安全执行边界 (状态空间模型画布)

饱和限幅: 任何融合后的动作先过限幅再下发执行器。

双层安全:
  认知层否决权 (cognition.py) — 决策层看语义 (残差/接触概率)
  物理限幅 (本模块)          — 执行层卡物理 (速度/力/位置上限)
"""
import numpy as np

# 物理限幅 (默认: 与状态机标定一致)
VEL_LIMIT = 1.0     # 速度上限
FORCE_LIMIT = 5.0   # 力上限 (N) — 金手指保护 ≤2N 过盈段力控
POS_LIMIT = 0.6     # 位置/动作幅值上限


def saturate(u, limit=POS_LIMIT):
    """饱和限幅: clip(u, −limit, +limit)"""
    return np.clip(np.asarray(u, dtype=float), -limit, limit)
