"""cognition.py — S3 认知决策层 (状态空间模型画布)

🧪 状态校正器 (卡尔曼更新核心):
  残差 r = z_k − ĥ(x̂ₖ₋)  (传感器反馈 vs 先验预测之差)
  接触概率 = σ(残差·增益)
  校正后潜状态 x̂ₖ = x̂ₖ₋ + K·r  → 喂回先验预测器 (闭环)

🧭 任务调度器 (原状态机, 握有否决权): 6阶段状态机
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
    """🧭 任务调度器 (原状态机, 握有否决权) — 6阶段状态机 + 按阶段动作融合

    阶段: 接近 → 抓取 → 抬起 → 转移 → 插入 → 完成
    推进证据 (每步 advance 喂入, 真实调度不靠外部硬推):
      接触概率 > contact_th      → 抓取   (力觉确认接触)
      夹持建立 (gripper>0.8)     → 抬起   (夹爪已闭合)
      孔位对准 (dist_h 缩小)     → 转移
      到位 (dist_h < align_th)   → 插入
      插入深度达标 (depth<阈值)   → 完成
    否决权: 残差 > veto_th → 强制减速重试; 连续 max_veto 次 → 异常上报
    动作融合按阶段调度:
      接近/抬起/转移 = 慢通道主导 (w_ff=0.3, 防碰撞)
      抓取/插入      = 前馈推力主导 (w_contact=0.85, 力控插入)
    """

    STAGES = ["接近", "抓取", "抬起", "转移", "插入", "完成"]

    def __init__(self, w_ff=0.3, contact_th=0.6, veto_th=2.0,
                 w_contact=0.85, align_th=0.02, insert_depth=0.004, max_veto=3):
        self.w_ff = w_ff                # 接近阶段前馈权重 (慢通道主导防碰撞)
        self.contact_th = contact_th    # 接触判定阈值 (力觉证据)
        self.veto_th = veto_th          # 否决阈值 (残差异常)
        self.w_contact = w_contact      # 抓取/插入阶段前馈推力权重 (力控)
        self.align_th = align_th        # 孔位对准阈值 (转移→插入)
        self.insert_depth = insert_depth  # 插入深度达标 (插入→完成)
        self.max_veto = max_veto        # 连续否决上限 → 异常上报
        self.stage_idx = 0
        self.veto_count = 0
        self.history = []               # 阶段切换历史 [(stage, reason)]

    def stage(self):
        return self.STAGES[self.stage_idx]

    def fuse(self, u_ff, u_fb):
        """接近阶段融合: u = w_ff·u_ff + (1−w_ff)·u_fb (慢通道主导)"""
        return self.w_ff * u_ff + (1.0 - self.w_ff) * u_fb

    def _goto(self, idx, reason):
        self.stage_idx = idx
        self.history.append((self.STAGES[idx], reason))

    def advance(self, contact_p=None, dist_h=None, gripper=None, depth=None):
        """状态机推进 — 感知/几何证据驱动 (每步调用)"""
        st = self.stage()
        if st == "接近" and contact_p is not None and contact_p > self.contact_th:
            self._goto(1, f"接触概率 {contact_p:.2f} > {self.contact_th}")
        elif st == "抓取" and gripper is not None and gripper > 0.8:
            self._goto(2, f"夹持建立 gripper={gripper:.2f}")
        elif st == "抬起" and dist_h is not None and dist_h < self.align_th * 0.5:
            self._goto(3, f"孔位对准 dist_h={dist_h:.4f}")
        elif st == "转移" and dist_h is not None and dist_h < self.align_th:
            self._goto(4, f"到位 dist_h={dist_h:.4f}")
        elif st == "插入" and depth is not None and depth < self.insert_depth:
            self._goto(5, f"插入深度达标 depth={depth:.4f}")
        return self.stage()

    def decide(self, u_ff, u_fb, contact_p, residual):
        """决策: ①否决权 (残差异常) ②按阶段融合 — 力控阶段前馈推力主导"""
        if residual > self.veto_th:
            self.veto_count += 1
            if self.veto_count >= self.max_veto:
                return 0.0, f"异常: 连续否决 (残差 {residual:.2f})"
            return 0.0, f"否决: 减速/重试 (残差 {residual:.2f})"
        self.veto_count = 0
        st = self.stage()
        if st in ("抓取", "插入"):
            # 力控阶段: 前馈推力主导 (插入靠推力, 不是比例衰减)
            u = self.w_contact * u_ff + (1.0 - self.w_contact) * u_fb
        else:
            u = self.fuse(u_ff, u_fb)     # 接近/抬起/转移: 慢通道校正主导
        tag = " · 接触" if contact_p > self.contact_th else ""
        return u, f"阶段 {st}{tag}"
