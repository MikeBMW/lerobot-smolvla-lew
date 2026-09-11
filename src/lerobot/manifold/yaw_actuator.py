# -*- coding: utf-8 -*-
"""🧠 yaw_actuator.py — 流形预测器 → 夹爪 yaw 指令 执行器 (L4 姿态解算, 2026-09-11)

老倪: "L4 的夹爪旋转指令是谁发出的? 是流形预测节点么?" → 此前答: 不是 (L4Demo 阶段
脚本开环固定角)。本文件 = 让**流形预测器真正发旋转指令**的接线 (A/B 实证用)。

链路 (每帧真调, 断点可进 `ManifoldYawActuator.decide`):
    z7 (相对几何潜向量) ─┐
                          ├─ WorldModelPredictor (LatentPredictor+ManifoldReadout) → 流形 6 维
    a4 (4D 动作) ────────┘     [progress, risk, V, eta, rem, dperp]
    候选偏航 φ ∈ {φ_ref ± k·Δφ}：
        姿态假设编码 = "如果夹爪转到 φ，剩余姿态失配 δφ = (来料朝向 − φ)"
        → 把相对几何按 −δφ 绕 z 旋转后喂预测器 (δφ=0 = 训练分布里的对准姿态)
        → 代价 cost(φ) = w_risk·|risk| + w_perp·|dperp| + w_prog·|progress|
                        + λ_prior·|φ − φ_ref|
    φ* = argmin cost(φ) → 下发 yaw (带 slew 限幅/角度限幅/夹持期冻结)

诚实标注 (不许含糊):
  · 预测器权重 = 仓库 models/l4_mani_predictor_v5.pt (v5, CY 等距正则, 抗干扰 64.6%);
    加载失败退回随机权重 → `trained=False`, 此时本执行器输出 = 随机打分对照 (日志明示)。
  · 候选姿态编码是**工程假设** (把候选 yaw 表示为相对几何旋转), 非测得真值;
    代价项权重可由 env 覆盖 (SS_MANI_YAW_W_*), 便于 A/B 复现。
  · φ_ref (搜索中心) 来自现场几何 (来料长轴朝向) = 几何先验; 预测器负责在候选里选。
"""
from __future__ import annotations

import math

import numpy as np


def _rot_xy(v, ang):
    """把 3 维向量 (或 [N,3]) 绕 z 转 ang 弧度 (就地返回新数组)"""
    v = np.asarray(v, dtype=float)
    c, s = math.cos(ang), math.sin(ang)
    if v.ndim == 1:
        return np.array([c * v[0] - s * v[1], s * v[0] + c * v[1], v[2] if v.size > 2 else 0.0])
    out = v.copy()
    out[:, 0] = c * v[:, 0] - s * v[:, 1]
    out[:, 1] = s * v[:, 0] + c * v[:, 1]
    return out


class ManifoldYawActuator:
    """流形预测器驱动的夹爪 yaw 指令器 (L4 姿态解算)。

    用法:
        act = ManifoldYawActuator(predictor, cand_span_deg=45, cand_step_deg=15)
        phi_deg, info = act.decide(z7, a4, module_yaw_deg=90.0)
        # → info["costs"] 每候选代价/分量, info["trained"], info["n_calls"] (每帧真调计数)
    """

    def __init__(self, predictor, cand_span_deg=45.0, cand_step_deg=15.0,
                 w_risk=1.0, w_perp=1.0, w_prog=0.25, lam_prior=0.02,
                 clip_deg=90.0, log=None):
        self.predictor = predictor
        self.cand_span = float(cand_span_deg)
        self.cand_step = float(cand_step_deg)
        self.w_risk = float(w_risk)
        self.w_perp = float(w_perp)
        self.w_prog = float(w_prog)
        self.lam_prior = float(lam_prior)
        self.clip_deg = float(clip_deg)
        self.log = log or (lambda *a: None)
        self.n_calls = 0          # 预测器真实前向次数 (取证: 应 ≈ 帧数×候选数)
        self.n_decide = 0         # 决策次数
        self.last_info = None
        self.history = []         # [(φ_ref, φ*, best_cost, costs)]
        self.trained = bool(getattr(predictor, "trained", False)) if predictor is not None else False

    # ── 候选集 ──
    def candidates(self, phi_ref_deg):
        n = int(round(self.cand_span * 2 / max(self.cand_step, 1e-6))) + 1
        offs = np.linspace(-self.cand_span, self.cand_span, n)
        return [float(np.clip(phi_ref_deg + o, -self.clip_deg, self.clip_deg)) for o in offs]

    # ── 单候选代价 (真调预测器) ──
    def _cost(self, z7, a4, phi_deg, phi_ref_deg):
        import torch
        dphi = math.radians(phi_ref_deg - phi_deg)     # 残余姿态失配 (对准 → 0)
        z = np.asarray(z7, dtype=float).copy().ravel()
        if z.size >= 3:
            z[0:3] = _rot_xy(z[0:3], -dphi)
        if z.size >= 6:
            z[3:6] = _rot_xy(z[3:6], -dphi)
        zt = torch.from_numpy(np.asarray(z[:7], dtype=np.float32)).unsqueeze(0)
        at = torch.from_numpy(np.asarray(a4, dtype=float).ravel()[:4].astype(np.float32)).unsqueeze(0)
        with torch.no_grad():
            out = self.predictor(zt, at)
        self.n_calls += 1
        m = out["manifold"][0].float().cpu().numpy()
        c_risk = self.w_risk * abs(float(m[1]))
        c_perp = self.w_perp * abs(float(m[5]))
        c_prog = self.w_prog * abs(float(m[0]))
        c_prior = self.lam_prior * abs(math.radians(phi_deg - phi_ref_deg))
        return c_risk + c_perp + c_prog + c_prior, {
            "risk": float(m[1]), "dperp": float(m[5]), "progress": float(m[0]),
            "eta": float(m[3]), "rem": float(m[4]), "V": float(m[2]),
            "c_risk": c_risk, "c_perp": c_perp, "c_prog": c_prog, "c_prior": c_prior}

    def decide(self, z7, a4, module_yaw_deg, phi_ref_deg=None):
        """返回 (phi_star_deg, info)。info 含每候选代价与分量 (审计/回归用)。"""
        if self.predictor is None:
            return float(phi_ref_deg if phi_ref_deg is not None else module_yaw_deg), {
                "trained": False, "costs": [], "n_calls": self.n_calls, "reason": "predictor=None"}
        if phi_ref_deg is None:
            phi_ref_deg = module_yaw_deg
        costs = []
        for phi in self.candidates(phi_ref_deg):
            c, comp = self._cost(z7, a4, phi, phi_ref_deg)
            costs.append((phi, c, comp))
        best = min(costs, key=lambda t: t[1])
        self.n_decide += 1
        info = {"phi_ref": float(phi_ref_deg), "phi_star": float(best[0]), "best_cost": float(best[1]),
                "costs": [(float(p), float(c), d) for p, c, d in costs],
                "trained": self.trained, "n_calls": self.n_calls,
                "encoding": "残余姿态失配 δφ=(来料朝向−φ) 绕z旋转相对几何 (工程假设)"}
        self.last_info = info
        self.history.append((info["phi_ref"], info["phi_star"], info["best_cost"]))
        return info["phi_star"], info

    def summary(self):
        return {"trained": self.trained, "n_calls": self.n_calls, "n_decide": self.n_decide,
                "cand_span_deg": self.cand_span, "cand_step_deg": self.cand_step,
                "weights": {"risk": self.w_risk, "perp": self.w_perp, "prog": self.w_prog,
                            "prior": self.lam_prior}}
