# -*- coding: utf-8 -*-
"""🧬 capability_stack.py — L2/L3/L4 能力栈仲裁 (老倪原则 2026-09-14)

原则: **上层只提供意图/条件, 执行永远由 L2 解析链收口; 每层只能收窄可行域、不能扩大
(U_L2 ⊇ U_L3 ⊇ U_L4); 稳定性由 L2 的李雅普诺夫势兜底 (V = 到孔口距离² + 姿态偏差²)。**

本模块是**纯 numpy 仲裁层** (不依赖 torch/引擎), 三件事:
  1. 层输出登记 (`LayerOut`): 每路都带 来源/权重/是否被采纳 —— 缺条件时**如实拒绝并标注**,
     不静默降级 (沿用 decoder/GUI 的既有纪律)。
  2. 收口融合 (`commit`): `u = proj_{U_L2}((1−w)·u_L2 + w·u_up)`, 越界必夹紧并记账 (I2)。
  3. 稳定性 (`lyapunov` / `lyapunov_ok`): 势函数与逐阶段单调检查 (I5)。

无状态全局变量; 计数与证据都在实例里, 供面板/报告逐帧取用。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import numpy as np

# 层名与允许的输出语义 (写死在这里, 防止"上层直接吐动作"重演)
LAYER_SEMANTICS = {
    "L4": "intent",       # 意图: 目标位移/姿态/交权
    "L3": "condition",    # 条件: 相位/子目标/流程条件
    "L2": "action",       # 动作: **唯一执行出口**
}


@dataclass
class LayerOut:
    """一路层输出 (每一路都必须能回答: 谁给的 / 多信 / 采不采纳 / 为什么)。"""
    layer: str
    kind: str                     # intent / condition / action
    vec: np.ndarray | None
    src: str = ""
    weight: float = 0.0
    accepted: bool = False
    reason: str = ""
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        want = LAYER_SEMANTICS.get(self.layer)
        if want is not None and self.kind != want:
            raise ValueError(f"{self.layer} 层语义必须是 {want!r}, 收到 {self.kind!r} "
                             f"(上层不许直接产动作 —— 老倪原则)")


def vec_hash(v) -> str:
    """逐位取证用的哈希 (零回退判定: 开关前后必须完全相同)。"""
    if v is None:
        return "none"
    a = np.asarray(v, dtype=np.float64)
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()[:16]


class CapabilityStack:
    """能力栈仲裁: 登记 → 融合 → 收口 → 记账。

    用法 (引擎里逐帧):
        st = CapabilityStack(bounds=(-1.0, 1.0))
        st.note_l4(m_int, src="decoder(δ)", weight=w_dec, ready=pred_ready)
        merged, info = st.commit(u_l2=u_analytic, u_up=u_intent)   # 已夹紧进 U_L2
        ok, num = st.lyapunov_ok(trace)
    """

    def __init__(self, bounds: tuple[float, float] = (-1.0, 1.0), dim: int = 4) -> None:
        self.lo, self.hi = float(bounds[0]), float(bounds[1])
        self.dim = int(dim)
        self.layers: dict[str, LayerOut] = {}
        self.stats: dict[str, object] = {
            "commit": 0, "vetoed": 0, "clipped": 0, "clip_max": 0.0, "clip_sum": 0.0,
            "w_sum": 0.0, "w_last": 0.0, "u_up_norm_sum": 0.0, "u_l2_norm_sum": 0.0,
            "zero_regression_hashes": [],
        }

    # ── 1) 登记层输出 ──────────────────────────────────────────────
    def register(self, layer: str, kind: str, vec, src: str = "",
                 weight: float = 0.0) -> LayerOut:
        out = LayerOut(layer=layer, kind=kind, vec=None if vec is None else np.asarray(vec, float),
                       src=src, weight=float(weight))
        self.layers[layer] = out
        return out

    def note_l4(self, m_int, src: str, weight: float, ready: bool) -> LayerOut:
        """L4 意图路: 未就绪 (预测器没训练) → 如实标注 weight=0, 但不隐藏线路在跑。"""
        out = self.register("L4", "intent", m_int, src=src, weight=weight)
        out.extra["ready"] = bool(ready)
        if m_int is None:
            out.reason = "无意图 (δ 缺失) → 不注入"
        elif not ready:
            out.reason = "预测器未训练 → 线路在跑但不注入 (w=0, 噪声不进执行口)"
        elif float(weight) <= 0.0:
            out.reason = "门控 w=0 (意图退化/置信度 0) → 不注入"
        else:
            out.accepted = True
            out.reason = f"采纳: w={float(weight):.3f}"
        return out

    def note_l3(self, c_t, src: str, weight: float = 0.0) -> LayerOut:
        """L3 条件路: 只产条件, 不产动作 (未标定/缺失时如实拒绝)。"""
        out = self.register("L3", "condition", c_t, src=src, weight=weight)
        out.reason = ("条件就绪" if c_t is not None else "无标定条件 → 拒绝 (不写死映射)")
        out.accepted = c_t is not None
        return out

    def note_l2(self, u_l2, src: str = "analytic") -> LayerOut:
        out = self.register("L2", "action", u_l2, src=src, weight=1.0)
        out.accepted = True
        out.reason = "执行层 (唯一出口)"
        return out

    # ── 2) 收口融合 (收缩投影) ────────────────────────────────────
    def project(self, u) -> tuple[np.ndarray, float]:
        """投影进 U_L2 = [lo, hi]; 返回 (投影后, 夹紧量 L∞)。"""
        a = np.asarray(u, dtype=float).reshape(-1)[: self.dim]
        p = np.clip(a, self.lo, self.hi)
        return p, float(np.max(np.abs(p - a))) if a.size else 0.0

    def commit(self, u_l2, u_up=None, w_up: float | None = None) -> tuple[np.ndarray, dict]:
        """u = proj_{U_L2}((1−w)·u_L2 + w·u_up)。u_up=None 或 w=0 → 逐位等于 u_L2。"""
        base = np.asarray(u_l2, dtype=float).reshape(-1)[: self.dim].copy()
        if u_up is None:
            self.stats["vetoed"] = int(self.stats["vetoed"]) + 1
            return base, {"applied": False, "reason": "无上层参考 → L2 原值", "clip": 0.0}
        w = float(self.layers["L4"].weight if w_up is None else w_up)
        if not np.isfinite(w) or w <= 0.0:
            self.stats["vetoed"] = int(self.stats["vetoed"]) + 1
            return base, {"applied": False, "reason": "w=0 → L2 原值 (零回退)", "clip": 0.0}
        up = np.asarray(u_up, dtype=float).reshape(-1)[: self.dim]
        merged, clip = self.project((1.0 - w) * base + w * up)
        self.stats["commit"] = int(self.stats["commit"]) + 1
        if clip > 0.0:
            self.stats["clipped"] = int(self.stats["clipped"]) + 1
            self.stats["clip_max"] = max(float(self.stats["clip_max"]), clip)
            self.stats["clip_sum"] = float(self.stats["clip_sum"]) + clip
        self.stats["w_sum"] = float(self.stats["w_sum"]) + w
        self.stats["w_last"] = w
        self.stats["u_up_norm_sum"] = float(self.stats["u_up_norm_sum"]) + float(np.linalg.norm(up[:3]))
        self.stats["u_l2_norm_sum"] = float(self.stats["u_l2_norm_sum"]) + float(np.linalg.norm(base[:3]))
        return merged, {"applied": True, "w": w, "clip": clip,
                        "reason": "融合并夹紧进 U_L2" if clip > 0 else "融合 (未越界)"}

    # ── 3) 稳定性: 李雅普诺夫势 + 单调检查 ─────────────────────────
    @staticmethod
    def lyapunov(hand, hole, yaw_err: float = 0.0, w_yaw: float = 1.0,
                 peg_head=None) -> float:
        """V = ‖hand−hole‖² + w·θ_err²  (老倪定义; peg_head 给了就用 peg 头, 否则用手)。"""
        p = np.asarray(peg_head if peg_head is not None else hand, dtype=float).reshape(-1)[:3]
        h = np.asarray(hole, dtype=float).reshape(-1)[:3]
        d2 = float(np.sum((p - h) ** 2))
        return d2 + float(w_yaw) * float(yaw_err) ** 2

    @staticmethod
    def lyapunov_ok(trace, tol: float = 0.0) -> tuple[bool, dict]:
        """逐帧单调不增检查 (tol>0 允许小幅噪声回升, 默认严格)。"""
        v = [float(x) for x in trace if x is not None and np.isfinite(x)]
        if len(v) < 2:
            return True, {"n": len(v), "rise_max": 0.0, "rise_cnt": 0, "note": "样本不足"}
        d = np.diff(np.asarray(v))
        rises = d[d > tol]
        return bool(rises.size == 0), {"n": len(v), "v0": round(v[0], 6), "v_last": round(v[-1], 6),
                                       "rise_max": float(rises.max()) if rises.size else 0.0,
                                       "rise_cnt": int(rises.size)}

    # ── 4) 证据快照 (面板/报告用) ─────────────────────────────────
    def summary(self) -> dict:
        s = dict(self.stats)
        n = int(s.get("commit") or 0)
        for k in ("clip_sum", "w_sum", "u_up_norm_sum", "u_l2_norm_sum"):
            s[k + "_mean"] = round(float(s[k]) / n, 5) if n else 0.0
        s["layers"] = {k: {"kind": v.kind, "src": v.src, "weight": round(v.weight, 4),
                           "accepted": v.accepted, "reason": v.reason, "hash": vec_hash(v.vec),
                           **({k2: v2 for k2, v2 in v.extra.items()})}
                       for k, v in self.layers.items()}
        return s


if __name__ == "__main__":
    import json
    st = CapabilityStack(bounds=(-1.0, 1.0))
    rng = np.random.default_rng(0)
    u_l2 = np.array([0.2, -0.1, 0.05, 1.0])
    u_up = np.array([0.9, -0.9, 0.8, 1.0])           # 越界参考 (L∞ = 0.9, 必夹紧)
    st.note_l2(u_l2)
    st.note_l4(rng.normal(size=192), "decoder(δ)", 0.3, ready=True)
    merged, info = st.commit(u_l2, u_up, w_up=0.5)
    print("融合:", np.round(merged, 4).tolist(), "|", info)
    print("L2 原值:", u_l2.tolist(), "→ 越界参考被夹紧 (I2) ✓" if info["clip"] > 0 else "未夹紧 ?")
    v = [1.0, 0.64, 0.36, 0.2, 0.1]
    print("V 单调:", CapabilityStack.lyapunov_ok(v))
    print(json.dumps(st.summary(), ensure_ascii=False)[:320])
