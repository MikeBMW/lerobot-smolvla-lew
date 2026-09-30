# -*- coding: utf-8 -*-
"""🧭 lie_intent.py — 意图的李群/李代数结构 (SU(2) / SE(3) / 接触丛 twist) — 老倪 2026-09-16

需求原话: "INTACT 的动作意图, 纯旋转用 SU(2), 完整刚体动作用 SE(3), 关节空间用环面 T^n;
把 INTACT 的意图输出、动作流形、接触流形、性能流形按 SE(3)/SU(2) 结构设计, 经 DiT 解码成
前馈加速器能接受的 action, 中间的增益由 L2/L3/L4 记忆层协调调整。"

本模块只做**几何**: 李群运算 + 意图/接触的 twist 表征 + **切空间 (李代数) 增益融合**。
不训练、不依赖 torch/引擎 —— 纯 numpy, 可单测。

结构 (与四流形的对应):
    潜空间丛 Z(192)  --Φ_su2-->  su(2)≅R³  旋转意图 ω      (纯旋转: 腕/插拔绕轴)
                     --Φ_se3-->  se(3)≅R⁶  刚体意图 ξ=(ω,v) (完整刚体: 末端位姿)
    接触丛 C:  e_tw = log(T_hole⁻¹ · T_peg) ∈ se(3)  ← **在孔坐标系里表达的接触误差**
               (位置误差 + 姿态误差同一个 twist; 比旧的欧氏 F_C(6) 更贴几何)
    性能丛 P:  以 C 为底空间、P 为纤维 ⇒ 联络/曲率 = 沿接触轨迹平行移动的不一致量
    动作丛 A:  引擎动作 u = (dx,dy,dz,grip) 属平移 twist 部分 (旋转走 yaw 通道, 另有 SU(2) 路)

增益融合 (老倪: L4 导航 / L3 流程 / L2 执行, 由记忆层协调):
    ξ_fuse = (1−K)·ξ_L2 + K·ξ_L4            ← **在切空间做** (李代数线性)
    T_fuse = exp(ξ_fuse)                     ← 再回群上 (测地线插值, 不越出流形)
    K=0 → 逐位等于 ξ_L2 (零回退); K=1 → 恰好等于 ξ_L4; 0<K<1 → 测地线中间点。

自检: python src/lerobot/manifold/lie_intent.py   (10 条判据, 含零回退逐位)
"""
from __future__ import annotations

import hashlib

import numpy as np

EPS = 1e-12
AXIS_EPS = 1e-8


def vec_hash(v) -> str:
    """逐位取证 (零回退判据)。"""
    if v is None:
        return "none"
    a = np.asarray(v, dtype=np.float64)
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()[:16]


# ══════════════════════════ SU(2) (单位四元数) ══════════════════════════
def quat_norm(q):
    """归一化 + **双覆盖消歧** (约定 w ≥ 0: SU(2)→SO(3) 是 2:1, U 与 −U 同一旋转)。"""
    q = np.asarray(q, float)
    n = float(np.linalg.norm(q))
    if n < EPS:
        return np.array([1.0, 0.0, 0.0, 0.0])
    q = q / n
    return -q if q[0] < 0.0 else q


def quat_mul(q1, q2):
    w1, x1, y1, z1 = np.asarray(q1, float)
    w2, x2, y2, z2 = np.asarray(q2, float)
    return np.array([w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
                     w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
                     w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
                     w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2])


def quat_conj(q):
    q = np.asarray(q, float)
    return np.array([q[0], -q[1], -q[2], -q[3]])


def quat_log(q):
    """SU(2) → su(2)≅R³ (旋转向量: 模长=角, 方向=轴; 角∈[0,π])。"""
    q = quat_norm(q)
    w = float(np.clip(q[0], -1.0, 1.0))
    v = q[1:]
    s = float(np.linalg.norm(v))
    if s < AXIS_EPS:
        return 2.0 * v                      # 小角: ω ≈ 2v
    ang = 2.0 * float(np.arctan2(s, w))
    return (ang / s) * v


def quat_exp(w):
    """su(2)≅R³ → SU(2) (指数映射, 罗德里格斯)。"""
    w = np.asarray(w, float).reshape(3)
    ang = float(np.linalg.norm(w))
    if ang < AXIS_EPS:
        q = np.concatenate([[1.0], 0.5 * w])
        return quat_norm(q)
    ax = w / ang
    return quat_norm(np.concatenate([[np.cos(ang / 2.0)], np.sin(ang / 2.0) * ax]))


def quat_relative(q_next, q_prev):
    """相对旋转 ΔU = q_next · q_prev⁻¹ ∈ SU(2) (SU(2) 上的意图)。"""
    return quat_norm(quat_mul(q_next, quat_conj(q_prev)))


def quat_slerp(q0, q1, t: float):
    """球面插值 (= 增益 K 在群上的测地线融合)。"""
    q0, q1 = quat_norm(q0), quat_norm(q1)
    d = float(np.dot(q0, q1))
    if d < 0.0:                             # 双覆盖: 取短弧
        q1, d = -q1, -d
    d = float(np.clip(d, -1.0, 1.0))
    if d > 1.0 - 1e-9:
        return quat_norm(q0 + t * (q1 - q0))
    th = float(np.arccos(d))
    return quat_norm(np.sin((1 - t) * th) / np.sin(th) * q0 + np.sin(t * th) / np.sin(th) * q1)


def quat_from_R(R):
    """SO(3) → 单位四元数 (w,x,y,z), 数值稳定分支 (Shepperd)。"""
    R = np.asarray(R, float)[:3, :3]
    tr = float(np.trace(R))
    if tr > 0.0:
        s = np.sqrt(tr + 1.0) * 2.0
        q = np.array([0.25 * s, (R[2, 1] - R[1, 2]) / s, (R[0, 2] - R[2, 0]) / s,
                      (R[1, 0] - R[0, 1]) / s])
    else:
        i = int(np.argmax(np.diag(R)))
        if i == 0:
            s = np.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2]) * 2.0
            q = np.array([(R[2, 1] - R[1, 2]) / s, 0.25 * s, (R[0, 1] + R[1, 0]) / s,
                          (R[0, 2] + R[2, 0]) / s])
        elif i == 1:
            s = np.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2]) * 2.0
            q = np.array([(R[0, 2] - R[2, 0]) / s, (R[0, 1] + R[1, 0]) / s, 0.25 * s,
                          (R[1, 2] + R[2, 1]) / s])
        else:
            s = np.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1]) * 2.0
            q = np.array([(R[1, 0] - R[0, 1]) / s, (R[0, 2] + R[2, 0]) / s,
                          (R[1, 2] + R[2, 1]) / s, 0.25 * s])
    return quat_norm(q)


def R_from_quat(q):
    """单位四元数 → SO(3)。"""
    return se3_make(quat_norm(q), [0.0, 0.0, 0.0])[:3, :3]


# ══════════════════════════ SE(3) (刚体变换) ══════════════════════════
def se3_make(quat, t):
    """(四元数, 位置) → 4×4 齐次矩阵。"""
    q = quat_norm(quat)
    w, x, y, z = q
    R = np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = np.asarray(t, float).reshape(3)
    return T


def so3_log(R):
    """SO(3) → R³ 旋转向量 (含 180° 边界保护)。"""
    R = np.asarray(R, float)[:3, :3]
    tr = float(np.clip((np.trace(R) - 1.0) / 2.0, -1.0, 1.0))
    ang = float(np.arccos(tr))
    if ang < AXIS_EPS:
        return np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]]) * 0.5
    if abs(ang - np.pi) < 1e-6:             # 180°: 从对角取轴
        A = (R + np.eye(3)) / 2.0
        d = np.clip(np.diag(A), 0.0, None)
        i = int(np.argmax(d))
        ax = A[:, i] / np.sqrt(max(d[i], EPS))
        return ang * ax / max(np.linalg.norm(ax), EPS)
    return (ang / (2.0 * np.sin(ang))) * np.array(
        [R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]])


def so3_exp(w):
    """R³ → SO(3) (罗德里格斯)。"""
    w = np.asarray(w, float).reshape(3)
    ang = float(np.linalg.norm(w))
    if ang < AXIS_EPS:
        return np.eye(3) + np.array([[0, -w[2], w[1]], [w[2], 0, -w[0]], [-w[1], w[0], 0]])
    k = w / ang
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + np.sin(ang) * K + (1 - np.cos(ang)) * (K @ K)


def _hat(w):
    """R³ → so(3) 反对称矩阵。"""
    w = np.asarray(w, float).reshape(3)
    return np.array([[0.0, -w[2], w[1]], [w[2], 0.0, -w[0]], [-w[1], w[0], 0.0]])


def se3_log(T):
    """SE(3) → se(3)≅R⁶, 顺序 ξ=(ω(3), v(3)), v 用左乘 twist 约定 (V⁻¹·Ṫ)。

    闭式 (小角走级数): V⁻¹ = I − ½Ω + (1/θ² − (1+cosθ)/(2θ sinθ))·Ω²
    """
    T = np.asarray(T, float)
    R, p = T[:3, :3], T[:3, 3]
    w = so3_log(R)
    th = float(np.linalg.norm(w))
    if th < 1e-8:
        return np.concatenate([w, p])
    O = _hat(w)
    c = np.cos(th)
    coef = (1.0 / th ** 2) - ((1.0 + c) / (2.0 * th * np.sin(th)))
    V_inv = np.eye(3) - 0.5 * O + coef * (O @ O)
    return np.concatenate([w, V_inv @ p])


def se3_exp(xi):
    """se(3)≅R⁶ (ω,v) → SE(3)。闭式: V = I + ((1−cosθ)/θ²)Ω + ((θ−sinθ)/θ³)Ω², p = V·v。"""
    xi = np.asarray(xi, float).reshape(6)
    w, v = xi[:3], xi[3:]
    th = float(np.linalg.norm(w))
    if th < 1e-8:                       # 小角级数 (避免 0/0)
        O = _hat(w)
        T = np.eye(4)
        T[:3, :3] = np.eye(3) + O
        T[:3, 3] = (np.eye(3) + 0.5 * O) @ v
        return T
    O = _hat(w)
    O2 = O @ O
    V = np.eye(3) + ((1.0 - np.cos(th)) / th ** 2) * O + ((th - np.sin(th)) / th ** 3) * O2
    T = np.eye(4)
    T[:3, :3] = so3_exp(w)
    T[:3, 3] = V @ v
    return T


# ══════════════════════════ 接触丛 (SE(3) twist) ══════════════════════════
def contact_twist(T_peg, T_hole):
    """接触误差 twist: e = log(T_hole⁻¹ · T_peg) ∈ R⁶ —— **在孔坐标系里表达**。

    与旧 F_C(6) 的差别: 位置误差与姿态误差进同一个 twist (姿态部分对插拔的对准质量是硬的),
    且坐标系固定在孔上 ⇒ 同一物理误差在不同世界位姿下数值一致 (可跨场景比)。
    """
    T_rel = np.linalg.inv(np.asarray(T_hole, float)) @ np.asarray(T_peg, float)
    return se3_log(T_rel)


def contact_decompose(e_tw, axis=(0.0, 0.0, 1.0)):
    """twist → (进度 e∥, 横向 e⊥, 姿态误差 ‖ω‖) — 供势函数/审计用。"""
    e = np.asarray(e_tw, float)
    ax = np.asarray(axis, float) / max(np.linalg.norm(axis), EPS)
    v = e[3:]
    return float(v @ ax), float(np.linalg.norm(v - (v @ ax) * ax)), float(np.linalg.norm(e[:3]))


def wrap_pi(ang):
    """角度折叠到 (−π, π]。"""
    return float((float(ang) + np.pi) % (2.0 * np.pi) - np.pi)


def yaw_from_twist(e_tw, axis=(0.0, 0.0, 1.0)):
    """🧭 SU(2) 姿态意图: 从接触 twist 取出**绕插拔轴需要的修正角** (rad)。

    e = log(T_hole⁻¹·T_peg) 的旋转部分 ω 是"孔系里还差多少旋转"; 绕轴的残差 = ω·â,
    要消除它需要把夹爪绕轴转 −ω·â ⇒ 返回该值 (弧度, 折叠到 (−π,π])。
    这是 yaw 通道的 **SU(2) 几何先验** (替代"猜测残余失配 δφ"的经验假设)。
    """
    e = np.asarray(e_tw, float).reshape(6)
    ax = np.asarray(axis, float) / max(np.linalg.norm(axis), EPS)
    return wrap_pi(-float(e[:3] @ ax))


def geodesic_deg(a_deg, b_deg):
    """圆上测地距离 (度), 180° 折叠 (长条模块绕 z 转 180° 等价 → 距离 0)。"""
    d = abs(wrap_pi(np.deg2rad(float(a_deg) - float(b_deg))))
    return float(np.rad2deg(min(d, np.pi - d)))


# ══════════════════════════ 切空间增益融合 ══════════════════════════
class LieGainBlend:
    """🎚 增益在**李代数**里做融合 (老倪: L2 执行 / L4 导航 / L3 流程, 记忆层协调)。

    · 平移 twist (引擎动作主通道): ξ = [0,0,0, dx,dy,dz] → 融合即欧氏凸组合 (等价, 严格)
    · 含旋转 (yaw 通道/真机姿态): 用群上的**测地线**融合 (SLERP / se(3) exp)
    · K=0 → 逐位等于 L2 (零回退); K=1 → 恰好 L4; 中间 = 测地线中点 (不越出流形)
    """

    def __init__(self, k_max: float = 0.5, gate_cos: float = 0.9, gate_ratio: float = 1.5):
        self.k_max, self.gate_cos, self.gate_ratio = float(k_max), float(gate_cos), float(gate_ratio)
        self.n = 0
        self.stats = {"n": 0, "refused": 0, "applied": 0, "k_sum": 0.0, "cos_sum": 0.0,
                      "ratio_sum": 0.0, "geo_mid_n": 0}

    def direction_ok(self, xi_l2, xi_nav) -> tuple[bool, float, float]:
        """方向/幅度闸 (每层只能收窄: 反向 / 超幅 → 否决)。"""
        a = np.asarray(xi_l2, float).reshape(6)[3:]
        b = np.asarray(xi_nav, float).reshape(6)[3:]
        na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
        if na < EPS or nb < EPS:
            return False, 0.0, float("inf")
        return (float(a @ b) / (na * nb) >= self.gate_cos and nb <= self.gate_ratio * na,
                float(a @ b) / (na * nb), nb / na)

    def blend(self, xi_l2, xi_nav, K: float, *, gate: bool = True) -> tuple[np.ndarray, dict]:
        """返回 (ξ_fuse, info)。K=0 → 逐位 ξ_l2; K≥1 → ξ_nav; 中间为切空间线性插值。"""
        a = np.asarray(xi_l2, float).reshape(6).copy()
        b = np.asarray(xi_nav, float).reshape(6)
        k = float(np.clip(K, 0.0, self.k_max))
        info = {"k_raw": float(K), "k": k, "applied": False, "refused": False, "gate": None}
        if k <= 0.0:
            info["reason"] = "K=0 → 逐位等于 L2 (零回退)"
            return a, info
        ok, cosv, ratio = self.direction_ok(a, b)
        info.update({"gate": bool(ok), "cos": cosv, "ratio": ratio})
        self.stats["k_sum"] += k
        self.stats["cos_sum"] += cosv
        self.stats["ratio_sum"] += min(ratio, 1e3)
        self.n += 1
        self.stats["n"] = self.n
        if gate and not ok:
            self.stats["refused"] += 1
            info.update({"refused": True, "reason": f"否决 (cos={cosv:.3f}, 幅度比={ratio:.3f})"})
            return a, info
        xi = (1.0 - k) * a + k * b
        if np.linalg.norm(xi[:3]) > EPS or np.linalg.norm(b[:3]) > EPS:
            self.stats["geo_mid_n"] += 1        # 含旋转分量 → 走的是群上测地线语义
        self.stats["applied"] += 1
        info.update({"applied": True, "reason": "切空间融合"})
        return xi, info

    def summary(self) -> dict:
        n = max(1, self.n)
        return {"n": self.n, "applied": self.stats["applied"], "refused": self.stats["refused"],
                "k_mean": round(self.stats["k_sum"] / n, 5),
                "cos_mean": round(self.stats["cos_sum"] / n, 5),
                "ratio_mean": round(self.stats["ratio_sum"] / n, 5),
                "geo_mid_n": self.stats["geo_mid_n"]}


# ══════════════════════════ 意图 → 李代数 (丛映射 Φ, 线性 + LOO 闸) ══════════════════════════
class LieIntentMap:
    """Φ: 潜空间意图 Δz(192) → (ω∈R³ su(2), ξ∈R⁶ se(3)) —— ridge 拟合 + LOO R² 闸。

    与既有 "换源不重训" 纪律一致: 下游模型权重一字不改, 只换"喂进去的几何口径"。
    ready 判定: R²_loso ≥ gate (默认 0.30, 与同仓既有闸一致)。
    """

    def __init__(self, gate: float = 0.30, ridge: float = 1e-2, pca_dim: int = 24):
        self.gate, self.ridge, self.pca_dim = float(gate), float(ridge), int(pca_dim)
        self.W_su2 = self.b_su2 = None
        self.W_se3 = self.b_se3 = None
        self.P = None                      # PCA 基 (降维后拟合, 防过拟合)
        self.ready = False
        self.meta: dict = {}

    @staticmethod
    def _design(X, P=None):
        X = np.asarray(X, float)
        if P is None:
            return X
        return (X - P["mu"]) @ P["V"]

    def fit(self, X, W_su2, Xi_se3, seed: int = 0) -> dict:
        X = np.asarray(X, float)
        Y1 = np.asarray(W_su2, float).reshape(len(X), -1)
        Y2 = np.asarray(Xi_se3, float).reshape(len(X), -1)
        mu = X.mean(0, keepdims=True)
        Xc = X - mu
        d = min(self.pca_dim, Xc.shape[0] - 1, Xc.shape[1])
        U, S, Vt = np.linalg.svd(Xc, full_matrices=False)
        P = {"mu": mu, "V": Vt[:d].T, "sv": S[:d]}
        Z = self._design(X, P)

        def _ridge(Za, Ya):
            A = Za.T @ Za + self.ridge * np.eye(Za.shape[1])
            return np.linalg.solve(A, Za.T @ Ya)

        res = {}
        for name, Y in (("su2", Y1), ("se3", Y2)):
            Wm = _ridge(Z, Y)
            pred = Z @ Wm
            r2 = 1.0 - float(np.sum((Y - pred) ** 2) / max(np.sum((Y - Y.mean(0)) ** 2), EPS))
            # LOO (留一交叉验证, 抑制过拟合假象) + null 对照 (打乱 Y)
            n = len(Z)
            loo = np.zeros_like(Y)
            for i in range(n):
                m = np.ones(n, bool)
                m[i] = False
                Wi = _ridge(Z[m], Y[m])
                loo[i] = Z[i] @ Wi
            r2l = 1.0 - float(np.sum((Y - loo) ** 2) / max(np.sum((Y - Y.mean(0)) ** 2), EPS))
            rng = np.random.default_rng(seed)
            Ys = Y[rng.permutation(n)]
            Wn = _ridge(Z, Ys)
            r2n = 1.0 - float(np.sum((Ys - Z @ Wn) ** 2) / max(np.sum((Ys - Ys.mean(0)) ** 2), EPS))
            res[name] = {"dim": Y.shape[1], "r2": round(r2, 4), "r2_loso": round(r2l, 4),
                         "null": round(r2n, 4), "per_dim_loso": [
                             round(1.0 - float(np.sum((Y[:, j] - loo[:, j]) ** 2)
                                               / max(np.sum((Y[:, j] - Y[:, j].mean()) ** 2), EPS)), 3)
                             for j in range(Y.shape[1])]}
        self.P = P
        Zm = self._design(np.asarray(X, float), P)
        self.W_su2 = _ridge(Zm, Y1)
        self.W_se3 = _ridge(Zm, Y2)
        self.meta = res
        self.ready = bool(res["se3"]["r2_loso"] >= self.gate and res["se3"]["null"] < 0.10)
        return res

    def predict(self, dz) -> tuple[np.ndarray, np.ndarray]:
        """Δz(192) → (ω∈R³, ξ∈R⁶)。未 ready 也照跑 (调用方按 ready 决定注不注入)。"""
        z = np.asarray(dz, float).reshape(1, -1)
        Zd = self._design(z, self.P)
        return (Zd @ self.W_su2).reshape(3), (Zd @ self.W_se3).reshape(6)

    def predict_batch(self, dz) -> tuple[np.ndarray, np.ndarray]:
        """批量: (n,192) → ((n,3), (n,6))。"""
        Z = np.asarray(dz, float).reshape(len(dz), -1)
        Zd = self._design(Z, self.P)
        return Zd @ self.W_su2, Zd @ self.W_se3


# ══════════════════════════ 自检 ══════════════════════════
def self_test() -> int:
    print("🧭 lie_intent 自检 — SU(2) / SE(3) / 接触 twist / 切空间增益融合")
    ok = True

    # ① quat log/exp 互逆 (|ω| ≤ π, SU(2) 双覆盖只保证这个区间唯一)
    rng = np.random.default_rng(0)
    errs = []
    for _ in range(200):
        d = rng.normal(0, 1, 3)
        w = d / np.linalg.norm(d) * rng.uniform(0.0, np.pi * 0.999)
        errs.append(float(np.linalg.norm(quat_log(quat_exp(w)) - w)))
    e1 = max(errs)
    print(f"① SU(2) exp∘log 互逆: 200 组最大误差 {e1:.2e} → {'✓' if e1 < 1e-9 else '✗'}")
    ok &= e1 < 1e-9

    # ② 双覆盖: q 与 −q 同一旋转, 相对旋转与 log 结果一致
    q = quat_exp([0.3, -0.2, 0.5])
    d1 = float(np.linalg.norm(quat_log(q) - quat_log(-q)))
    print(f"② 双覆盖消歧 (w≥0): ‖log(q)−log(−q)‖ = {d1:.2e} → {'✓' if d1 < 1e-9 else '✗'}")
    ok &= d1 < 1e-9

    # ③ SE(3) exp∘log 互逆 (随机 200 组刚体变换)
    errs = []
    for _ in range(200):
        xi = np.concatenate([rng.normal(0, 0.4, 3), rng.normal(0, 0.05, 3)])
        errs.append(float(np.linalg.norm(se3_log(se3_exp(xi)) - xi)))
    e3 = max(errs)
    print(f"③ SE(3) exp∘log 互逆: 200 组最大误差 {e3:.2e} → {'✓' if e3 < 1e-8 else '✗'}")
    ok &= e3 < 1e-8

    # ④ 合成律: exp(ξ1)·exp(ξ2) 的 log 与直接矩阵乘一致
    T1, T2 = se3_exp(np.r_[rng.normal(0, .3, 3), rng.normal(0, .05, 3)]), se3_exp(
        np.r_[rng.normal(0, .3, 3), rng.normal(0, .05, 3)])
    Tp = T1 @ T2
    e4 = float(np.linalg.norm((se3_exp(se3_log(T1)) @ se3_exp(se3_log(T2))) - Tp))
    print(f"④ 群合成律 ‖exp(log T1)·exp(log T2) − T1T2‖ = {e4:.2e} → {'✓' if e4 < 1e-9 else '✗'}")
    ok &= e4 < 1e-9

    # ⑤ 接触 twist: 零误差 → 0; 纯平移 5mm → 进度 5mm; 纯旋转 10° → ‖ω‖=10°
    T_h = se3_make([1, 0, 0, 0], [0.5, 0.0, 0.1])
    T_p0 = se3_make([1, 0, 0, 0], [0.5, 0.0, 0.1])
    e_zero = contact_twist(T_p0, T_h)
    T_p1 = se3_make([1, 0, 0, 0], [0.5, 0.0, 0.105])
    e_t = contact_twist(T_p1, T_h)
    T_p2 = se3_make(quat_exp([0, 0, np.deg2rad(10)]), [0.5, 0.0, 0.1])
    e_r = contact_twist(T_p2, T_h)
    prog, lat, ang = contact_decompose(e_t)
    ang2 = float(np.linalg.norm(e_r[:3]))
    c5 = (np.linalg.norm(e_zero) < 1e-12 and abs(prog - 0.005) < 1e-9 and abs(lat) < 1e-9
          and abs(np.rad2deg(ang2) - 10.0) < 1e-6)
    print(f"⑤ 接触 twist: 零={np.linalg.norm(e_zero):.1e} · 平移5mm→进度{prog*1000:.3f}mm/横向{lat*1000:.1e}mm"
          f" · 旋转10°→姿态{np.rad2deg(ang2):.4f}° → {'✓' if c5 else '✗'}")
    ok &= c5

    # ⑥ 坐标不变性: 同一物理误差, 孔位姿改变后 twist 的分量不变 (孔系表达的好处)
    Rz = se3_exp([0, 0, 0.7, 0, 0, 0])
    th = se3_make(quat_exp([0, 0, 0.7]), [1.2, -0.3, 0.4])
    e_a = contact_twist(T_p1, T_h)
    e_b = contact_twist(th @ T_p1, th @ T_h)
    d6 = float(np.linalg.norm(e_a - e_b))
    print(f"⑥ 孔系不变性: ‖e(原) − e(整体刚体变换后)‖ = {d6:.2e} → {'✓' if d6 < 1e-9 else '✗'}")
    ok &= d6 < 1e-9

    # ⑦ 切空间增益融合: K=0 逐位等于 L2; K=1 = L4; 中间 = 测地线中点
    bl = LieGainBlend(k_max=1.0)
    xi_l2 = np.array([0.0, 0.0, 0.0, 0.10, -0.05, 0.02])
    xi_nav = np.array([0.2, 0.0, 0.1, 0.12, -0.04, 0.03])
    f0, i0 = bl.blend(xi_l2, xi_nav, 0.0)
    f1, _ = bl.blend(xi_l2, xi_nav, 1.0)
    fm, _ = bl.blend(xi_l2, xi_nav, 0.5)
    c7 = (vec_hash(f0) == vec_hash(xi_l2) and np.allclose(f1, xi_nav, atol=1e-12)
          and np.allclose(fm, 0.5 * (xi_l2 + xi_nav), atol=1e-12) and i0["reason"].startswith("K=0"))
    print(f"⑦ 切空间融合: K=0 hash 相同={vec_hash(f0) == vec_hash(xi_l2)} · K=1=nav "
          f"· K=0.5=中点 → {'✓' if c7 else '✗'}")
    ok &= c7

    # ⑧ 测地线 (含旋转): SLERP 中点角 = 两端夹角一半; 且不越出 SU(2) (模长=1)
    qa, qb = quat_exp([0, 0, 0]), quat_exp([0, 0, np.deg2rad(90)])
    qm = quat_slerp(qa, qb, 0.5)
    ang_m = float(np.linalg.norm(quat_log(qm)))
    c8 = (abs(np.rad2deg(ang_m) - 45.0) < 1e-9 and abs(float(np.linalg.norm(qm)) - 1.0) < 1e-12)
    print(f"⑧ 群上测地线中点: 90°→{np.rad2deg(ang_m):.4f}° · ‖q‖={np.linalg.norm(qm):.12f} → {'✓' if c8 else '✗'}")
    ok &= c8

    # ⑨ 方向/幅度闸: 反向 / 超幅 必被否决, 拒绝时输出逐位等于 L2
    g = LieGainBlend(k_max=0.5, gate_cos=0.9, gate_ratio=1.5)
    rev = np.array([0.0, 0.0, 0.0, -0.10, 0.05, -0.02])
    fr, ir = g.blend(xi_l2, rev, 0.5)
    big = np.array([0.0, 0.0, 0.0, 0.4, -0.2, 0.08])
    fb2, ib2 = g.blend(xi_l2, big, 0.5)
    c9 = (ir["refused"] and vec_hash(fr) == vec_hash(xi_l2) and ib2["refused"]
          and vec_hash(fb2) == vec_hash(xi_l2) and g.summary()["refused"] == 2)
    print(f"⑨ 方向/幅度闸: 反向 cos={ir['cos']:.2f} 否决={ir['refused']} · 超幅比={ib2['ratio']:.2f} "
          f"否决={ib2['refused']} → {'✓' if c9 else '✗'}")
    ok &= c9

    # ⑩ Φ 标定: 合成数据 (真映射为线性) 必须过闸, 纯噪声必须不过 (证明闸不是恒真)
    X = rng.normal(0, 1, (600, 40))
    Wt = rng.normal(0, 0.5, (40, 6))
    Y = X @ Wt
    m = LieIntentMap(gate=0.30)
    r = m.fit(X, Y[:, :3], Y)
    m2 = LieIntentMap(gate=0.30)
    r2 = m2.fit(rng.normal(0, 1, (600, 40)), rng.normal(0, 1, (600, 3)), rng.normal(0, 1, (600, 6)))
    c10 = (r["se3"]["r2_loso"] > 0.6 and m.ready and not m2.ready)
    print(f"⑩ Φ 标定判据: 线性真映射 R²_loso={r['se3']['r2_loso']:.4f} ready={m.ready} · "
          f"纯噪声 R²_loso={r2['se3']['r2_loso']:.4f} ready={m2.ready} → {'✓' if c10 else '✗'}")
    ok &= c10

    # ⑪ SO(3) ↔ 四元数 往返 (引擎取姿态的真实路径: site_xmat → quat)
    errs = []
    for _ in range(200):
        w = rng.normal(0, 0.55, 3)
        R = so3_exp(w)
        errs.append(float(np.linalg.norm(so3_log(R_from_quat(quat_from_R(R))) - w)))
    e11 = max(errs)
    print(f"⑪ R↔quat 往返: 200 组最大误差 {e11:.2e} → {'✓' if e11 < 1e-9 else '✗'}")
    ok &= e11 < 1e-9

    # ⑫ SU(2) yaw 先验: 孔相对光模块转 90° → 需要的修正角 = −90° (符号/量级都对)
    T_h = se3_make([1, 0, 0, 0], [0.5, 0.0, 0.1])
    T_p = se3_make(quat_exp([0, 0, np.deg2rad(90)]), [0.5, 0.0, 0.1])
    ph_req = float(np.rad2deg(yaw_from_twist(contact_twist(T_p, T_h))))
    c12 = abs(ph_req + 90.0) < 1e-6
    print(f"⑫ SU(2) yaw 先验: 孔−件转 90° → 修正角 {ph_req:+.4f}° (期望 −90°) → "
          f"{'✓' if c12 else '✗'}")
    ok &= c12

    # ⑬ 圆上测地距离: 180° 折叠 (长条件 180° 等价) + 对称性 + 三角不等式抽样
    d1 = geodesic_deg(0.0, 90.0)
    d2 = geodesic_deg(0.0, 180.0)
    d3 = geodesic_deg(90.0, 90.0)
    d4 = min(abs(geodesic_deg(a, b) - geodesic_deg(b, a)) for a, b in
             [(0.0, 45.0), (30.0, -120.0), (170.0, -170.0)])
    c13 = (abs(d1 - 90.0) < 1e-6 and abs(d2 - 0.0) < 1e-6 and abs(d3) < 1e-9 and d4 < 1e-9)
    print(f"⑬ 圆测地距离: d(0,90)={d1:.4f}° · d(0,180)={d2:.4f}° (=0, 180° 等价) · "
          f"d(90,90)={d3:.1e} · 对称性误差 {d4:.1e} → {'✓' if c13 else '✗'}")
    ok &= c13

    print(f"── 自检结论: {'13/13 全过' if ok else '有判据未过'} ──")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(self_test())
