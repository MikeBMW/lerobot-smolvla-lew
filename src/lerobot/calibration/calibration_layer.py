# -*- coding: utf-8 -*-
"""calibration_layer.py — 🧮 标定层: 引力/斥力二分超参数 + 平衡点

第一性原理 (2026-09-02 老倪, 参考 Drifting Models arXiv:2602.04770):
  把状态空间引擎的全部超参数按作用方向二分:
    引力 (Attraction) = 快速动作 — 把末端拉向目标 (Kp·(target−pos) + 阶段速度上限/下限)
    斥力 (Repulsion)  = 状态预测 — 把状态估计拉回与预测一致 (卡尔曼校正/残差EMA/接触判定)
  两者平衡点 = 系统无漂移 (V≈0, 对应论文 q=p 平衡; 反称场 Vp,q(x) = −Vq,p(x) ⇒ q=p ⇒ V=0)。

标定量: 状态/阶段是明确的标定量 — 每个阶段的 STAGE_V_CAP 是该阶段的速度标定,
        每个估计增益 (K_kalman/EMA/接触增益/否决阈值) 是状态预测的标定。

定位: 标定层是**回路外的元层** — 收集/展示/调节引擎散落各处的标定参数, 不参与
      引擎推理, 不改变任何现有拓扑/流程/架构 (引擎仍用源码常量, 标定层只读展示+建议)。

数据同源: 数值与引擎源码一致 (cognition.py STAGE_V_CAP/STAGE_V_MIN, parallel.py Kp,
          state_space_sim.py 卡尔曼/EMA/接触增益/否决阈值), 改引擎时此处同步。
"""
import json
import os
import time

STAGES = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"]

# ── 引力标定 (快速动作) — 与 parallel.py FeedforwardAccelerator / cognition.py 同源 ──
ATTRACTION_CALIB = {
    "Kp": 1.2,                # 比例引导增益 (前馈加速器 Kp·(target−pos) 限幅 ±0.5)
    "u_clip": 0.5,            # 前馈限幅
    "safety_limit": 0.6,      # 安全执行边界 saturate 限幅
    "stage_v_cap": {          # 各阶段速度上限 (明确标定量: 每阶段一个速度标定)
        "接近": 0.35, "对位": 0.12, "下降": 0.09, "抓取": 0.04,
        "抬起": 0.30, "转移": 0.35, "插入": 0.07, "完成": 0.02},
    "stage_v_min": {          # 最小趋近速度 (证据未达标时别在末端磨)
        "接近": 0.12, "对位": 0.04, "抬起": 0.10, "转移": 0.12},
}

# ── 斥力标定 (状态预测) — 与 state_space_sim.py 卡尔曼/滤波/接触判定同源 ──
REPULSION_CALIB = {
    "K_kalman": 0.5,          # 状态校正增益 (state_correction K=0.5)
    "res_ema": 0.15,          # 残差 EMA 滤波系数 (反馈前 α=0.15, ≈10 步时间常数)
    "contact_gain": 8.0,      # 接触概率增益 (contact_probability gain)
    "veto_th": 2.0,           # 否决阈值 (残差超此值调度器否决)
    "k_fb": 1.0,              # 反馈增益 (decide 前馈+反馈相加 k_fb)
    "prior_A": 0.95,          # 先验动力学状态转移 (AdaptiveStateEstimator A)
}

# 平衡判定阈值 (|引力势−斥力势| < 此值 = 平衡)
EQ_BAND = 0.15


class CalibrationLayer:
    """标定层 — 引力/斥力标定参数 + 平衡点计算 (纯数据/计算, 不参与引擎推理)"""

    def __init__(self, attraction=None, repulsion=None):
        self.attr = dict(ATTRACTION_CALIB)
        if attraction:
            self.attr.update(attraction)
        self.rep = dict(REPULSION_CALIB)
        if repulsion:
            self.rep.update(repulsion)

    # ── 引力势: 当前速度贴阶段上限的程度 (1.0=满速贴上限, <1=有余量) ──
    def attraction_potential(self, stage, speed):
        cap = float(self.attr["stage_v_cap"].get(stage, 0.1))
        return float(min(1.0, abs(speed) / max(cap, 1e-6)))

    # ── 斥力势: 状态预测的不确定性 (残差贴否决阈值的程度 + 接触概率) ──
    def repulsion_potential(self, residual, contact_p):
        r = float(min(1.0, abs(residual) / max(self.rep["veto_th"], 1e-6)))
        return float(0.7 * r + 0.3 * (1.0 - float(contact_p)))

    # ── 平衡偏差: 引力势 − 斥力势; |gap|→0 表示引力斥力平衡 (V≈0, 无漂移) ──
    def equilibrium_gap(self, stage, speed, residual, contact_p):
        return self.attraction_potential(stage, speed) - self.repulsion_potential(residual, contact_p)

    def equilibrium_state(self, gap):
        if abs(gap) < EQ_BAND:
            return "⚖ 平衡"
        return "引力↑ 动作偏快" if gap > 0 else "斥力↑ 状态修正偏强"

    # ── 一行可读摘要 (画布日志用) ──
    def summarize(self, stage, speed, residual, contact_p):
        a = self.attraction_potential(stage, speed)
        r = self.repulsion_potential(residual, contact_p)
        g = a - r
        return (f"标定层 · {stage}: 引力势 {a:.2f} vs 斥力势 {r:.2f} · "
                f"平衡偏差 {g:+.2f} → {self.equilibrium_state(g)}")

    # ── 标定表导出 (不改变引擎, 落盘建议值) ──
    def export(self, path=None):
        if path is None:
            path = os.path.join("reports", f"calibration_{time.strftime('%Y%m%d_%H%M%S')}.json")
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"attraction": self.attr, "repulsion": self.rep,
                       "eq_band": EQ_BAND}, f, ensure_ascii=False, indent=1)
        return path
