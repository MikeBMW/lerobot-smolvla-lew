"""parallel.py — S2 并行处理层 (快慢分离, 状态空间模型画布)

快通道 (前馈加速器, 原左脑 MLP):  obs → 建议动作 u_ff (权重 30%)
  - 直接映射, 无递归无延迟, 毫秒级 (~5ms)
  - 学习过的逆动力学模型: u_ff = π_ff(x)

慢通道 (自适应状态估计器, 原右脑 GRU): obs → 递归潜状态 + 卡尔曼预测-校正
  - 状态转移 A ≈ GRU 循环权重 W_hh (世界动力学)
  - 卡尔曼增益 K ≈ 更新门/重置门 (信预测 vs 信观测)
  - ~15ms, 产生修正信号 + contact 概率

输出汇合到 S3 认知决策层: 调度器 u = w_ff·u_ff + (1−w_ff)·u_fb
"""
import numpy as np

W_FF = 0.3            # 前馈加速器建议权重 (认知调度器采纳比例)
LATENCY_FAST_MS = 5   # 快通道时耗
LATENCY_SLOW_MS = 15  # 慢通道时耗


class FeedforwardAccelerator:
    """⚡ 前馈加速器 — 快路径: obs → u_ff 建议动作 (4D: dx dy dz gripper)"""

    def __init__(self, w_ff=W_FF):
        self.w_ff = w_ff  # 建议权重 (调度器按此比例采纳)

    def forward(self, obs):
        """非线性映射 u_ff = π_ff(obs)。实际工程实现 = LeftBrainMLP (547K 参数)。"""
        # 占位: 真实推理由 src/lerobot/policies/left_right/modeling_left_right.py
        # LeftBrainMLP 完成 — 此处仅定义接口与语义
        return np.zeros(4)


class AdaptiveStateEstimator:
    """🔮 自适应状态估计器 — 慢路径: obs → 潜状态 (递归 + 卡尔曼校正)

    卡尔曼组件对照:
      状态转移 A      ≈ GRU 循环权重 W_hh      (世界动力学)
      控制输入 B      ≈ action 输入             (动作如何改变世界)
      先验估计        ≈ (h_{t-1}, obs, action)  (猜下一步)
      卡尔曼增益 K    ≈ 更新门 + 重置门          (信预测 vs 信观测)
    """

    def __init__(self, A=0.95, K=0.5):
        self.A = A  # 预测强度 (状态转移)
        self.K = K  # 更新增益 (等效卡尔曼增益)

    def predict(self, latent, action):
        """先验: x̂ₖ₋ = A·x̂ₖ₋₁ + B·uₖ"""
        return self.A * latent + action

    def update(self, latent_pred, z_k):
        """后验: x̂ₖ = x̂ₖ₋ + K·(z_k − x̂ₖ₋)  (残差加权)"""
        return latent_pred + self.K * (z_k - latent_pred)
