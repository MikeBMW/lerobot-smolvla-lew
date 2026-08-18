"""cognition.py — S3 认知决策层 (状态空间模型画布)

🧪 状态校正器 (卡尔曼更新核心):
  残差 r = z_k − ĥ(x̂ₖ₋)  (传感器反馈 vs 先验预测之差)
  接触概率 = σ(残差·增益)
  校正后潜状态 x̂ₖ = x̂ₖ₋ + K·r  → 喂回先验预测器 (闭环)

🧭 认知任务调度器 (原状态机, 握有否决权):
  输入: u_ff 建议动作 (前馈加速器) + contact 概率/残差 (状态校正器)
  决策: 阶段切换 (接近→抓取→抬起→转移→插入→完成) + 动作融合
  融合: u = w_ff·u_ff + (1−w_ff)·u_fb
  否决权: 残差 > 阈值 → 强制减速/重试 (快路径无权独自行动)
"""
import numpy as np


def state_correction(prior_pred, z_k, K=0.5):
    """状态校正: 残差 r = z_k − prior_pred (传感器反馈 vs 先验预测);
    校正后潜状态 x̂ = prior_pred + K·r (卡尔曼更新核心, K=增益)"""
    residual = z_k - prior_pred
    corrected = prior_pred + K * residual
    return corrected, residual


def contact_probability(residual, gain=1.0):
    """接触概率: σ(残差·增益) — 残差大 → 接触/碰撞概率高"""
    return 1.0 / (1.0 + np.exp(-gain * residual))


class CognitiveScheduler:
    """🧭 认知任务调度器 — 握有否决权

    STAGES: 接近 → 抓取 → 抬起 → 转移 → 插入 → 完成
    """

    STAGES = ["接近", "抓取", "抬起", "转移", "插入", "完成"]

    def __init__(self, w_ff=0.3, contact_th=0.6, veto_th=2.0):
        self.w_ff = w_ff          # 前馈建议权重
        self.contact_th = contact_th  # 接触判定阈值
        self.veto_th = veto_th    # 否决阈值 (残差)
        self.stage_idx = 0

    def fuse(self, u_ff, u_fb):
        """动作融合: u = w_ff·u_ff + (1−w_ff)·u_fb"""
        return self.w_ff * u_ff + (1.0 - self.w_ff) * u_fb

    def decide(self, u_ff, u_fb, contact_p, residual):
        """决策: ①残差超阈值=世界出乎意料 → 否决 (强制减速) ②接触成立 → 力控插入
        (前馈推力主导 0.85, 校正 15% 兜底 — 快慢分离的阶段切换) ③接近 → 慢通道主导
        (0.3 前馈 + 0.7 校正, 防碰撞)"""
        if residual > self.veto_th:
            return 0.0, "否决: 减速/重试"      # 否决权生效 (残差异常)
        if contact_p > self.contact_th:
            # 接触: 阶段推进到抓取 — 前馈推力主导 (插入靠推力, 不是比例衰减)
            u = 0.85 * u_ff + 0.15 * u_fb
            self.stage_idx = max(1, self.stage_idx)   # 接近 → 抓取
            return u, f"阶段 {self.STAGES[self.stage_idx]} · 接触"
        u = self.fuse(u_ff, u_fb)             # 接近: 慢通道校正主导
        return u, f"阶段 {self.STAGES[self.stage_idx]}"
