"""dynamics.py — 先验动力学预测器 (状态空间模型画布)

预测 next_obs: x̂ₖ₋ = A·x̂ₖ₋₁ + B·uₖ  (先验 = 还没看传感器就先猜)

- 状态转移 A ≈ GRU 循环权重 (世界模型学到的动力学)
- 控制输入 B ≈ action 的影响
- 输出 → 状态校正器作为残差基准 (z_k − ĥ(x̂ₖ₋))

先验 vs 观测的差 = 残差: 残差大 = 世界出乎意料 → 接触/异常信号。
"""
import numpy as np


class PriorDynamicsPredictor:
    """📈 先验动力学预测器 — 潜状态 → next_obs 预测"""

    def __init__(self, A=0.95, B=1.0):
        self.A = A  # 状态转移 (≈ GRU 循环权重)
        self.B = B  # 控制输入增益

    def predict(self, latent, action):
        """先验预测: x̂ₖ₋ = A·latent + B·action"""
        return self.A * latent + self.B * action
