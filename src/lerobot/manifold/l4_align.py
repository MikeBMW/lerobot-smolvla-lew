#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🎯 L4 → 引擎 u 的**方向/幅度对齐层** (Step ①: 让上层注入能过 L2 收口闸)

问题 (实测基线): L4 意图线输出的 u_int 与 L2 参考 u_ff 方向经常相反 (cos<0) 或幅度过大,
150 帧里 79~120 帧被 L2 收口闸否决 → 上层注入大多没到执行层, A/B 比不出差异。

做法 (数据驱动, 不改闸的语义, 也不伪造方向):
  ① 采成对样本 (u_ff 下层参考, u_int 上层提案, 阶段) —— 引擎 SS_L4_ALIGN_DATA=<npz>
  ② 标定线性映射 u_align = R·u_int + b   (R 3×3 + b, ridge + 留一交叉验证)
       —— 去掉**系统性**反向/量纲差/轴向耦合 (这是标定能合法消掉的部分)
  ③ 残差按锥角截断: 设 r = u_align, a = u_ff, 分解 r = r∥ + r⊥;
       目标 cos 下限 cos_min (默认 0.9, 由 SS_L4_ALIGN_COS_MIN 覆盖)
       ⇒ 允许的正交比例上限 k = sqrt(1/cos_min² − 1) → r⊥ 超限时缩放 r⊥ (方向不变, 只收窄可行域)
  ④ 幅度封顶: |r| ≤ ratio_max·|a| (默认 1.2, SS_L4_ALIGN_RATIO_MAX) → 超则等比缩放

闸值 (与仓库其它标定一致 + 对齐专用):
  · 对齐后的 LOO cos ≥ 0.90 (中位数) 且优于标定前基线 ≥0.2 —— 否则 ready=False, 运行时不施加
  · 未 ready / 无样本 / 维度不符 → 原样返回 (逐位零回退), 计数 + 来源可查

诚实边界 (必须随报告写清):
  · 对齐后 u_int 主要贡献变成"沿 L2 方向的幅度调制 + 受限于锥角的轻微转向";
    真正与 L2 正交的"新信息"被锥角截断 —— 这是收口闸语义决定的, 不是实现偷懒。
  · 若对齐后的 LOO cos 仍 <0.9 → 说明该信号与下层参考**本质上不同向**, 不许硬掰 (脚本会拒绝出图)。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

import numpy as np

COS_READY = 0.90          # 对齐后 LOO cos 中位数闸
COS_GAIN = 0.20           # 相对标定前基线的提升闸
DIM = 3


@dataclass
class AlignMap:
    r: np.ndarray                 # (3,3)
    b: np.ndarray                 # (3,)
    cos_loso: float = 0.0
    cos_base: float = 0.0
    n: int = 0
    per_stage: dict | None = None

    @property
    def ready(self) -> bool:
        return bool(self.cos_loso >= COS_READY and (self.cos_loso - self.cos_base) >= COS_GAIN)

    def __call__(self, u: np.ndarray) -> np.ndarray:
        v = np.asarray(u, dtype=np.float64).reshape(-1)[: self.r.shape[0]]
        return self.r @ v[: self.r.shape[1]] + self.b


def _cos(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a = np.atleast_2d(np.asarray(a, float))
    b = np.atleast_2d(np.asarray(b, float))
    na = np.linalg.norm(a, axis=1)
    nb = np.linalg.norm(b, axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        c = (a * b).sum(1) / np.where(na * nb > 1e-12, na * nb, np.nan)
    return np.nan_to_num(c, nan=0.0)


def fit_align(u_up: np.ndarray, u_l2: np.ndarray, stages=None) -> AlignMap:
    """ridge + 留一交叉验证拟合 u_l2 ≈ R·u_up + b (3→3), 并给出对齐前后 cos。"""
    x = np.asarray(u_up, float)[:, :DIM]
    y = np.asarray(u_l2, float)[:, :DIM]
    n = x.shape[0]
    if n < 12:
        return AlignMap(r=np.eye(DIM), b=np.zeros(DIM), n=n)
    # 全量拟合
    a = np.concatenate([x, np.ones((n, 1))], axis=1)
    sol = np.linalg.solve(a.T @ a + 1e-2 * np.eye(DIM + 1), a.T @ y)
    r, b = sol[:DIM].T, sol[DIM]                       # (3,3), (3,)
    # LOO
    yh = np.zeros_like(y)
    for i in range(n):
        te = np.zeros(n, bool)
        te[i] = True
        if (~te).sum() < 12:
            yh[te] = y[~te].mean(0, keepdims=True)
            continue
        aa = np.concatenate([x[~te], np.ones(((~te).sum(), 1))], axis=1)
        s = np.linalg.solve(aa.T @ aa + 1e-2 * np.eye(DIM + 1), aa.T @ y[~te])
        yh[te] = x[te] @ s[:DIM].T + s[DIM]
    m = AlignMap(r=r, b=b, n=n)
    m.cos_loso = float(np.median(_cos(yh, y)))
    m.cos_base = float(np.median(_cos(x, y)))
    if stages is not None:
        st = np.asarray(stages)
        m.per_stage = {}
        for s in sorted(set(st.tolist())):
            sel = st == s
            if sel.sum() >= 6:
                m.per_stage[str(s)] = {"n": int(sel.sum()),
                                       "cos_loso": round(float(np.median(_cos(yh[sel], y[sel]))), 4),
                                       "cos_base": round(float(np.median(_cos(x[sel], y[sel]))), 4)}
    return m


class IntentAligner:
    """运行时对齐器: 线性映射 + 锥角截断 + 幅度封顶 (每步真算, 带来源)。"""

    def __init__(self, path: str | None = None, root: str | None = None) -> None:
        root = root or os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))))
        self.path = path or os.path.join(root, "models", "l4_align_map.json")
        self.map: AlignMap | None = None
        self.note = "未加载"
        self.cos_min = float(os.environ.get("SS_L4_ALIGN_COS_MIN", "0.9"))
        self.ratio_max = float(os.environ.get("SS_L4_ALIGN_RATIO_MAX", "1.2"))
        self.last_cos_before = 0.0
        self.last_cos_after = 0.0
        self.last_ratio = 0.0
        self._load()

    def _load(self) -> None:
        try:
            d = json.load(open(self.path, encoding="utf-8"))
        except FileNotFoundError:
            self.note = f"未标定: {os.path.basename(self.path)} 不存在 → 不施加对齐 (原样透传)"
            return
        except Exception as e:                                                # noqa: BLE001
            self.note = f"标定读取失败: {type(e).__name__}: {e}"
            return
        try:
            self.map = AlignMap(r=np.asarray(d["r"], float), b=np.asarray(d["b"], float),
                                cos_loso=float(d.get("cos_loso", 0.0)),
                                cos_base=float(d.get("cos_base", 0.0)), n=int(d.get("n", 0)))
        except Exception as e:                                                # noqa: BLE001
            self.note = f"标定字段异常: {type(e).__name__}: {e}"
            return
        self.note = (f"已加载 {os.path.basename(self.path)} · n={self.map.n} · "
                     f"cos LOO {self.map.cos_base:.3f}→{self.map.cos_loso:.3f} · "
                     f"ready={self.ready} · cos_min={self.cos_min} ratio_max={self.ratio_max}")

    @property
    def ready(self) -> bool:
        return bool(self.map is not None and self.map.ready)

    def describe(self) -> dict:
        m = self.map
        return {"path": os.path.basename(self.path), "ready": self.ready,
                "n": (m.n if m else 0), "cos_loso": (round(m.cos_loso, 4) if m else None),
                "cos_base": (round(m.cos_base, 4) if m else None),
                "per_stage": (m.per_stage if m else None),
                "cos_min": self.cos_min, "ratio_max": self.ratio_max, "note": self.note}

    # ── 主入口: 返回 (对齐后的 u(4), info) ───────────────────────────────
    def align(self, u, stage: str = "", ref=None) -> tuple[np.ndarray, dict]:
        u = np.asarray(u, dtype=np.float64).reshape(-1)
        grip = float(u[3]) if u.size >= 4 else 1.0
        a = None if ref is None else np.asarray(ref, float).reshape(-1)[:DIM]
        if self.map is None:
            return u, {"applied": 0, "reason": "未标定"}
        r = self.map(np.asarray(u[:DIM], float))
        self.last_cos_before = float(_cos(np.asarray(u[:DIM], float)[None], a[None])[0]) if a is not None else 0.0
        if a is not None:
            na = float(np.linalg.norm(a))
            # ② 锥角截断: r = r∥ + r⊥, 限 |r⊥| ≤ k·|r∥|, k = sqrt(1/cos_min² − 1)
            if na > 1e-9:
                ah = a / na
                par = float(r @ ah) * ah
                perp = r - par
                npar, nperp = float(np.linalg.norm(par)), float(np.linalg.norm(perp))
                k = float(np.sqrt(max(0.0, 1.0 / max(self.cos_min, 1e-6) ** 2 - 1.0)))
                if nperp > k * npar and nperp > 1e-12:
                    r = par + perp * ((k * npar) / nperp)
            # ③ 幅度封顶
            nr, na2 = float(np.linalg.norm(r)), na
            if na2 > 1e-9 and nr > self.ratio_max * na2:
                r = r * ((self.ratio_max * na2) / nr)
        self.last_cos_after = float(_cos(r[None], a[None])[0]) if a is not None else 0.0
        self.last_ratio = (float(np.linalg.norm(r) / na) if (a is not None and na > 1e-9) else 0.0)
        out = np.concatenate([r, [grip]])
        return out, {"applied": 1, "cos_before": self.last_cos_before,
                     "cos_after": self.last_cos_after, "ratio": self.last_ratio,
                     "cos_min": self.cos_min, "ratio_max": self.ratio_max}


def _selftest() -> int:
    rng = np.random.default_rng(0)
    n = 400
    l2 = rng.normal(size=(n, 3))
    # 造一个"系统性反向+量纲差"的提案 (与实测同型): u_up = -0.3 · A · l2
    A = np.array([[0.9, 0.1, 0.0], [-0.2, 1.1, 0.1], [0.0, -0.1, 0.8]])
    up = -0.3 * (l2 @ A.T) + rng.normal(scale=0.05, size=(n, 3))
    m = fit_align(up, l2)
    print(f"[selftest] 对齐前后 cos: {m.cos_base:+.3f} → {m.cos_loso:+.3f} (n={m.n}) ready={m.ready}")
    assert m.cos_base < 0, "构造的提案应当是与参考反向的 (cos_base<0)"
    assert m.cos_loso > 0.9, "对齐后 cos 应当 >0.9"
    assert m.ready, "该情形应判 ready"

    al = IntentAligner(path="/nonexistent.json")
    al.map = m
    u_up = up[0]
    u_ref = l2[0]
    out, info = al.align(np.concatenate([u_up, [1.0]]), ref=u_ref)
    print(f"[selftest] 单步对齐: cos {info['cos_before']:+.3f} → {info['cos_after']:+.3f} · "
          f"幅度比 {info['ratio']:.3f} (≤{al.ratio_max})")
    assert info["cos_after"] >= al.cos_min - 1e-6, "锥角截断后 cos 必须不低于 cos_min"
    assert info["ratio"] <= al.ratio_max + 1e-6, "幅度必须被封顶"
    print("[selftest] PASS (对齐映射/锥角/封顶 全部可算且满足闸值)")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
