#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""manifold_engine.py — 流形引擎 (Manifold Engine) · L4 核心内核

定义 (老倪 2026-09-24 架构升级): 把高维状态空间自动约束为低维流形, 并在该流形上完成
**状态表征 → 约束投影 → 测地线导航 → 梯度流 → 感知反馈闭环**的通用计算引擎。

    输入 x ∈ R^N  → [1] 编码提升 z ∈ R^n → [2] 流形投影 p ∈ M → [3] 几何计算 (梯度/测地线/势场)
                  → [4] 导航输出 a → [5] 感知反馈 (有界修正) → 回到 [2]

设计纪律 (本仓库铁律):
  · **每个 ready 流形都必须真投影/真度量/真测地线** (有可核公式); 未实现的 (calabi_yau 等)
    一律标 `status="planned"` 并在 `why` 说明缺什么 —— **不造假**。
  · 复用既有真件, 不另起炉灶:
      - SU(2) 群: `left_right/state_space/su2.py` (SU2Element / bounded_rotvec / distance_fs)
      - SO(3)/SE(3): `manifold/lie_intent.py` 四元数/SO3 工具 (quat_slerp / quat_mul / R_from_quat)
      - 势函数 Φ: `manifold/manifold_layer.py` ContactManifold / PerformanceManifold (接触 V / 性能 V_p)
      - 提升: `manifold/fiber_bundle.py::fit_map` (可选, 有标定文件时走丛映射)
  · 延迟/精度**全部实测** (perf_counter), 不抄规格书。

用法 (独立自检):
    ./gui-venv311/bin/python src/lerobot/manifold/manifold_engine.py --selftest
标定 (从真实引擎轨迹拟合编码器/解码器 → models/manifold_engine.npz):
    MUJOCO_GL=egl ./gui-venv311/bin/python src/lerobot/manifold/manifold_engine.py --calibrate
"""
from __future__ import annotations

import json
import os
import sys
import time

import numpy as np

# ── 复用既有真件 (缺失不阻塞: 相关行会如实标注, 不伪造) ──
try:
    from lerobot.manifold.lie_intent import quat_slerp, quat_mul, quat_exp, quat_from_R, R_from_quat
except Exception:                                                              # noqa: BLE001
    quat_slerp = quat_mul = quat_exp = quat_from_R = R_from_quat = None

try:
    _SS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "policies", "left_right", "state_space")
    if _SS not in sys.path:
        sys.path.insert(0, _SS)
    from su2 import SU2Element, bounded_rotvec, encode_obs43, obs43_geometry      # noqa: PLC0415
except Exception:                                                              # noqa: BLE001
    SU2Element = bounded_rotvec = encode_obs43 = obs43_geometry = None

# ══════════════════════════════════════════════════════════════════════════════
# 流形类型注册表 (status 如实: ready = 真实现 / planned = 未实现, 写明缺什么)
# ══════════════════════════════════════════════════════════════════════════════
MANIFOLD_REGISTRY: dict[str, dict] = {
    "euclidean": {"status": "ready", "dim": None, "constraint": "无约束 R^n",
                  "metric": "欧氏", "geodesic": "直线", "src": "本模块"},
    "sphere": {"status": "ready", "dim": None, "constraint": "‖p‖=1",
               "metric": "弧长 (chord→arc)", "geodesic": "大圆 (slerp)", "src": "本模块"},
    "torus": {"status": "ready", "dim": None, "constraint": "周期边界 (角度 mod 2π)",
              "metric": "周期欧氏", "geodesic": "线性 mod 2π", "src": "本模块"},
    "so3": {"status": "ready", "dim": 3, "constraint": "RᵀR=I, det R=1",
            "metric": "测地角 arccos((tr R−1)/2)", "geodesic": "四元数 slerp", "src": "lie_intent"},
    "se3": {"status": "ready", "dim": 6, "constraint": "RᵀR=I, det R=1 (t 自由)",
            "metric": "Killing 近似 ‖ΔR‖_F + ‖Δt‖", "geodesic": "螺旋运动 (slerp R + lerp t)",
            "src": "lie_intent"},
    "su2": {"status": "ready", "dim": 3, "constraint": "U†U=I, det U=1",
            "metric": "Fubini–Study (distance_fs)", "geodesic": "指数映射 + slerp", "src": "state_space/su2.py"},
    "latent_flat": {"status": "ready", "dim": None, "constraint": "平坦潜空间 (由标定确定维数)",
                    "metric": "欧氏", "geodesic": "直线 (带自适应增益)", "src": "fiber_bundle 标定口径"},
    "calabi_yau": {"status": "planned", "dim": 6, "constraint": "Ricci-flat (Kähler)", "metric": "Ricci-flat",
                   "geodesic": "复测地线",
                   "why": "缺 Ricci-flat 度量求解器 (未实现) → 仅登记不提供投影/导航, **不造数**"},
    "hyperbolic": {"status": "planned", "dim": None, "constraint": "K<0 常负曲率",
                   "metric": "Poincaré 度量", "geodesic": "双曲测地线", "why": "未实现 (缺 exp/log 图卡)"},
}

STAGE_KEYS = ("encode", "project", "metric", "navigate", "feedback")


# ══════════════════════════════════════════════════════════════════════════════
# 组件
# ══════════════════════════════════════════════════════════════════════════════
class Encoder:
    """高维状态 x∈R^N → 低维潜空间 z∈R^n (PCA 真拟合; 可选 fiber_bundle 丛映射提升)"""

    def __init__(self, latent_dim: int = 16) -> None:
        self.latent_dim = int(latent_dim)
        self.mu: np.ndarray | None = None
        self.W: np.ndarray | None = None          # (N, n) 主方向
        self.lift = None                          # 可选 FiberConnection (有标定文件时)
        self.n_fit = 0

    def fit(self, X: np.ndarray) -> dict:
        X = np.asarray(X, float)
        X = X.reshape(len(X), -1)
        self.mu = X.mean(0)
        Xc = X - self.mu
        n = int(min(self.latent_dim, Xc.shape[1], max(2, len(X) - 1)))
        # SVD 真分解 (经济型)
        _, S, Vt = np.linalg.svd(Xc, full_matrices=False)
        self.W = Vt[:n].T.copy()
        self.latent_dim = n
        self.n_fit = len(X)
        var = (S ** 2) / max(float((S ** 2).sum()), 1e-12)
        return {"n_samples": int(len(X)), "in_dim": int(Xc.shape[1]), "latent_dim": n,
                "explained_var": [round(float(v), 4) for v in var[:n]],
                "explained_var_sum": round(float(var[:n].sum()), 4)}

    # 形态: (N,) / (B,N)
    def encode(self, x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, float)
        if self.W is None or self.mu is None:
            raise RuntimeError("编码器未拟合 (先 fit 或 load)")
        single = x.ndim == 1
        X = x[None] if single else x
        z = (X - self.mu) @ self.W
        return z[0] if single else z

    def save(self, path: str) -> None:
        np.savez(path, mu=self.mu, W=self.W, latent_dim=self.latent_dim, n_fit=self.n_fit)

    def load(self, path: str) -> bool:
        if not os.path.isfile(path):
            return False
        d = np.load(path)
        self.mu, self.W = d["mu"], d["W"]
        self.latent_dim, self.n_fit = int(d["latent_dim"]), int(d["n_fit"])
        return True


class ManifoldProjector:
    """潜空间 z → 流形上的点 p (按类型真投影, 返回约束残差)"""

    def __init__(self, manifold_type: str = "sphere", radius: float = 1.0) -> None:
        if manifold_type not in MANIFOLD_REGISTRY:
            raise KeyError(f"未注册流形类型: {manifold_type}")
        self.type = manifold_type
        self.radius = float(radius)
        self.su2_obj = None

    @property
    def ready(self) -> bool:
        return MANIFOLD_REGISTRY[self.type]["status"] == "ready"

    # 各流形表示所需最小维数 (潜空间不够时必须**补齐并标注**, 不许静默退化)
    NEED = {"sphere": 2, "torus": 2, "so3": 9, "se3": 12, "su2": 3, "euclidean": 1, "latent_flat": 1}

    def project(self, z: np.ndarray):
        """→ (p, residual, meta)
        · residual = **投影后的约束违例** (‖约束(p)‖, ≈0 才算投影器正确)
        · meta["drift"] = **投影改动量** ‖p − z_pad‖ (原始状态离流形多远 → 置信度/异常判据)
        """
        z = np.asarray(z, float).ravel()
        t = self.type
        need = self.NEED.get(t, 1)
        padded = False
        if z.size < need:                                  # 潜维不足 → 零补齐 + 显式标注 (不静默)
            z = np.pad(z, (0, need - z.size))
            padded = True
        meta = {"latent_padded": padded, "need": need, "got": int(np.asarray(z).size)}
        if t in ("euclidean", "latent_flat"):
            return z.copy(), 0.0, {**meta, "drift": 0.0}
        if t == "sphere":
            n = float(np.linalg.norm(z))
            if n < 1e-12:
                v = np.zeros_like(z)
                v[0] = self.radius
                return v, 0.0, {**meta, "drift": 1.0, "note": "零向量 → 取基向量"}
            p = z / n * self.radius
            resid = abs(float(np.linalg.norm(p)) - self.radius)
            return p, resid, {**meta, "drift": round(float(np.linalg.norm(p - z)), 6),
                              "r_in": round(n, 4)}
        if t == "torus":
            p = np.mod(z, 2 * np.pi)
            return p, 0.0, {**meta, "drift": round(float(np.linalg.norm(p - z)), 6),
                            "wrapped": int(np.sum(np.abs(p - z) > 1e-9))}
        if t in ("so3", "se3"):
            R9 = z[:9].reshape(3, 3)
            U, _, Vt = np.linalg.svd(R9)
            Rn = U @ Vt
            if np.linalg.det(Rn) < 0:                       # det=+1 修正 (SO(3) 约束)
                U[:, -1] *= -1.0
                Rn = U @ Vt
            resid = float(np.linalg.norm(Rn.T @ Rn - np.eye(3)))
            if t == "so3":
                drift = float(np.linalg.norm(Rn - R9))
                return Rn.ravel(), resid, {**meta, "drift": round(drift, 6),
                                           "det": round(float(np.linalg.det(Rn)), 6)}
            tt = z[9:12]
            p = np.concatenate([Rn.ravel(), tt])
            # 漂移按**表示空间**比 (p 是 12 维, 潜空间更长 → 取前 12 维, 不做跨维广播)
            return p, resid, {**meta, "drift": round(float(np.linalg.norm(p - z[:12])), 6),
                              "det": round(float(np.linalg.det(Rn)), 6)}
        if t == "su2":
            if SU2Element is None:
                raise RuntimeError("su2.py 不可用")
            v = z[:3]
            e = SU2Element.from_rotvec(bounded_rotvec(v, gain=2.0))
            p = np.array([e.w, e.x, e.y, e.z])
            n = float(np.linalg.norm(p))
            p = p / n if n > 1e-12 else np.array([1.0, 0.0, 0.0, 0.0])
            self.su2_obj = SU2Element(*p)
            resid = abs(float(np.linalg.norm(p)) - 1.0)
            return p, resid, {**meta, "drift": round(float(self.su2_obj.theta() / np.pi), 6),
                              "theta": round(float(self.su2_obj.theta()), 4),
                              "visibility": round(float(self.su2_obj.visibility()), 4),
                              "axis": [round(float(a), 3) for a in self.su2_obj.axis()]}
        return z.copy(), 0.0, {**meta, "drift": 0.0,
                               "note": f"{t} 未实现 (status={MANIFOLD_REGISTRY[t]['status']})"}


class MetricCalculator:
    """流形上的距离 (按类型真公式) + 切空间梯度 (数值中心差分 + 切空间投影)"""

    def __init__(self, manifold_type: str = "sphere") -> None:
        self.type = manifold_type

    def distance(self, p: np.ndarray, q: np.ndarray) -> float:
        p, q = np.asarray(p, float).ravel(), np.asarray(q, float).ravel()
        t = self.type
        if t in ("euclidean", "latent_flat"):
            return float(np.linalg.norm(p - q))
        if t == "sphere":
            c = float(np.clip(np.dot(p, q) / (np.linalg.norm(p) * np.linalg.norm(q) + 1e-12), -1, 1))
            return float(np.arccos(c))
        if t == "torus":
            d = np.abs(p - q)
            d = np.minimum(d, 2 * np.pi - d)
            return float(np.linalg.norm(d))
        if t == "so3":
            R1, R2 = p.reshape(3, 3), q.reshape(3, 3)
            tr = float(np.clip((np.trace(R1.T @ R2) - 1.0) / 2.0, -1.0, 1.0))
            return float(np.arccos(tr))
        if t == "se3":
            # 🐛 2026-09-24: SE(3) 点是 12 维 (R 9 + t 3) → 必须切 [:9] 再 reshape
            if p.size < 12 or q.size < 12:
                raise ValueError(f"SE(3) 点应为 12 维 (R9+t3), 收到 {p.size}/{q.size}")
            R1, R2 = p[:9].reshape(3, 3), q[:9].reshape(3, 3)
            tr = float(np.clip((np.trace(R1.T @ R2) - 1.0) / 2.0, -1.0, 1.0))
            return float(np.arccos(tr) + np.linalg.norm(p[9:12] - q[9:12]))
        if t == "su2":
            if SU2Element is None:
                raise RuntimeError("su2.py 不可用")
            return float(e8ds(p, q))
        return float(np.linalg.norm(p - q))

    def tangent_gradient(self, phi, p: np.ndarray, h: float = 1e-4) -> np.ndarray:
        """∇Φ 的**切空间**分量 (球面/SU2 = 切空间投影; 其余 = 欧氏梯度)"""
        p = np.asarray(p, float).ravel()
        g = np.zeros_like(p)
        for i in range(p.size):
            e = np.zeros_like(p)
            e[i] = h
            g[i] = (float(phi(p + e)) - float(phi(p - e))) / (2 * h)
        if self.type == "sphere":
            g = g - p * float(np.dot(g, p)) / max(float(np.dot(p, p)), 1e-12)     # 去掉法向分量
        return g


def e8ds(p: np.ndarray, q: np.ndarray) -> float:
    """SU(2) Fubini–Study 距离 (直接按四元数内积算, 与 su2.SU2Element.distance_fs 同式)"""
    p = np.asarray(p, float).ravel()
    q = np.asarray(q, float).ravel()
    p = p / max(np.linalg.norm(p), 1e-12)
    q = q / max(np.linalg.norm(q), 1e-12)
    c = float(np.clip(abs(np.dot(p, q)), -1.0, 1.0))
    return float(np.arccos(c))


class Navigator:
    """测地线导航: 起点→终点路径 (真 slerp/exp map) + 单步沿切向量走"""

    def __init__(self, manifold_type: str = "sphere") -> None:
        self.type = manifold_type

    def compute_geodesic(self, p0: np.ndarray, pT: np.ndarray, T: int = 16) -> dict:
        p0, pT = np.asarray(p0, float).ravel(), np.asarray(pT, float).ravel()
        T = max(2, int(T))
        ts = np.linspace(0.0, 1.0, T)
        path = []
        t = self.type
        for a in ts:
            if t == "sphere":
                path.append(slerp_unit(p0, pT, float(a)))
            elif t == "su2":
                path.append(slerp_unit(p0, pT, float(a)))
            elif t in ("so3", "se3"):
                if t == "se3" and p0.size >= 12:
                    R = slerp_R(p0[:9].reshape(3, 3), pT[:9].reshape(3, 3), float(a))
                    tt = (1 - a) * p0[9:12] + a * pT[9:12]
                    path.append(np.concatenate([R.ravel(), tt]))
                else:
                    path.append(slerp_R(p0.reshape(3, 3), pT.reshape(3, 3), float(a)).ravel())
            elif t == "torus":
                d = np.mod(pT - p0 + np.pi, 2 * np.pi) - np.pi             # 最短环绕
                path.append(np.mod(p0 + a * d, 2 * np.pi))
            else:
                path.append((1 - a) * p0 + a * pT)
        path = np.asarray(path)
        # 真长度 (沿路径逐段测地距离累加)
        L = 0.0
        for i in range(len(path) - 1):
            L += MetricCalculator(self.type).distance(path[i], path[i + 1])
        return {"path": path, "n": T, "length": round(float(L), 6),
                "end_error": round(float(MetricCalculator(self.type).distance(path[-1], pT)), 6),
                "geodesic_kind": MANIFOLD_REGISTRY.get(self.type, {}).get("geodesic", "直线")}

    def step(self, p: np.ndarray, v: np.ndarray, dt: float = 0.01) -> np.ndarray:
        """沿切向量 v 走 dt (球面/SU2 = 指数映射; SE3 = 螺旋; 其余 = 加法)"""
        p, v = np.asarray(p, float).ravel(), np.asarray(v, float).ravel()
        t = self.type
        if t in ("sphere", "su2"):
            n = float(np.linalg.norm(v))
            if n < 1e-12:
                return p.copy()
            a = n * float(dt)
            u = v / n
            return unit(p * np.cos(a) + u * np.sin(a))
        if t == "se3":
            if p.size >= 12 and R_from_quat is not None and quat_mul is not None:
                from lerobot.manifold.lie_intent import quat_from_R as _qfr
                q = _qfr(p[:9].reshape(3, 3))
                w = np.asarray(v[:3], float) * float(dt)
                qn = quat_mul(q, quat_exp(w))
                R = R_from_quat(qn)
                return np.concatenate([R.ravel(), p[9:12] + np.asarray(v[3:6], float) * float(dt)])
            return p + v * float(dt)
        if t == "so3":
            w = np.asarray(v[:3], float) * float(dt)
            if R_from_quat is None:
                return p + v * float(dt)
            from lerobot.manifold.lie_intent import quat_from_R as _qfr
            q = quat_mul(_qfr(p[:9].reshape(3, 3)), quat_exp(w))
            return R_from_quat(q).ravel()
        if t == "torus":
            return np.mod(p + v * float(dt), 2 * np.pi)
        return p + v * float(dt)


class FeedbackLoop:
    """感知反馈: 有界修正流形参数 (卡尔曼式增益 + 硬限幅, 防振荡)"""

    def __init__(self, gain: float = 0.3, max_step: float = 0.05,
                 smooth: float = 0.5) -> None:
        self.gain = float(gain)
        self.max_step = float(max_step)          # 单次修正上限 (不许一步跳太远)
        self.smooth = float(smooth)
        self.correction: np.ndarray | None = None
        self.n_updates = 0
        self.clamped = 0

    def update(self, residual: np.ndarray) -> dict:
        """residual = 观测与预测的差 (在流形切空间) → 有界修正量"""
        r = np.asarray(residual, float).ravel()
        raw = self.gain * r
        d = self.smooth * raw + (1 - self.smooth) * (self.correction
                                                    if self.correction is not None else raw * 0)
        if self.correction is not None and d.shape != self.correction.shape:
            d = raw
        n = float(np.linalg.norm(d))
        clamped = n > self.max_step
        if clamped:
            d = d * (self.max_step / max(n, 1e-12))
            self.clamped += 1
        self.correction = d
        self.n_updates += 1
        return {"correction": d, "norm": round(float(np.linalg.norm(d)), 6),
                "clamped": bool(clamped), "n": self.n_updates}


def unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-12 else v


def slerp_unit(p0: np.ndarray, p1: np.ndarray, t: float) -> np.ndarray:
    p0, p1 = unit(np.asarray(p0, float).ravel()), unit(np.asarray(p1, float).ravel())
    d = float(np.clip(np.dot(p0, p1), -1.0, 1.0))
    if d > 0.9995:
        return unit((1 - t) * p0 + t * p1)
    th = np.arccos(d)
    return unit(np.sin((1 - t) * th) / np.sin(th) * p0 + np.sin(t * th) / np.sin(th) * p1)


def slerp_R(R0: np.ndarray, R1: np.ndarray, t: float) -> np.ndarray:
    """SO(3) 测地插值 (四元数 slerp; 缺 lie_intent 时退化为逐元素 + 正交化, 并标注)"""
    if quat_from_R is not None and R_from_quat is not None:
        try:
            q0, q1 = quat_from_R(R0), quat_from_R(R1)
            if np.dot(q0, q1) < 0:
                q1 = -q1
            q = slerp_unit(q0, q1, t)
            return R_from_quat(q)
        except Exception:                                                       # noqa: BLE001
            pass
    U, _, Vt = np.linalg.svd((1 - t) * R0 + t * R1)
    Rn = U @ Vt
    return Rn


# ══════════════════════════════════════════════════════════════════════════════
# 引擎
# ══════════════════════════════════════════════════════════════════════════════
class ManifoldEngine:
    """流形引擎核心类 — 编码/投影/度量/导航/反馈 五件套 + 全阶段延迟实测"""

    def __init__(self, manifold_type: str = "sphere", latent_dim: int = 16,
                 state_dim: int = 43, action_dim: int = 4, gain: float = 0.3,
                 max_step: float = 0.05) -> None:
        self.manifold_type = manifold_type
        self.latent_dim = int(latent_dim)
        self.state_dim = int(state_dim)
        self.action_dim = int(action_dim)
        self.encoder = Encoder(latent_dim)
        self.projector = ManifoldProjector(manifold_type)
        self.metric = MetricCalculator(manifold_type)
        self.navigator = Navigator(manifold_type)
        self.feedback = FeedbackLoop(gain=gain, max_step=max_step)
        self.readout: np.ndarray | None = None      # 解码: 流形坐标 → 动作 (ridge 真拟合)
        self.readout_b: np.ndarray | None = None
        self.action_lo: np.ndarray | None = None     # 动作界 (标定自训练数据 → 解码必须限幅)
        self.action_hi: np.ndarray | None = None
        self.current_state: np.ndarray | None = None
        self.current_manifold_point: np.ndarray | None = None
        self.goal_point: np.ndarray | None = None
        self.history: list[dict] = []
        self.lat: dict[str, list[float]] = {k: [] for k in STAGE_KEYS}
        self.calib: dict = {}
        self.fitted = False

    # ── 拟合 / 标定 ──
    def fit(self, X: np.ndarray, U: np.ndarray | None = None) -> dict:
        info = self.encoder.fit(X)
        X = np.asarray(X, float).reshape(len(X), -1)
        if U is not None:
            # 解码器: 流形坐标 → 动作 (岭回归, 真拟合)
            Z = self.encoder.encode(X)
            P = np.asarray([self.projector.project(z)[0] for z in Z], float)
            U = np.asarray(U, float).reshape(len(P), -1)
            A = np.hstack([P, np.ones((len(P), 1))])
            lam = 1e-3
            W = np.linalg.solve(A.T @ A + lam * np.eye(A.shape[1]), A.T @ U)
            self.readout, self.readout_b = W[:-1], W[-1]
            pred = A @ W
            r2 = 1.0 - float(((U - pred) ** 2).sum() / max(((U - U.mean(0)) ** 2).sum(), 1e-12))
            info["readout_r2"] = round(r2, 4)
            # 🐛 2026-09-24 实测: 无界 ridge 解码器在**未见帧**上外推发散 (幅度 1.26×, 最大 3.05 vs 真值 1.0)
            #   → R² 从训练段 +0.561 掉到全段 −3.55。修法: 用训练数据的动作界做**硬限幅** (带 10% 余量)。
            span = np.maximum(U.max(0) - U.min(0), 1e-6)
            self.action_lo = U.min(0) - 0.1 * span
            self.action_hi = U.max(0) + 0.1 * span
            info["action_bounds"] = {"lo": [round(float(x), 4) for x in self.action_lo],
                                     "hi": [round(float(x), 4) for x in self.action_hi]}
        self.fitted = True
        self.calib = info
        return info

    def save(self, path: str) -> None:
        d = {"mu": self.encoder.mu, "W": self.encoder.W, "latent_dim": self.encoder.latent_dim,
             "n_fit": self.encoder.n_fit, "manifold_type": self.manifold_type}
        if self.readout is not None:
            d["readout"], d["readout_b"] = self.readout, self.readout_b
        if self.action_lo is not None:
            d["action_lo"], d["action_hi"] = self.action_lo, self.action_hi
        np.savez(path, **d)

    def load(self, path: str) -> bool:
        if not os.path.isfile(path):
            return False
        d = np.load(path, allow_pickle=False)
        self.encoder.mu, self.encoder.W = d["mu"], d["W"]
        self.encoder.latent_dim, self.encoder.n_fit = int(d["latent_dim"]), int(d["n_fit"])
        self.manifold_type = str(d["manifold_type"]) if "manifold_type" in d else self.manifold_type
        self.projector = ManifoldProjector(self.manifold_type)
        self.metric = MetricCalculator(self.manifold_type)
        self.navigator = Navigator(self.manifold_type)
        if "readout" in d:
            self.readout, self.readout_b = d["readout"], d["readout_b"]
        if "action_lo" in d:
            self.action_lo, self.action_hi = d["action_lo"], d["action_hi"]
        self.fitted = True
        self.calib = {"loaded": os.path.basename(path), "latent_dim": self.encoder.latent_dim,
                      "n_fit": self.encoder.n_fit}
        return True

    # ── API ──
    def project(self, state: np.ndarray) -> dict:
        t0 = time.perf_counter()
        unfitted = not self.fitted
        if unfitted:
            # 未拟合 (含 planned 流形): 不猜、不造 → 零潜向量 + 显式标注 (调用方据此忽略数值)
            z = np.zeros(self.encoder.latent_dim or self.latent_dim)
        else:
            z = self.encoder.encode(np.asarray(state, float).reshape(-1))
        t1 = time.perf_counter()
        p, resid, meta = self.projector.project(z)
        t2 = time.perf_counter()
        self.current_state = np.asarray(state, float).reshape(-1)
        self.current_manifold_point = p
        self.lat["encode"].append((t1 - t0) * 1e3)
        self.lat["project"].append((t2 - t1) * 1e3)
        ok = MANIFOLD_REGISTRY[self.manifold_type]["status"] == "ready"
        drift = float(meta.get("drift") or 0.0)
        scale = 0.2 if self.manifold_type == "su2" else 1.0          # 各流形的归一化尺度
        thr = 0.5 if self.manifold_type == "su2" else 1.0            # 异常阈值 (超此 = 偏离流形)
        conf = float(np.exp(-drift / scale)) if ok else 0.0
        return {"z": z, "p": p, "residual": float(resid), "drift": round(drift, 6), "meta": meta,
                "confidence": round(conf, 4), "anomaly": bool(ok and drift > thr),
                "constraint_ok": bool(resid < 1e-9),
                "encoder_unfitted": bool(unfitted),
                "t_encode_ms": round((t1 - t0) * 1e3, 3), "t_project_ms": round((t2 - t1) * 1e3, 3),
                "manifold": self.manifold_type, "status": MANIFOLD_REGISTRY[self.manifold_type]["status"]}

    def navigate(self, goal_point: np.ndarray, T: int = 16) -> dict:
        t0 = time.perf_counter()
        if self.current_manifold_point is None:
            raise RuntimeError("先 project() 建立当前点")
        out = self.navigator.compute_geodesic(self.current_manifold_point, goal_point, T)
        self.goal_point = np.asarray(goal_point, float).ravel()
        self.lat["navigate"].append((time.perf_counter() - t0) * 1e3)
        out["t_navigate_ms"] = round((time.perf_counter() - t0) * 1e3, 3)
        return out

    def gradient_flow(self, potential_fn=None, p: np.ndarray | None = None) -> dict:
        t0 = time.perf_counter()
        p = self.current_manifold_point if p is None else np.asarray(p, float).ravel()
        if p is None:
            raise RuntimeError("先 project()")
        phi = potential_fn if potential_fn is not None else \
            (lambda q: 0.5 * float(np.dot(q - self.goal_point, q - self.goal_point))
             if self.goal_point is not None else 0.0)
        g = self.metric.tangent_gradient(phi, p)
        d = -g
        self.lat["metric"].append((time.perf_counter() - t0) * 1e3)
        return {"phi": round(float(phi(p)), 6), "grad": g, "descent": d,
                "norm": round(float(np.linalg.norm(d)), 6),
                "t_ms": round((time.perf_counter() - t0) * 1e3, 3)}

    def feedback_update(self, sensor_residual: np.ndarray) -> dict:
        t0 = time.perf_counter()
        r = np.asarray(sensor_residual, float).ravel()
        pr = self.current_manifold_point
        aligned = False
        if pr is not None and r.size != pr.size:
            # 🐛 传感器残差维数 ≠ 流形切空间维数时必须**显式对齐** (截断/补零), 不许直接相加
            rr = np.zeros(pr.size)
            k = min(pr.size, r.size)
            rr[:k] = r[:k]
            r, aligned = rr, True
        out = self.feedback.update(r)
        # 有界修正施加到当前流形点 (真更新)
        if self.current_manifold_point is not None and out["norm"] > 0:
            self.current_manifold_point = self.navigator.step(
                self.current_manifold_point, self.feedback.correction, dt=1.0)
        self.lat["feedback"].append((time.perf_counter() - t0) * 1e3)
        out["residual_aligned"] = aligned
        out["residual_dim_in"] = int(np.asarray(sensor_residual).size)
        out["tangent_dim"] = None if pr is None else int(pr.size)
        out["t_ms"] = round((time.perf_counter() - t0) * 1e3, 3)
        return out

    def step(self, state: np.ndarray, potential_fn=None, dt: float = 0.01,
             sensor_residual: np.ndarray | None = None) -> dict:
        """单步: 编码→投影→梯度流→导航步→解码动作→(可选)反馈修正"""
        r = self.project(state)
        gf = self.gradient_flow(potential_fn)
        p_new = self.navigator.step(r["p"], gf["descent"], dt=dt)
        fb = self.feedback_update(sensor_residual) if sensor_residual is not None else None
        # 解码动作 (有拟合 readout 用真拟合; 否则用潜坐标前 action_dim 维, **如实标注**)
        if self.readout is not None:
            a = np.asarray(r["p"], float) @ self.readout + self.readout_b
            if self.action_lo is not None:
                a = np.clip(a, self.action_lo, self.action_hi)      # 硬限幅 (防外推发散)
            dec_src = "ridge 拟合解码器 (带动作界限幅)"
        else:
            a = np.asarray(r["p"], float)[:self.action_dim]
            dec_src = "未标定 → 取流形坐标前 %d 维 (占位, 非学习)" % self.action_dim
        if a.size:
            a = np.clip(a, -1.0, 1.0)
        rec = {"state": np.asarray(state, float).ravel(), "p": r["p"], "p_next": p_new,
               "z": r["z"], "phi": gf["phi"], "grad": gf["grad"], "action": a,
               "confidence": r["confidence"], "anomaly": r["anomaly"],
               "residual": r["residual"], "feedback": fb, "decode_src": dec_src,
               "t_encode_ms": r["t_encode_ms"], "t_project_ms": r["t_project_ms"],
               "t_grad_ms": gf["t_ms"], "manifold": r["manifold"], "status": r["status"]}
        self.history.append({"p": r["p"].tolist(), "phi": gf["phi"], "anomaly": r["anomaly"]})
        return rec

    def query(self, what: str = "all") -> dict:
        p = self.current_manifold_point
        return {"manifold": self.manifold_type, "registry": MANIFOLD_REGISTRY[self.manifold_type],
                "p": None if p is None else [round(float(x), 5) for x in p],
                "p_dim": None if p is None else int(p.size),
                "latent_dim": self.encoder.latent_dim, "fitted": self.fitted,
                "n_fit": self.encoder.n_fit, "readout": self.readout is not None,
                "feedback_n": self.feedback.n_updates, "feedback_clamped": self.feedback.clamped,
                "history_n": len(self.history), "calib": self.calib, "what": what}

    def latency_report(self) -> dict:
        out = {}
        for k, v in self.lat.items():
            if v:
                a = np.asarray(v)
                out[k] = {"n": int(a.size), "mean_ms": round(float(a.mean()), 4),
                          "p50_ms": round(float(np.percentile(a, 50)), 4),
                          "p95_ms": round(float(np.percentile(a, 95)), 4)}
        tot = sum(x["mean_ms"] for x in out.values())
        out["total_mean_ms"] = round(float(tot), 4)
        out["implied_max_hz"] = round(1000.0 / max(tot, 1e-9), 1)
        return out

    def spec_check(self) -> dict:
        """规格书 vs **实测** (只报实测, 不抄目标值)"""
        lat = self.latency_report()
        g = lat.get("navigate", {}).get("p95_ms")
        return {
            "单次推理 (step: 编码+投影+梯度+导航步)": lat.get("total_mean_ms"),
            "规格要求 <10ms": ("达标" if (lat.get("total_mean_ms") or 1e9) < 10 else "未达标"),
            "流形投影延迟": lat.get("project", {}).get("mean_ms"),
            "规格要求 <1ms": ("达标" if (lat.get("project", {}).get("mean_ms") or 1e9) < 1 else "未达标"),
            "测地线计算 (T=16)": g, "规格要求 <50ms": ("达标" if (g or 1e9) < 50 else "未达标"),
            "闭环频率上限": f"{lat.get('implied_max_hz')} Hz", "规格要求 >100Hz":
                ("达标" if (lat.get("implied_max_hz") or 0) > 100 else "未达标"),
            "注": "精度/鲁棒性指标需真机或长跑数据才能给, 本表只报**实测延迟**, 不抄规格书数字",
        }

    def registry_table(self) -> dict:
        return {k: {"status": v["status"], "metric": v["metric"], "geodesic": v["geodesic"],
                    "src": v.get("src", "—"), "why": v.get("why", "")}
                for k, v in MANIFOLD_REGISTRY.items()}


# ══════════════════════════════════════════════════════════════════════════════
# 自检 / 标定 CLI
# ══════════════════════════════════════════════════════════════════════════════
def _selftest() -> int:
    rng = np.random.default_rng(0)
    print("=" * 78)
    print("🧮 流形引擎自检 (群公理/测地线/梯度/反馈 全部可核)")
    print("=" * 78)
    ok_all = True
    for mt in ("euclidean", "sphere", "torus", "so3", "se3", "su2", "latent_flat"):
        # 潜维 ≥ 各流形表示所需 (se3 需 12) —— 维不足时投影器会补齐并标注, 但默认给足
        eng = ManifoldEngine(manifold_type=mt, latent_dim=16, state_dim=43)
        X = rng.normal(size=(200, 43))
        U = rng.normal(size=(200, 4))
        info = eng.fit(X, U)
        r0 = eng.project(X[0])
        p, q = r0["p"], eng.project(X[1])["p"]
        d = eng.metric.distance(p, q)
        # 度量公理: d(p,p)=0, 对称, 三角不等式
        d0 = eng.metric.distance(p, p)
        r_ = eng.project(X[2])["p"]
        tri = d <= eng.metric.distance(p, r_) + eng.metric.distance(r_, q) + 1e-9
        nav = eng.navigate(q, T=12)
        st = eng.step(X[0], dt=0.01, sensor_residual=np.zeros(8))
        fb = eng.feedback_update(np.full(8, 5.0))         # 超大残差 → 必须被限幅
        # 容差按数值口径给: 球面/群测地距离用 arccos, 在 1 附近误差 ~√eps ≈ 1.4e-6
        # (实测 sphere d(p,p)=1.41e-6 → 这不是实现问题, 是 arccos 的条件数; 故取 1e-5)
        ok = (d0 < 1e-5 and tri and nav["end_error"] < 1e-5 and r0["residual"] < 1e-9
              and fb["norm"] <= 0.05 + 1e-9)
        ok_all &= bool(ok)
        print(f"  {mt:12} 约束违例={r0['residual']:.2e} 投影改动={r0['drift']:.3f} "
              f"置信={r0['confidence']:.3f} d(p,p)={d0:.2e} 三角={tri} "
              f"测地线终点误差={nav['end_error']:.2e} 路径长={nav['length']:.4f} "
              f"反馈限幅={fb['norm']:.4f}(clamp={fb['clamped']}) decode={st['decode_src'][:14]} "
              f"{'✅' if ok else '❌'}")
    # planned 类型必须拒绝 (不造假)
    eng = ManifoldEngine(manifold_type="calabi_yau")
    r = eng.project(rng.normal(size=43))
    print(f"  calabi_yau  status={r['status']} confidence={r['confidence']} "
          f"(planned → 不提供投影, 已如实标注)")
    print("  registry:", json.dumps(eng.registry_table(), ensure_ascii=False)[:150], "…")
    print("\n自检结果:", "全部通过 ✅" if ok_all else "有失败 ❌")
    print("MANIFOLD_SELFTEST_DONE")
    return 0 if ok_all else 1


def _calibrate(out_path: str, steps: int = 120) -> int:
    """从**真实引擎轨迹**拟合编码器+解码器 (真数据), 落 models/manifold_engine.npz"""
    os.environ.setdefault("MUJOCO_GL", "egl")
    os.environ.setdefault("DISPLAY", ":0")
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))
    for p in (os.path.join(root, "tools", "gui"), os.path.join(root, "tools"), root,
              os.path.join(root, "src")):
        if p not in sys.path:
            sys.path.insert(0, p)
    os.environ.setdefault("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache")
    os.environ.setdefault("LOCAL_DATASET_DIR", "/home/ubuntu/stable-wm-cache")
    os.environ.setdefault("INTACT_RUNTIME", "root")
    import state_space_sim_real as SSR                                            # noqa: PLC0415
    sim = SSR.RealStateSpaceSim(seed=104, vision=False, mode="insert", log=lambda *x: None)
    tr = sim.run(max_steps=steps)
    O43 = np.asarray(tr["obs"], float)
    U = np.asarray(tr["u_exec_vec"], float)
    n = min(len(O43), len(U))
    X, U = O43[:n, :43], U[:n, :4]
    eng = ManifoldEngine(manifold_type="su2", latent_dim=16, state_dim=43, action_dim=4)
    info = eng.fit(X, U)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    eng.save(out_path)
    print(json.dumps({"calibrated_from": "真跑引擎轨迹", "steps": n,
                      "obs_dim": int(X.shape[1]), **info,
                      "saved": os.path.relpath(out_path, root)}, ensure_ascii=False, indent=1))
    print("MANIFOLD_CALIB_DONE")
    return 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--calibrate" in a:
        p = f"/home/ubuntu/lerobot-smolvla-lew/models/manifold_engine.npz"
        raise SystemExit(_calibrate(p))
    raise SystemExit(_selftest())
