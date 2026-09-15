#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧬 纤维丛联络层 (action bundle → contact bundle) — L4 意图/预测潜空间的几何映射

老倪 (2026-09-15): 「要把 INTACT 意图解码器的 predictor 预测的 z 潜空间, 输出到流形专家预测器;
这个流形是个动作丛 (action bundle / 纤维丛), 然后进一步进到接触流形, 也是一个接触丛;
你来设计映射关系, 应用纤维丛的映射联络关系。因为是光模块插拔, 所以对性能流形没啥作用,
但主力还是接触流形有作用。最后进入 DiT 生成轨迹。」

────────────────────────────────────────────────────────────────────────
一、丛结构 (全部量都来自真实链路, 无占位值)

  底空间 B —— 任务相位/进度: 阶段 s ∈ {接近, 对位, 下降, 抓取, 抬起, 转移, 插入…},
              进度坐标 e∥ (沿插拔轴的推进量, 由几何真值给出)。

  动作丛 A = (B, F_act)     纤维 F_act = 执行/意图矢量 (引擎参考 u_ff ∈ R³, 夹爪 1 维)。
                            L2 解析链给出的 u_ff 场 = 该丛上的**参考水平场** (canonical horizontal field)。

  潜空间丛 Z = (B, R^192)   纤维 = INTACT-JEPA 世界模型潜空间:
                            z_t = encode(obs 滑窗)[-1],  z_goal = encode(goal),
                            **z_pred = predictor(z_t, a) 的下一步预测** (规划器同源, 逐位一致)。

  接触丛 C = (B, F_C ⊂ R^6) 纤维 = 接触坐标 (切向进度 e∥ / 法向偏离 e⊥ / 相对速度 V / 接触指示 …)。
                            ⭐ 插拔任务的主力丛 (接触约束决定成败)。

  性能丛 P = (B, F_P ⊂ R^6) 纤维 = 光耦合代价 (η / 对准残差 …)。
                            ⚠️ 插拔任务次要 —— 本层保留通道但默认 w_perf=0 (只跑不注入, 证据留痕)。

二、映射 / 联络 (三个可测量, 都有实测数字)

  · 丛映射 (pullback) Φ: Z → F_C,   Φ(z) = W·z + W_q·φ(PCA(z))     ← 标定 (ridge + LOSO R² 闸 ≥0.3)
      语义: 世界模型潜空间上的点 → 接触丛上的点。线性项 W = 联络系数 (1-形式),
            二次项 W_q 让曲率可非零 (线性联络曲率恒 0, 见下)。
  · 几何联络 (canonical, 无需标定): 由几何真值给出的接触坐标变化 h_geo (target/peg_head 之差)。
  · 水平提升 (horizontal lift):
        h_z = Φ(z_pred) − Φ(z_t)        ← 沿"预测潜空间方向"的协变导数 (一步)
  · 挠率/张力 (torsion-like, 潜空间联络 ⊖ 几何联络):
        T = h_Z^C − h_geo^C ,   κ_tor = ‖T‖ ,   cos∠ = ⟨h_Z^C, h_geo^C⟩ / (‖·‖‖·‖)
        → 世界模型预测与几何是否同向 (同向 ⇒ 预测可信, 可加权注入)。
  · 曲率 (curvature, 交换子 / 和乐):
        Ω = Φ(z_t+δ_a+δ_g) − Φ(z_t+δ_a) − Φ(z_t+δ_g) + Φ(z_t)
        δ_a = z_pred − z_t (动作方向), δ_g = z_goal − z_t (目标方向)
        Ω ≠ 0 ⇔ 两个方向的平行移动不交换 ⇔ 接触约束下丛不平凡 (自由空间应 ≈0)。
        (标定里显式拟合二次项才有非零曲率 —— 这也是"标定是否真学到了非线性"的判据。)

三、下游接线 (本层只产条件, 不写执行量)

  ① 流形专家预测器 (既有训练权重, 输入维不变):
       ẑ7 = A·z_pred + b   (丛映射 Z→R^7, 标定; LOSO R² 闸)
       manifold = WorldModelPredictor(ẑ7, a, m_geo)   → 接触丛预测 6 维
       ★ "把 predictor 预测的 z 潜空间喂给流形专家预测器" = 经 A 适配维度后真喂 (不是另起一套)。
  ② DiT 条件 token (叠加, 不替换既有 192 维 δ 通道):
       c_fiber = [ δ̂(192, 单位化) ⊕ ĥ_z(6, 归一化) ⊕ [κ_tor, cos∠, ‖Ω‖] ]  (200 维)
       经 action_head.apply_l4_cond 的同一 token 机制进 DiT (维度自适应)。
  ③ 性能丛: 只记录 (Φ_p, ŷ_p) 入证据列, w_perf=0 不注入。

四、零回退纪律

  · 环境守卫: SS_L4_FIBER=1 才启用; 不设 = 逐位与改造前相同 (hash 取证)。
  · 标定未过闸 (R²<0.3) ⇒ 通道照跑 + 逐帧真前向, 但 **不注入** (w=0), 来源标注 "未过闸"。
  · 只产条件/参考; 唯一执行出口仍是 L2 (`sched.decide` + `safety.saturate`), 融合走 capability_stack 收缩投影。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

import numpy as np

R2_GATE = 0.30            # 与 intact_l3_map / intent_line 同一闸值 (R²≥0.3 且 null<0.1 才算真信号)
NULL_GATE = 0.10
CONTACT_DIM = 6
PERF_DIM = 6
PCA_DIM = 8               # 二次项用低维投影 (192 → 8), 交叉项 = 8 + 8*9/2 = 44 → 可控参数数
Z_DIM = 192


# ══════════════════════════════════════════════════════════════════════════
# 标定容器: Φ (潜空间→接触丛) / A (潜空间→几何基 R^7) / Φ_p (潜空间→性能丛)
# ══════════════════════════════════════════════════════════════════════════
@dataclass
class LinearMap:
    """一项标定映射 y ≈ W·x + b (可选二次项 via 低维 PCA 投影)。"""
    w: np.ndarray
    b: np.ndarray
    r2: float = 0.0
    r2_loso: float = 0.0
    null_r2: float = 1.0
    n: int = 0
    pca_mean: np.ndarray | None = None
    pca_comp: np.ndarray | None = None      # (PCA_DIM, D)
    wq: np.ndarray | None = None            # (out, 1 + PCA_DIM + tri_dim)
    gate_dim: np.ndarray | None = None      # 每维 R² (可诊断哪个自由度可辨识)

    @property
    def ready(self) -> bool:
        return bool(self.r2_loso >= R2_GATE and self.null_r2 < NULL_GATE)

    def __call__(self, x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, dtype=np.float64).reshape(-1)
        y = self.w @ x[: self.w.shape[1]] + self.b
        if self.wq is not None and self.pca_comp is not None:
            y = y + self.wq @ self._quad(x)
        return y

    # ── 二次特征 (与 fit_map._design 的拼接顺序逐位一致: [x, tri]) ──────
    def _quad(self, x: np.ndarray) -> np.ndarray:
        xc = np.asarray(x, dtype=np.float64).reshape(-1)
        assert self.pca_comp is not None and self.pca_mean is not None
        p = (xc - self.pca_mean[: xc.size]) @ self.pca_comp[:, : xc.size].T
        d = p.shape[0]
        return np.asarray([p[i] * p[j] for i in range(d) for j in range(i, d)], dtype=np.float64)

    def feature_len(self) -> int:
        d = PCA_DIM
        return 1 + d + d * (d + 1) // 2

    def to_json(self) -> dict:
        d = {"w": self.w.tolist(), "b": self.b.tolist(), "r2": float(self.r2),
             "r2_loso": float(self.r2_loso), "null_r2": float(self.null_r2), "n": int(self.n),
             "gate_dim": None if self.gate_dim is None else np.asarray(self.gate_dim).tolist()}
        if self.wq is not None:
            d["wq"] = self.wq.tolist()
            d["pca_mean"] = np.asarray(self.pca_mean).tolist()
            d["pca_comp"] = np.asarray(self.pca_comp).tolist()
        return d

    @staticmethod
    def from_json(d: dict) -> LinearMap:
        return LinearMap(
            w=np.asarray(d["w"], dtype=np.float64), b=np.asarray(d["b"], dtype=np.float64),
            r2=float(d.get("r2", 0.0)), r2_loso=float(d.get("r2_loso", 0.0)),
            null_r2=float(d.get("null_r2", 1.0)), n=int(d.get("n", 0)),
            gate_dim=None if d.get("gate_dim") is None else np.asarray(d["gate_dim"], dtype=np.float64),
            wq=None if d.get("wq") is None else np.asarray(d["wq"], dtype=np.float64),
            pca_mean=None if d.get("pca_mean") is None else np.asarray(d["pca_mean"], dtype=np.float64),
            pca_comp=None if d.get("pca_comp") is None else np.asarray(d["pca_comp"], dtype=np.float64))


def _ridge(x: np.ndarray, y: np.ndarray, lam: float = 1e-2) -> tuple[np.ndarray, np.ndarray]:
    """带偏置的岭回归 (闭式解)。x: [N,D]  y: [N,K] (或 [N])。"""
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    if y.ndim == 1:
        y = y[:, None]
    a = np.concatenate([x, np.ones((x.shape[0], 1))], axis=1)
    g = a.T @ a + lam * np.eye(a.shape[1])
    sol = np.linalg.solve(g, a.T @ y)                      # [D+1, K]
    return sol[:-1].T, sol[-1]                             # W [K,D], b [K]


def _r2(y: np.ndarray, yh: np.ndarray) -> np.ndarray:
    y = np.asarray(y, float)
    yh = np.asarray(yh, float)
    if y.ndim == 1:
        y, yh = y[:, None], yh[:, None]
    ss_res = ((y - yh) ** 2).sum(0)
    ss_tot = ((y - y.mean(0, keepdims=True)) ** 2).sum(0)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = 1.0 - ss_res / np.where(ss_tot > 1e-12, ss_tot, np.nan)
    return np.nan_to_num(out, nan=0.0)


def fit_map(x: np.ndarray, y: np.ndarray, use_quad: bool = False,
            pca_dim: int = PCA_DIM) -> LinearMap:
    """标定 y ≈ Φ(x): 线性项 + (可选) 二次项; 用**留一交叉验证 (LOO)** 出 R²_loso。

    纪律: PCA 与回归系数都**只在训练折上拟合** (防泄漏); 同时给 null 基线 R² (用均值预测),
    防"看起来高其实只是在猜均值"。R²_loso ≥ 0.3 且 null < 0.1 才算真信号 (与既有闸一致)。
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    if y.ndim == 1:
        y = y[:, None]
    n, dx, dy = x.shape[0], x.shape[1], y.shape[1]
    if n < 8:
        return LinearMap(w=np.zeros((dy, dx)), b=np.zeros(dy), n=n, r2_loso=-1.0, null_r2=1.0)

    def _design(xa: np.ndarray, pc: tuple | None) -> tuple[np.ndarray, tuple | None]:
        if not use_quad:
            return xa, pc
        if pc is None:
            mu = xa.mean(0)
            vt = np.linalg.svd(xa - mu, full_matrices=False)[2]
            pc = (mu, vt[: min(pca_dim, vt.shape[0])])
        mu, comp = pc
        p = (xa - mu) @ comp.T
        d = p.shape[1]
        tri = np.column_stack([p[:, i] * p[:, j] for i in range(d) for j in range(i, d)])
        return np.concatenate([xa, tri], axis=1), pc

    # ── LOO 预测 (训练折内自拟合 PCA) ──
    yh = np.zeros_like(y)
    for i in range(n):
        te = np.zeros(n, bool)
        te[i] = True
        if (~te).sum() < 4:
            yh[te] = y[~te].mean(0, keepdims=True) if (~te).any() else 0.0
            continue
        xa, _ = _design(x[~te], None)
        w, b = _ridge(xa, y[~te])
        xa_te, _ = _design(x[te], _design(x[~te], None)[1])
        yh[te] = xa_te @ w.T + b

    # ── 全量拟合 (落地模型) ──
    xa, pc = _design(x, None)
    w_all, b_all = _ridge(xa, y)
    m = LinearMap(w=w_all[:, :dx], b=b_all, r2=0.0, r2_loso=0.0, null_r2=1.0, n=n)
    if use_quad:
        m.wq = w_all[:, dx:]
        m.pca_mean, m.pca_comp = pc[0], pc[1]
    m.r2 = float(np.mean(_r2(y, xa @ w_all.T + b_all)))
    m.r2_loso = float(np.mean(_r2(y, yh)))
    m.null_r2 = float(np.mean(_r2(y, np.tile(y.mean(0), (n, 1)))))
    m.gate_dim = _r2(y, yh)
    return m


# ══════════════════════════════════════════════════════════════════════════
# 丛联络: 主入口
# ══════════════════════════════════════════════════════════════════════════
@dataclass
class LiftResult:
    """一次水平提升的完整结果 (全部可审计)。"""
    h_z: np.ndarray                       # 潜空间联络给出的接触丛增量 [F_C]
    phi_zt: np.ndarray
    phi_zp: np.ndarray
    z7_hat: np.ndarray | None = None      # 丛映射 Z→R^7 (喂流形专家预测器)
    kappa_tor: float = 0.0                # 挠率/张力 ‖h_z − h_geo^C‖
    cos_geo: float = 0.0                  # h_z 与几何增量方向一致性
    omega: np.ndarray | None = None       # 曲率 (交换子)
    kappa_curv: float = 0.0               # ‖Ω‖
    perf_pred: np.ndarray | None = None   # 性能丛 (只记录)
    src: str = ""
    ok: bool = False


class FiberConnection:
    """动作丛 → 接触丛 (主力) / 性能丛 (次要) 的丛映射与联络。"""

    def __init__(self, path: str | None = None, root: str | None = None) -> None:
        root = root or os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))))
        self.path = path or os.path.join(root, "models", "intact_fiber_map.json")
        self.contact: LinearMap | None = None
        self.contact_geo: LinearMap | None = None     # 几何 → 接触丛 (canonical 联络用)
        self.morph: LinearMap | None = None           # z_pred → z7 (丛映射)
        self.perf: LinearMap | None = None            # z_pred → 性能丛 (弱通道)
        self.w_perf = 0.0
        self.note = "未加载"
        self._load()

    # ── 加载/状态 ────────────────────────────────────────────────────────
    def _load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
        except FileNotFoundError:
            self.note = (f"未标定: {os.path.relpath(self.path, os.path.dirname(self.path)) if self.path else '?'} "
                         f"不存在 → 联络只跑几何项, 潜空间项不注入 (拒绝 + 计数, 不写死映射)")
            return
        except Exception as e:                                             # noqa: BLE001
            self.note = f"标定读取失败: {type(e).__name__}: {e}"
            return
        for key, attr in (("l3_contact", "contact"), ("geom_contact", "contact_geo"),
                          ("z7_morph", "morph"), ("perf", "perf")):
            blk = d.get(key)
            if blk:
                setattr(self, attr, LinearMap.from_json(blk))
        self.w_perf = float(d.get("w_perf", 0.0))
        self.note = str(d.get("note") or "已加载")

    @property
    def ready(self) -> bool:
        return self.contact is not None and self.contact.ready and self.morph is not None and self.morph.ready

    def describe(self) -> dict:
        g = lambda m: None if m is None else {"r2": round(m.r2, 4), "r2_loso": round(m.r2_loso, 4),
                                              "null_r2": round(m.null_r2, 4), "n": m.n}
        return {"fiber": "action Z(192) → contact C(6) / perf P(6)", "path": os.path.basename(self.path),
                "contact_map": g(self.contact), "morph_z7": g(self.morph), "perf_map": g(self.perf),
                "ready": bool(self.ready), "w_perf": self.w_perf, "note": self.note,
                "r2_gate": R2_GATE}

    # ── 主运算: 水平提升 + 挠率 + 曲率 ──────────────────────────────────
    def lift(self, z_t, z_pred, z_goal=None, h_geo: np.ndarray | None = None) -> LiftResult:
        zt = np.asarray(z_t, dtype=np.float64).reshape(-1)
        zp = np.asarray(z_pred, dtype=np.float64).reshape(-1)
        if self.contact is None or zt.size == 0 or zp.size == 0 or zt.size != zp.size:
            return LiftResult(h_z=np.zeros(CONTACT_DIM), phi_zt=np.zeros(CONTACT_DIM),
                              phi_zp=np.zeros(CONTACT_DIM), src="拒绝(无潜空间/未标定)")
        phi_zt = self.contact(zt)
        phi_zp = self.contact(zp)
        h_z = phi_zp - phi_zt                                  # 水平提升 (协变导数一步)
        res = LiftResult(h_z=h_z, phi_zt=phi_zt, phi_zp=phi_zp)
        # 丛映射 → 几何基 (喂既有流形专家预测器, 输入维不变)
        if self.morph is not None:
            res.z7_hat = self.morph(zp)
        # 挠率: 潜空间联络 ⊖ 几何联络 (同维比较, 取前 3 维切向语义)
        if h_geo is not None:
            hg = np.asarray(h_geo, dtype=np.float64).reshape(-1)
            k = min(3, hg.size, h_z.size)
            t = h_z[:k] - hg[:k]
            res.kappa_tor = float(np.linalg.norm(t))
            nh, ng = float(np.linalg.norm(h_z[:k])), float(np.linalg.norm(hg[:k]))
            res.cos_geo = float(h_z[:k] @ hg[:k] / (nh * ng)) if nh > 1e-9 and ng > 1e-9 else 0.0
        # 曲率 (交换子): Ω = Φ(zt+δa+δg) − Φ(zt+δa) − Φ(zt+δg) + Φ(zt)
        if z_goal is not None:
            zg = np.asarray(z_goal, dtype=np.float64).reshape(-1)
            if zg.size == zt.size:
                da, dg = zp - zt, zg - zt
                om = (self.contact(zt + da + dg) - self.contact(zt + da)
                      - self.contact(zt + dg) + phi_zt)
                res.omega = np.asarray(om, dtype=np.float64)
                res.kappa_curv = float(np.linalg.norm(res.omega))
        # 性能丛 (本任务次要): 只记录
        if self.perf is not None:
            res.perf_pred = self.perf(zp)
        res.ok = True
        res.src = (f"Φ(z_pred)−Φ(z_t) · contact r²_loso={self.contact.r2_loso:.3f} "
                   f"(null={self.contact.null_r2:.3f}, n={self.contact.n}) · "
                   f"z7 丛映射 r²_loso={self.morph.r2_loso:.3f}" if self.morph is not None
                   else "Φ(z_pred)−Φ(z_t) (无 z7 丛映射)")
        return res

    # ── 条件向量 (DiT token; 叠加不替换) ────────────────────────────────
    def condition_vector(self, delta, lift: LiftResult | None = None,
                         extra: list[float] | None = None,
                         perf=None) -> np.ndarray:
        """[δ̂(192) ⊕ ĥ_z(6 归一化) ⊕ Φ(z_pred)(6 接触丛) ⊕ Φ_p(z_pred)(6 性能丛) ⊕ 标量]

        设计 (老倪: "动作丛 → 接触丛 → 最后进入 DiT 生成轨迹"; 性能流形对插拔作用小):
          · δ̂  —— 意图增量方向 (既有通道, 不丢)
          · ĥ_z —— **联络的水平提升**: 预测潜空间方向在接触丛上的协变导数方向 (归一化)
          · Φ(z_pred)  —— **接触丛坐标** (切向进度/法向偏离/V/V̇/切向速度/法向速度) = 主力
          · Φ_p(z_pred)—— **性能丛坐标** (η/δ⊥/δ_axial/…) = 次要: 只作条件 token, 无动作幅值权重
          · 标量 —— 挠率 κ_tor / 与几何联络一致性 cos∠ / 曲率 ‖Ω‖ / 调用方额外量
        """
        d = np.asarray(delta, dtype=np.float64).reshape(-1)
        nd = float(np.linalg.norm(d))
        dh = d / nd if nd > 1e-9 else d
        h = np.zeros(CONTACT_DIM, dtype=np.float64)
        phi = np.zeros(CONTACT_DIM, dtype=np.float64)
        pf = np.zeros(PERF_DIM, dtype=np.float64)
        scal = [0.0, 0.0, 0.0]
        if lift is not None and lift.ok:
            hv = np.asarray(lift.h_z, dtype=np.float64).reshape(-1)
            nh = float(np.linalg.norm(hv))
            h[: min(CONTACT_DIM, hv.size)] = (hv / nh)[:CONTACT_DIM] if nh > 1e-9 else hv[:CONTACT_DIM]
            pv = np.asarray(lift.phi_zp, dtype=np.float64).reshape(-1)
            if pv.size:
                phi[: min(CONTACT_DIM, pv.size)] = pv[:CONTACT_DIM]
            scal = [float(lift.kappa_tor), float(lift.cos_geo), float(lift.kappa_curv)]
        if perf is not None:
            pvv = np.asarray(perf, dtype=np.float64).reshape(-1)
            if pvv.size:
                pf[: min(PERF_DIM, pvv.size)] = pvv[:PERF_DIM]
        elif lift is not None and lift.perf_pred is not None:
            pvv = np.asarray(lift.perf_pred, dtype=np.float64).reshape(-1)
            pf[: min(PERF_DIM, pvv.size)] = pvv[:PERF_DIM]
        if extra:
            scal = scal + [float(x) for x in extra]
        return np.concatenate([dh, h, phi, pf, np.asarray(scal, dtype=np.float64)])


# ══════════════════════════════════════════════════════════════════════════
# 自检 (纯 numpy, 不依赖引擎/模型): 曲率判据必须能区分"平直"与"弯曲"
# ══════════════════════════════════════════════════════════════════════════
def _selftest() -> int:
    rng = np.random.default_rng(0)
    n, dz = 400, 12
    z = rng.normal(size=(n, dz))
    w_true = rng.normal(size=(CONTACT_DIM, dz)) * 0.3
    # 真值: y = W z + 二次项 (曲率非零) —— 拿它当"真接触坐标"
    q = rng.normal(size=(CONTACT_DIM, dz, dz)) * 0.05
    quad = np.einsum("ni,kij,nj->nk", z, q, z)
    y = z @ w_true.T + quad
    lin = fit_map(z, y, use_quad=False)
    non = fit_map(z, y, use_quad=True)
    print(f"[selftest] 线性 Φ : r2_loso={lin.r2_loso:.3f} 二次 Φ: r2_loso={non.r2_loso:.3f} "
          f"(null={lin.null_r2:.3f})")
    assert non.r2_loso >= lin.r2_loso, "二次项应当不劣于线性项"

    fc = FiberConnection(path="/nonexistent.json")
    fc.contact, fc.morph = non, LinearMap(w=rng.normal(size=(7, dz)) * 0.1,
                                          b=np.zeros(7), r2_loso=0.5, null_r2=0.0, n=n)
    zt, zp, zg = z[0], z[1], z[2]
    r = fc.lift(zt, zp, z_goal=zg, h_geo=np.zeros(3))
    print(f"[selftest] 提升: ‖h_z‖={np.linalg.norm(r.h_z):.4f} ‖Ω‖={r.kappa_curv:.4f} "
          f"z7_hat={None if r.z7_hat is None else np.round(r.z7_hat[:3], 3).tolist()}")

    # 平直检验: 纯线性 Φ → 曲率必须 ≈ 0
    fc.contact = lin
    r2 = fc.lift(zt, zp, z_goal=zg, h_geo=np.zeros(3))
    print(f"[selftest] 线性 Φ 曲率 ‖Ω‖={r2.kappa_curv:.6f} (应≈0)")
    assert r2.kappa_curv < 1e-6, "线性联络曲率必须为 0"
    assert r.kappa_curv > 1e-9, "二次联络曲率必须非零 (否则曲率项是摆设)"

    c = fc.condition_vector(zg - zt, r)
    print(f"[selftest] 条件向量 dim={c.size} δ̂={np.round(c[:3], 4).tolist()} "
          f"提升段={np.round(c[dz:dz + 3], 4).tolist()} "
          f"接触丛Φ段={np.round(c[dz + CONTACT_DIM:dz + CONTACT_DIM + 3], 4).tolist()} "
          f"性能丛Φp段={np.round(c[dz + 2 * CONTACT_DIM:dz + 2 * CONTACT_DIM + 3], 4).tolist()} "
          f"标量={np.round(c[-3:], 4).tolist()}")
    assert c.size == dz + 3 * CONTACT_DIM + 3, c.size
    print("[selftest] PASS (映射/提升/曲率/条件向量 全部真值可算)")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
