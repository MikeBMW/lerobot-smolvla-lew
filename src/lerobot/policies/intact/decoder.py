# -*- coding: utf-8 -*-
"""🎯 INTACT 意图解码器 (L4 → L3) — 把 INTACT 输出解码成 L3 可消费的条件。

设计 (docs/design/zmax_l4_intact_policy.md §4):
  INTACT 输出 = ① action chunk [H,4] (metaworld act 空间 ±1) ② 潜空间 z_t/z_goal
                ③ 意图 (goal_displacement = z_goal − z_t) ④ 诊断 (零搜索/延迟/意图范数)
  解码成 L3 能用的两类条件:
    A) u_ff 先验 (4 维, 引擎 u 空间 m/s + 夹爪)  —— **量纲逆运算, 无需标定**
       依据 = 引擎 state_space_sim_real.py 自有约定: act[:3] = clip(u[:3]/K_ACT),
       act[3] = CLOSE if u[3] > 0.5 → 逆运算 u[:3] = act[:3]·K_ACT, u[3] = ±1
       (与 tools/intact_sw_optical_bridge.py 同一口径, 不是新控制律)
    B) L3 条件向量 (l3_cond_dim 维) —— **需要标定映射**, 未标定则诚实拒绝 (reason)
       依据 = Step 2 实测: INTACT 潜空间对引擎流形真值 6 维中 rem/dperp 可解码
              (R² 0.65/0.63), progress/risk/V 不可解码 → 只用可解码维。
       ⚠️ 未标定 (models/intact_l3_map.json 缺失) → 拒绝返回条件并计数, **不写死映射**。

诚实纪律 (老倪红线): 每种失败都返回 reason 并被调用方计数, 不做静默回退。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

import numpy as np

# 引擎标定常数 (与 tools/gui/state_space_sim_real.py:172 同源 —— 单一事实来源, 不复制数值)
K_ACT_DEFAULT = 0.5
GRIP_CLOSE_TH = 0.5          # 引擎侧 u[3] > 0.5 → 闭合 (state_space_sim_real.py:1198)


def _engine_k_act() -> float:
    """从引擎源码读 K_ACT (不硬编码副本; 读不到才退回默认并如实标注)。"""
    try:
        import re
        p = os.path.join(_repo_root(), "tools", "gui", "state_space_sim_real.py")
        with open(p, encoding="utf-8") as f:
            m = re.search(r"^K_ACT\s*=\s*([0-9.]+)", f.read(), re.M)
        if m:
            return float(m.group(1))
    except Exception:
        pass
    return K_ACT_DEFAULT


def _repo_root() -> str:
    d = os.path.dirname(os.path.abspath(__file__))
    while d != os.path.dirname(d):
        if os.path.isdir(os.path.join(d, "reports")):
            return d
        d = os.path.dirname(d)
    return os.getcwd()


@dataclass
class DecodedIntent:
    """解码结果 (每一路都带来源标注, 供面板/日志显示)。"""
    u_ff: np.ndarray | None            # (4,) 引擎 u 空间先验; None = 不注入
    u_ff_source: str                   # "intact(chunk×K_ACT)" / "拒绝(未标定)" / ...
    l3_cond: np.ndarray | None         # (D,) L3 条件向量; None = 未标定
    l3_cond_source: str
    weight: float                      # 融合权重 w ∈ [0,1]
    reason: str = ""
    # 🎯 2026-09-14 L4→L3 条件通道 (老倪: 画布 ssintact_dec → ssdec(DiT) 连线必须真接):
    #   l3_cond 走"标定到引擎流形"的路 (需 models/intact_l3_map.json); 实测 z_t→流形6维 在
    #   13 轮/1935 样本下 LOSO 测试 R²≤0 → **不可标定** (不做假映射)。因此新增这条**无需标定**的
    #   真通道: INTACT 自己的意图增量 δ=z_goal−z_t (单位向量) 直接作为 DiT 的额外条件 token。
    l4_cond: np.ndarray | None = None
    l4_cond_source: str = ""


class IntactIntentDecoder:
    """INTACT → L3 条件解码器 (无参, 全部映射都有实测依据)。"""

    name = "intact_l3_decoder"

    def __init__(self, cond_dim: int = 6, excluded_stages: tuple[str, ...] = ("插入",),
                 action_dim: int = 4, map_path: str | None = None) -> None:
        self.cond_dim = int(cond_dim)
        self.excluded_stages = tuple(excluded_stages or ())
        self.action_dim = int(action_dim)
        self.map_path = map_path or os.path.join(_repo_root(), "models", "intact_l3_map.json")
        self.k_act = _engine_k_act()
        self._map = None
        self.map_loaded = False
        self._load_map()

    # ── 标定映射 (未标定 = 诚实拒绝 L3 条件, 但 u_ff 先验不受影响) ──
    def _load_map(self) -> None:
        try:
            with open(self.map_path, encoding="utf-8") as f:
                d = json.load(f)
            piv = d.get("l3_cond") or {}
            r2 = float(piv.get("r2_min", 0.0))
            if r2 < 0.3:            # 与技能里的闸值一致: R²>0.3 且 null<0.1 才算真信号
                self.reason = (f"标定文件存在但 R²={r2:.3f} < 0.3 (无可解码维) → 不注入 L3 条件")
                return
            W = np.asarray(piv["w"], dtype=np.float64)     # (cond_dim, latent_dim)
            if W.ndim != 2 or W.shape[0] < self.cond_dim:
                self.reason = f"标定矩阵形状不符: {W.shape}"
                return
            self._map = {"w": W, "b": np.asarray(piv.get("b", np.zeros(W.shape[0])), dtype=np.float64),
                         "used_dims": list(piv.get("used_dims") or []), "r2": r2,
                         "null_r2": float(piv.get("null_r2", 1.0))}
            self.map_loaded = True
        except FileNotFoundError:
            self.reason = (f"未标定: {os.path.relpath(self.map_path, _repo_root())} 不存在 → "
                           f"u_ff 先验可用, L3 条件向量不注入 (拒绝 + 计数, 不写死映射)")
        except Exception as e:                                     # noqa: BLE001
            self.reason = f"标定文件读取失败: {type(e).__name__}: {e}"

    # ── 主入口 ──
    def decode(self, out, stage: str = "", cfg=None) -> DecodedIntent:
        """out: IntactOutput (node.step 的返回); stage: 引擎当前阶段名; cfg: IntactConfig (可选)。"""
        excluded = tuple(cfg.l3_exclude_stages) if cfg is not None and hasattr(cfg, "l3_exclude_stages") \
            else self.excluded_stages
        w_max = float(getattr(cfg, "l3_prior_weight", 0.3)) if cfg is not None else 0.3
        st = str(stage or "")
        if st and st in excluded:
            return DecodedIntent(None, f"阶段排除({st})", None, "阶段排除", 0.0,
                                 reason=f"阶段 {st!r} 在排除表内 → 保持引擎解析 u_ff (零回退)")
        chunk = np.asarray(getattr(out, "chunk", None), dtype=np.float64)
        if chunk.ndim == 1:
            chunk = chunk[None]
        if chunk.size == 0 or not np.all(np.isfinite(chunk)):
            return DecodedIntent(None, "拒绝(空/非有限 chunk)", None, "拒绝", 0.0,
                                 reason="INTACT chunk 空或含 NaN/Inf")
        a0 = chunk[0][:self.action_dim]

        # ① u_ff 先验: 量纲逆运算 (act → u), 依据引擎自有约定
        u = np.zeros(4, dtype=np.float64)
        u[:3] = np.clip(a0[:3], -1.0, 1.0) * self.k_act
        u[3] = 1.0 if float(a0[3]) > GRIP_CLOSE_TH else -1.0
        u_ff_src = f"intact(chunk×K_ACT={self.k_act:g})"

        # ② L3 条件向量: 需要标定
        cond, cond_src = None, "拒绝(未标定)"
        mp = self._map
        if mp is not None:
            z = self._latent_vec(out)
            if z is None:
                cond_src = "拒绝(无潜空间)"
            else:
                W, b = mp["w"], mp["b"]
                cond = (W[:, :z.size] @ z[:W.shape[1]]) + b
                cond = np.asarray(cond[:self.cond_dim], dtype=np.float64)
                cond_src = f"标定映射(R²={mp['r2']:.3f}, 维={mp['used_dims'] or '?'})"
        # ③ 权重: INTACT 是"专家提议", 置信度 = 意图是否非退化 (与引擎 w_floor 纪律一致)
        intent_norm = float(getattr(out, "diagnostics", {}).get("intent_norm") or 0.0)
        w = w_max if intent_norm > 1e-6 else 0.0
        reason = "" if abs(w) > 0 else "INTACT 意图退化 (intent_norm≈0) → w=0, 不注入"
        # ④ L4→L3 条件通道 (无需标定): 意图增量 δ=z_goal−z_t 的单位向量 → DiT 额外条件 token
        l4c, l4src = self._intent_cond(out)
        return DecodedIntent(u_ff=u, u_ff_source=u_ff_src, l3_cond=cond,
                             l3_cond_source=cond_src, weight=w, reason=reason,
                             l4_cond=l4c, l4_cond_source=l4src)

    def _intent_cond(self, out) -> tuple[np.ndarray | None, str]:
        """意图增量 δ=z_goal−z_t → 单位向量 (L4→L3 条件; 无需标定, 每帧真值)。"""
        lat = getattr(out, "latent", None) or {}
        if not isinstance(lat, dict):
            return None, "拒绝(无潜空间)"
        def _v(k):
            v = lat.get(k)
            if v is None:
                return None
            a = np.asarray(v, dtype=np.float64).ravel()
            return a if a.size and np.all(np.isfinite(a)) else None
        zt, zg = _v("z_t"), _v("z_goal")
        if zt is None or zg is None or zt.size != zg.size:
            return None, f"拒绝(缺 z_t/z_goal: z_t={zt is not None}, z_goal={zg is not None})"
        d = zg - zt
        n = float(np.linalg.norm(d))
        if not np.isfinite(n) or n < 1e-9:
            return None, f"拒绝(意图增量退化 ‖δ‖={n:.2e})"
        return (d / n), f"intact(意图增量 δ=z_goal−z_t 单位向量, {d.size}维, 无需标定, ‖δ‖={n:.4f})"

    @staticmethod
    def _latent_vec(out) -> np.ndarray | None:
        """取 INTACT 潜空间向量 (z_t 优先; 无则 z_goal; 都无 → None)。"""
        lat = getattr(out, "latent", None) or {}
        for k in ("z_t", "z", "z_goal", "emb"):
            v = lat.get(k) if isinstance(lat, dict) else None
            if v is not None:
                a = np.asarray(v, dtype=np.float64).ravel()
                if a.size and np.all(np.isfinite(a)):
                    return a
        return None

    def describe(self) -> dict:
        mp = self._map
        return {"decoder": self.name, "cond_dim": self.cond_dim,
                "excluded_stages": list(self.excluded_stages),
                "u_ff_path": f"act×K_ACT (K_ACT={self.k_act:g}, 读自引擎源码)",
                "l3_cond_ready": mp is not None,
                "l3_cond_map": os.path.relpath(self.map_path, _repo_root()),
                "trained": mp is not None,
                "reason": self.reason if mp is None else
                f"标定就绪 (R²={mp['r2']:.3f}, null R²={mp['null_r2']:.3f})"}
