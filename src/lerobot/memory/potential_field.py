# -*- coding: utf-8 -*-
"""🧲 分层记忆势场 (Memory Potential Field) — L2 肌肉 / L3 工艺 / L4 工作空间 / 总装机记忆联络

2026-09-13 老倪: 「先把这个势场的逻辑, 实现到 L2肌肉记忆, L3工艺流程记忆, L4物理工作空间记忆,
以及总装机记忆的记忆层联络策略。然后我会将当前独立的 L4 INTACT 功能, 逐步打开每层记忆。」

════════════════════════════════════════════════════════════════════════
统一接口 = 一个标量势场 Φ(x) (x = 末端/光模块头 的 3D 位置, 米)。
  · 势场低处 = 该层记忆认为"该待的地方" (轨迹/谷底)
  · 梯度 -∇Φ = 速度场 = **意图** (intent): 不传技能标签, 只传"往哪个方向走"
  · 所有层共用同一表示 → 层间传递的就是势场参数, 无需各自约定

L2 肌肉记忆   SkillPotentialField
    Φ_SK(x) = ½·k·‖x − x_g‖²  +  λ·(1 − exp(−d⊥(x)² / 2σ²))
               └─ 谷底吸引 (x_g = 该技能真实终点 exit)   └─ 轨迹管壁惩罚 (d⊥ = 到 Champion 轨迹的横向距离)
    性质: ①轨迹上 d⊥=0 → Φ 最小 (老倪要求"轨迹上的点势能低")
          ②离开轨迹越远 Φ 越高 ("轨迹外的地方势能高")
          ③全局极小在 x_g → 沿 −∇Φ 积分必收敛到终点 (李雅普诺夫: Φ̇ = ∇Φ·ẋ = −‖∇Φ‖² ≤ 0)
    数据 = data/muscle_memory.json 的 champ_x (真机真跑冠军轨迹) + io.exit (真终点)

L3 工艺流程记忆 ProcessPotentialField
    Φ_process(x,t) = Σ_k w_k(t)·Φ_SK_k(x),  Σ w_k ≡ 1
    w_k(t) 由**真实段时长** (muscle_memory io.frames) 归一 + 边界平滑过渡 (raised-cosine 交叉淡入)
    → 谷底随时间从 SK01 终点连续移到 SK07 终点 = "流程语义" (不用传技能名)

L4 物理工作空间记忆 GlobalPotentialField
    Φ_global(x,t) = Φ_process(x,t) + Φ_obstacle(x) + Φ_world(x,t)
      Φ_obstacle = 真实工位几何斥力 (孔壁圆柱/台面/孔底, 取自引擎 geom 现场值 — 无引擎则 None+原因, 不编)
      Φ_world    = 世界模型预测项 (预测状态处挂一个移动吸引子); 无预测器时恒 0 且标记 enabled=False

总装机记忆 AssemblyMemory / MemoryLayerBridge
    四层**联络策略**: L2 向上交势场参数(谷底/谷宽/触发), L3 组合成流程势场, L4 叠加障碍/预测,
    顶层做跨层仲裁 + 台账。**逐层开关** (data/memory_layers.json, 默认全关)
    → 老倪逐步打开: 每开一层, compose()/intent()/blend_action() 的贡献随之增加;
      全关时 compose() 返回 None、blend_action 恒等返回入参 (零回退, 可断言)
════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import json
import os
import time

import numpy as np

# ── 默认参数 (物理量纲: 米) ──────────────────────────────────────────
SIGMA_FLOOR = 0.004          # 谷宽下限 4mm (窄谷=精细对位段)
SIGMA_SCALE = 1.6            # σ = 1.6 × 相邻轨迹点中位间距
LAMBDA_RATIO = 4.0           # 管壁惩罚高度 λ = LAMBDA_RATIO·k_att·σ² (与吸引项同量级 → 谷底唯一)
LIN_RATIO = 3.0              # 近谷锥形吸引 k_lin = LIN_RATIO·k_att·σ (保证谷底是唯一极小/必收敛)
LAYERS_FILE = "data/memory_layers.json"
LEDGER_FILE = "data/assembly_memory.json"
STAGE_ORDER = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"]
STAGE_TO_SK = {"接近": "SK01", "对位": "SK02", "下降": "SK03", "抓取": "SK04",
               "抬起": "SK05", "转移": "SK06", "插入": "SK07", "完成": "SK08"}


# ══════════════════════════════════════════════════════════════════
# 几何工具 (折线投影 = 轨迹管壁距离)
# ══════════════════════════════════════════════════════════════════
def project_polyline(x, P):
    """把点 x 投到折线 P(N,3) 上 → (最近点 γ*, 距离 d⊥, 弧长 s*, 段号 i)"""
    x = np.asarray(x, float).ravel()[:3]
    P = np.asarray(P, float)
    if P.ndim != 2 or P.shape[0] == 0:
        return x.copy(), float("inf"), 0.0, -1
    if P.shape[0] == 1:
        return P[0].copy(), float(np.linalg.norm(x - P[0])), 0.0, 0
    A, B = P[:-1], P[1:]
    AB = B - A
    L2 = np.einsum("ij,ij->i", AB, AB)
    L2 = np.where(L2 < 1e-18, 1e-18, L2)
    t = np.clip(np.einsum("ij,ij->i", x - A, AB) / L2, 0.0, 1.0)
    C = A + t[:, None] * AB
    d = np.linalg.norm(x - C, axis=1)
    i = int(np.argmin(d))
    seg = np.sqrt(L2)
    s = float(seg[:i].sum() + t[i] * seg[i])
    return C[i].copy(), float(d[i]), s, i


def polyline_length(P):
    P = np.asarray(P, float)
    if P.shape[0] < 2:
        return 0.0
    return float(np.linalg.norm(np.diff(P, axis=0), axis=1).sum())


def resample_polyline(P, n):
    """按弧长等距重采样 (势场用均匀点, 免得密集段主导)"""
    P = np.asarray(P, float)
    L = polyline_length(P)
    if L <= 1e-12 or n < 2:
        return P.copy()
    s = np.linspace(0.0, L, int(n))
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    cs = np.concatenate([[0.0], np.cumsum(seg)])
    out = np.stack([np.interp(s, cs, P[:, j]) for j in range(P.shape[1])], axis=1)
    return out


# ══════════════════════════════════════════════════════════════════
# L2 · 肌肉记忆势场
# ══════════════════════════════════════════════════════════════════
class SkillPotentialField:
    """单技能势场 (L2 肌肉记忆): 谷底=技能真终点, 谷宽=轨迹横向尺度, 轨迹=Champion 真跑点。"""

    def __init__(self, code, stage, points, exit=None, entry=None, sigma=None,
                 lam=None, k_att=None, n_ok=0, v_cap=None, v_min=None,
                 name="", desc="", evidence="", source="", meta=None):
        P = np.asarray(points, float).reshape(-1, 3)
        if P.shape[0] < 2:
            raise ValueError(f"{code}: 轨迹点太少 ({P.shape[0]})")
        P = resample_polyline(P, min(64, max(8, P.shape[0])))
        self.code, self.stage = code, stage
        self.P = P
        self.x_0 = np.asarray(entry, float).ravel()[:3] if entry is not None else P[0].copy()
        if sigma is None:
            step = np.linalg.norm(np.diff(P, axis=0), axis=1)
            sigma = max(float(np.median(step)) * SIGMA_SCALE, SIGMA_FLOOR)
        self.sigma = float(sigma)
        L0 = polyline_length(P)
        # 吸引项刚度归一: k_att = 2/L² → 沿轨迹 Φ_att 从入口 ~1 降到终点 0 (与管壁项同量级, 无量纲可读)
        self.k_att = float(k_att if k_att is not None else 2.0 / max(L0, 1e-6) ** 2)
        # 管壁惩罚高度 λ 按**与吸引项同量级**归一: λ = lam_ratio·k_att·σ² (lam_ratio 默认 4)
        #   为什么要归一 (实测踩过): λ 取绝对值时 λ/σ² 可达 6e4 ≫ k_att (~1e3) → 管壁项完全压住
        #   吸引项, 轨迹若有回折/勾尾, 流量会停在离谷底 4~5mm 的**次极小**处 (不收敛)。
        #   按 λ∝k_att·σ² 归一后, 谷底是唯一极小 → 收敛有保证 (Lyapunov), 轨迹外势能仍随 d⊥ 单调升。
        self.lam_ratio = float(lam if lam is not None else LAMBDA_RATIO)
        self.lam = float(self.lam_ratio * self.k_att * self.sigma ** 2)
        # 近谷**锥形(线性)**吸引项: k_lin = LIN_RATIO·k_att·σ, Φ_lin = k_lin·‖x−x_g‖
        #   为什么要它 (实测踩过): 只有二次吸引项时, 短轨迹 + 管壁项(λ/σ² 刚度大)会在离谷底
        #   3~5mm 处留一个**次极小** (流量停住不收敛)。加锥形项后 ∇Φ 在除谷底外处处非零
        #   (‖∇Φ_lin‖ ≡ k_lin = 常数, 量级与管壁梯度峰值同阶) → 谷底是唯一极小, 收敛有保证。
        #   学名 = 势场导航的 quadratic-near / conic-far 组合; 这里把 conic 放在**近端**保证收口。
        self.lin_ratio = float(LIN_RATIO if k_att is None else LIN_RATIO)
        self.k_lin = float(self.lin_ratio * self.k_att * self.sigma)
        # ── 谷底必须 = 轨迹真跑末点 (自洽): 势场极小值就在谷底, 沿 −∇Φ 必收敛 ──
        #   传入的 exit (如肌肉库 io.exit) 与轨迹末点同源才采信; 若二者相差 > 3σ 说明**锚点/帧不同源**
        #   (实测: SK06/07 差 127/145mm ≈ PEG_HEAD_OFF_XY=0.13 → io 是抓握点(hand)系, champ_x 是
        #    光模块头(peg head)系) → 谷底用轨迹末点, 原值存 x_g_target 供溯源 + 报差异 (不静默)。
        self.x_g_target = None if exit is None else np.asarray(exit, float).ravel()[:3]
        self.goal_fallback = False
        self.goal_fallback_reason = ""
        self.goal_mismatch_m = 0.0
        x_g = P[-1].copy()
        if self.x_g_target is not None:
            self.goal_mismatch_m = float(np.linalg.norm(self.x_g_target - P[-1]))
            if self.goal_mismatch_m > 3.0 * self.sigma:
                self.goal_fallback = True
                self.goal_fallback_reason = (
                    f"传入谷底与轨迹末点相差 {self.goal_mismatch_m*1000:.1f}mm > 3σ"
                    f"({3*self.sigma*1000:.1f}mm) → 说明锚点/帧不同源 (抓握点 vs 光模块头); "
                    f"谷底改用轨迹末点, 原值存 x_g_target")
            else:
                x_g = self.x_g_target.copy()
        self.x_g = x_g
        self.n_ok, self.v_cap, self.v_min = int(n_ok), v_cap, v_min
        self.name, self.desc, self.evidence, self.source = name, desc, evidence, source
        self.meta = dict(meta or {})
        self.L = polyline_length(P)
        _, d_g, _, _ = project_polyline(self.x_g, P)
        self.goal_offset = float(d_g)

    # ── 势场与梯度 (解析式) ──
    def phi(self, x):
        x = np.asarray(x, float).ravel()[:3]
        g_ = self.x_g
        d_goal = float(np.linalg.norm(x - g_))
        _, d, _, _ = project_polyline(x, self.P)
        return (0.5 * self.k_att * d_goal ** 2 + self.k_lin * d_goal
                + self.lam * (1.0 - np.exp(-(d ** 2) / (2.0 * self.sigma ** 2))))

    def phi_tube(self, x):
        """横向(管壁)分量 — 老倪口径"轨迹上势能低/轨迹外势能高"说的就是这个量:
        轨迹上 d⊥=0 → 0; 偏离轨迹 → 上升 (单调)"""
        _, d, _, _ = project_polyline(np.asarray(x, float).ravel()[:3], self.P)
        return float(self.lam * (1.0 - np.exp(-(d ** 2) / (2.0 * self.sigma ** 2))))

    def grad(self, x):
        x = np.asarray(x, float).ravel()[:3]
        c, d, _, _ = project_polyline(x, self.P)
        v = x - self.x_g
        nv = float(np.linalg.norm(v))
        g_att = self.k_att * v
        if nv > 1e-12:                                   # 锥形项 (谷底处不可导 → 置 0, 谷底即极小)
            g_att = g_att + self.k_lin * v / nv
        if d < 1e-12:
            g_tube = np.zeros(3)
        else:
            g_tube = self.lam * np.exp(-(d ** 2) / (2.0 * self.sigma ** 2)) * (x - c) / (self.sigma ** 2)
        return g_att + g_tube

    def flow(self, x, speed=None):
        """意图方向 = −∇Φ 的**单位方向**; speed 给定则该方向的速率 (m/s) = 单位方向 × speed"""
        f = -self.grad(x)
        n = float(np.linalg.norm(f))
        d = f / n if n > 1e-12 else np.zeros(3)
        return d if speed is None else d * float(speed)

    def velocity(self, x, k_p=2.0, dt=None):
        """执行速度律 (与引擎解析控制器同语义: 比例律 + 速率上/下限):
            v = clip(k_p · d_goal, 0, v_cap)   → 远离谷底全速, 临近谷底自动减速并在谷底停
        返回 (v_vec, info)。dt 给定则附带本步位移 (米)。"""
        x = np.asarray(x, float).ravel()[:3]
        d_goal = float(np.linalg.norm(x - self.x_g))
        v_cap = float(self.v_cap or 0.35)
        v = float(min(v_cap, max(0.0, k_p * d_goal)))
        f = -self.grad(x)
        n = float(np.linalg.norm(f))
        d = f / n if n > 1e-12 else np.zeros(3)
        info = {"v_m_s": round(v, 6), "d_goal_m": round(d_goal, 6), "skill": self.code,
                "at_goal": bool(d_goal <= 1e-3)}
        if dt is not None:
            info["step_m"] = round(v * float(dt), 8)
        return d * v, info

    def direction(self, x):
        """单位意图方向 + 是否已在终点的判据"""
        f = self.flow(x)
        d_goal = float(np.linalg.norm(np.asarray(x, float).ravel()[:3] - self.x_g))
        return f, d_goal

    def diagnostics(self, x):
        c, d, s, _ = project_polyline(x, self.P)
        return {"skill": self.code, "stage": self.stage, "d_perp_m": round(d, 6),
                "s_arc_m": round(s, 6), "len_m": round(self.L, 6),
                "remain_m": round(max(self.L - s, 0.0), 6),
                "d_goal_m": round(float(np.linalg.norm(np.asarray(x, float).ravel()[:3] - self.x_g)), 6),
                "in_tube": bool(d <= 3.0 * self.sigma), "phi": round(float(self.phi(x)), 6)}

    def to_dict(self):
        return {"code": self.code, "stage": self.stage, "sigma_m": round(self.sigma, 6),
                "len_m": round(self.L, 6), "k_att": round(self.k_att, 4), "lam": self.lam,
                "n_ok": self.n_ok, "v_cap": self.v_cap, "v_min": self.v_min,
                "entry": [round(float(v), 6) for v in self.x_0],
                "goal": [round(float(v), 6) for v in self.x_g],
                "goal_target": (None if self.x_g_target is None else
                                [round(float(v), 6) for v in self.x_g_target]),
                "goal_fallback": self.goal_fallback, "goal_fallback_reason": self.goal_fallback_reason,
                "goal_on_traj_offset_m": round(self.goal_offset, 6),
                "points": self.P.shape[0], "source": self.source,
                "name": self.name, "evidence": self.evidence}

    # ── 构造器 (只从真实数据; 缺数据就报错/置空, 不编) ──
    @classmethod
    def from_muscle(cls, code, stage, rec, sk_meta=None, sigma=None):
        """从 data/muscle_memory.json 的一条 <seed>|<stage> 记录建场"""
        X = np.asarray(rec.get("champ_x") or [], float).reshape(-1, 3)
        if X.shape[0] < 2:
            raise ValueError(f"{stage}: champ_x 不足 ({X.shape[0]})")
        io = rec.get("io") or {}
        m = sk_meta or {}
        return cls(code=code, stage=stage, points=X, exit=io.get("exit"), entry=io.get("entry"),
                   sigma=sigma, n_ok=rec.get("n_ok", 0),
                   v_cap=(m.get("ctrl") or {}).get("v_cap"), v_min=(m.get("ctrl") or {}).get("v_min"),
                   name=m.get("name", ""), desc=m.get("desc", ""), evidence=m.get("evidence", ""),
                   source="data/muscle_memory.json champ_x (真机真跑冠军轨迹) + io.exit/goal",
                   meta={"frames": io.get("frames"), "entry_u": io.get("entry_u")})

    @classmethod
    def from_trajectory(cls, code, stage, X, exit=None, **kw):
        """从任意真轨迹 (引擎 rollout tr['peg']/x 等) 建场 — 供引擎在线标定用"""
        return cls(code=code, stage=stage, points=X, exit=exit, **kw)


# ══════════════════════════════════════════════════════════════════
# L3 · 工艺流程势场
# ══════════════════════════════════════════════════════════════════
class ProcessPotentialField:
    """技能序列的时变加权组合: Φ_process(x,t)=Σ w_k(t)Φ_k(x), Σw≡1 (凸组合 → 谷底连续移动)"""

    def __init__(self, fields, durations=None, blend=0.50, name="插入流程"):
        if not fields:
            raise ValueError("流程势场需要至少一个技能势场")
        self.fields = list(fields)
        self.name = name
        n = len(self.fields)
        d = np.asarray(durations if durations is not None else [1.0] * n, float)
        d = np.where(d <= 0, 1.0, d)
        self.frac = d / d.sum()
        self.edges = np.concatenate([[0.0], np.cumsum(self.frac)])       # t∈[0,1] 段边界
        self.blend = float(blend)                                        # 边界交叉淡入宽度 (占段长比例)

    def weights(self, t):
        """t∈[0,1] 归一进度 → (n,) 权重; 段内 1, 边界处与邻段 raised-cosine 交叉 (Σ≡1)"""
        t = float(min(max(t, 0.0), 1.0))
        n = len(self.fields)
        w = np.zeros(n)
        k = int(np.clip(np.searchsorted(self.edges, t, side="right") - 1, 0, n - 1))
        w[k] = 1.0
        for b in range(1, n):                                            # 内部边界 b: 段 b-1 ↔ 段 b
            e = self.edges[b]
            half = 0.5 * self.blend * self.frac[b]
            if abs(t - e) <= half and half > 1e-12:
                u = (t - (e - half)) / (2 * half)                        # 0→1
                s = 0.5 - 0.5 * np.cos(np.pi * u)                        # raised cosine
                w[:] = 0.0
                w[b - 1], w[b] = 1.0 - s, s
                break
        return w

    def _w(self, x, t):
        """权重取法: t 给定 → 时钟权重; t=None → **按状态**软判相位 (模型直驱用)"""
        if t is not None:
            return self.weights(t)
        w, _ = self.weights_from_state(x)
        n = len(self.fields)
        return w if w is not None else np.full(n, 1.0 / n)

    def phi(self, x, t=None):
        w = self._w(x, t)
        return float(sum(w[k] * self.fields[k].phi(x) for k in range(len(self.fields))))

    def grad(self, x, t=None):
        w = self._w(x, t)
        g = np.zeros(3)
        for k, f in enumerate(self.fields):
            if w[k] > 1e-9:
                g += w[k] * f.grad(x)
        return g

    def flow(self, x, t=None, speed=None):
        w = self._w(x, t)
        f = np.zeros(3)
        for k, fk in enumerate(self.fields):
            if w[k] > 1e-9:
                f += w[k] * fk.flow(x)               # 各技能先给单位方向 → 凸组合后再缩放 (量纲一致)
        n = float(np.linalg.norm(f))
        d = f / n if n > 1e-12 else np.zeros(3)
        return d if speed is None else d * float(speed)

    def active(self, t):
        k = int(np.argmax(self.weights(t)))
        return self.fields[k]

    def weights_from_state(self, x, k_sigma=3.0):
        """**按状态**软判当前相位: 到各技能轨迹管的横向距离 d_k → w ∝ exp(−d_k²/2(3σ_k)²), Σw=1。
        为什么需要它: 模型直驱时"时钟进度 t"与实际所在相位不同步 (速度/时长都变了) →
        用"你在哪条轨迹管附近"判相位, 物理上自洽 (也天然给出跨技能过渡)。"""
        x = np.asarray(x, float).ravel()[:3]
        d = np.array([project_polyline(x, f.P)[1] for f in self.fields], float)
        sig = np.array([f.sigma for f in self.fields], float)
        e = np.exp(-(d ** 2) / (2.0 * (k_sigma * sig) ** 2))
        s = float(e.sum())
        if s < 1e-12:
            return None, d
        return e / s, d

    def active_from_state(self, x):
        """按状态判当前技能: 软权重最大者; 若全部远离 (softmax 下溢) → 取**最近**轨迹管那个
        (仍是真几何判据; 距离由 diagnostics/d_perp 如实报出, 不假装贴近)。"""
        w, d = self.weights_from_state(x)
        if w is not None:
            return self.fields[int(np.argmax(w))], d
        if not self.fields:
            return None, d
        return self.fields[int(np.argmin(d))], d

    def goal_path(self, n=40):
        """谷底随时间: 各 t 处 max-权重技能的终点 (用于验证"谷底按时序移动")"""
        out = []
        for t in np.linspace(0.0, 1.0, n):
            a = self.active(t)
            out.append((round(float(t), 4), a.code, a.stage,
                        [round(float(v), 5) for v in a.x_g]))
        return out

    def min_gain(self, n=25):
        """流程势场在各 t 的谷底增益 (Σ w/k 的等效刚度), 用于稳定性说明"""
        return min(float(sum(self.weights(t)[k] * self.fields[k].k_att
                             for k in range(len(self.fields)))) for t in np.linspace(0, 1, n))

    def to_dict(self):
        return {"name": self.name, "skills": [f.code for f in self.fields],
                "frac": [round(float(v), 4) for v in self.frac],
                "blend": self.blend, "min_gain": round(self.min_gain(), 4),
                "source": "段时长 = muscle_memory io.frames (真跑帧数) 归一"}

    @classmethod
    def from_skill_fields(cls, fields, durations=None, **kw):
        return cls(fields, durations=durations, **kw)


# ══════════════════════════════════════════════════════════════════
# L4 · 障碍势场 (真实工位几何) + 世界模型预测项
# ══════════════════════════════════════════════════════════════════
class ObstacleField:
    """真实工位几何斥力: ①台面 (z < z_table 罚) ②孔壁圆柱 (靠近孔轴外壁罚) — 参数必须来自现场"""

    def __init__(self, hole=None, goal=None, z_table=None, hole_radius=0.016,
                 k_wall=2.0, k_table=2.0, sigma_wall=0.004, source=""):
        self.hole = None if hole is None else np.asarray(hole, float).ravel()[:3]
        self.goal = None if goal is None else np.asarray(goal, float).ravel()[:3]
        self.z_table = None if z_table is None else float(z_table)
        self.r = float(hole_radius)
        self.k_wall, self.k_table, self.sigma_wall = float(k_wall), float(k_table), float(sigma_wall)
        self.source = source

    @classmethod
    def from_engine(cls, root="/home/ubuntu/lerobot-smolvla-lew", seed=104):
        """从真实引擎读现场几何 (geom: hole/goal/peg_grasp)。取不到 → (None, 原因), 绝不编造。
        ⚠️ geom 在 _reset 里现场采样 (构造时为空) → 必须先真跑一次 reset 才读得到。"""
        import sys
        try:
            p = os.path.join(root, "tools", "gui")
            if p not in sys.path:
                sys.path.insert(0, p)
            from state_space_sim_real import RealStateSpaceSim       # noqa: PLC0415
            sim = RealStateSpaceSim(seed=int(seed), vision=False, mode="insert", log=lambda *a: None)
            g = dict(getattr(sim, "geom", {}) or {})
            if not g:                                     # 构造后 geom 为空 → 真 reset 采样几何
                sim._reset(int(seed))
                g = dict(getattr(sim, "geom", {}) or {})
            hole = g.get("hole")
            goal = g.get("goal")
            if hole is None or goal is None:
                return None, f"引擎 geom 缺 hole/goal (现有键: {sorted(g)[:8]})"
            ztbl = None
            for k in ("table_z", "z_table", "table"):
                if k in g:
                    ztbl = float(np.asarray(g[k]).ravel()[-1])
                    break
            hole_r = float(g.get("hole_radius", 0.016))
            return cls(hole=hole, goal=goal, z_table=ztbl, hole_radius=hole_r,
                       source="引擎 geom 现场值 (state_space_sim_real.RealStateSpaceSim._reset 采样)"), ""
        except Exception as e:                                        # noqa: BLE001
            return None, f"{type(e).__name__}: {e}"

    def phi(self, x):
        if self.hole is None:
            return 0.0
        x = np.asarray(x, float).ravel()[:3]
        p = 0.0
        if self.z_table is not None:
            dz = self.z_table - x[2]
            if dz > 0:
                p += 0.5 * self.k_table * dz ** 2
        d_ax = float(np.linalg.norm(x[:2] - self.hole[:2]))
        if x[2] < self.hole[2] + 0.02:                     # 只在孔口附近考虑孔壁
            gap = abs(d_ax - self.r)
            p += self.k_wall * np.exp(-(gap ** 2) / (2.0 * self.sigma_wall ** 2))
        return float(p)

    def grad(self, x):
        if self.hole is None:
            return np.zeros(3)
        x = np.asarray(x, float).ravel()[:3]
        g = np.zeros(3)
        if self.z_table is not None and x[2] < self.z_table:
            g[2] += -self.k_table * (self.z_table - x[2])
        d_ax = float(np.linalg.norm(x[:2] - self.hole[:2]))
        if x[2] < self.hole[2] + 0.02 and d_ax > 1e-9:
            gap = d_ax - self.r
            coef = self.k_wall * np.exp(-(gap ** 2) / (2.0 * self.sigma_wall ** 2)) * gap / (self.sigma_wall ** 2)
            rhat = (x[:2] - self.hole[:2]) / d_ax
            g[:2] += -coef * rhat                          # 靠壁 → 沿径向外推 (斥力)
        return g

    def to_dict(self):
        return {"available": self.hole is not None, "hole": None if self.hole is None else
                [round(float(v), 5) for v in self.hole], "hole_radius": self.r,
                "z_table": self.z_table, "source": self.source}


class WorldField:
    """世界模型预测项: 在预测的下一个状态 x̂ 处挂移动吸引子 (Φ_w = −½k_w‖x − x̂‖²)"""

    def __init__(self, gain=0.5):
        self.gain = float(gain)
        self._pred = None

    def set_predictor(self, fn):
        """fn(x, t) -> 预测 3D 位置 (真实预测器, 例如 L4 流形/JEPA 预测); None = 关闭"""
        self._pred = fn
        return self

    @property
    def enabled(self):
        return self._pred is not None

    def _xhat(self, x, t):
        if self._pred is None:
            return None
        try:
            v = self._pred(x, t)
            return None if v is None else np.asarray(v, float).ravel()[:3]
        except Exception:                                              # noqa: BLE001
            return None

    def phi(self, x, t=None):
        xh = self._xhat(x, t)
        if xh is None:
            return 0.0
        x = np.asarray(x, float).ravel()[:3]
        return float(-0.5 * self.gain * np.dot(x - xh, x - xh))

    def grad(self, x, t=None):
        xh = self._xhat(x, t)
        if xh is None:
            return np.zeros(3)
        x = np.asarray(x, float).ravel()[:3]
        return -self.gain * (x - xh)


class GlobalPotentialField:
    """L4 物理工作空间记忆 = 流程势场 + 障碍势场 + 世界模型预测项"""

    def __init__(self, process, obstacle=None, world=None, name="物理工作空间记忆"):
        self.process = process
        self.obstacle = obstacle
        self.world = world
        self.name = name

    def phi(self, x, t=None):
        return float(self.process.phi(x, t)
                     + (self.obstacle.phi(x) if self.obstacle else 0.0)
                     + (self.world.phi(x, t) if self.world else 0.0))

    def grad(self, x, t=None):
        g = self.process.grad(x, t)
        if self.obstacle:
            g = g + self.obstacle.grad(x)
        if self.world:
            g = g + self.world.grad(x, t)
        return g

    def flow(self, x, t=None, speed=None):
        f = -self.grad(x, t)
        n = float(np.linalg.norm(f))
        d = f / n if n > 1e-12 else np.zeros(3)
        return d if speed is None else d * float(speed)

    def anomaly(self, x, t, tube_sigma=3.0):
        """异常判据: 当前点超出当前激活技能的轨迹管 (d⊥ > 3σ) → 需回退/重对准"""
        act = self.process.active(t)
        diag = act.diagnostics(x)
        out = {"skill": act.code, "d_perp_m": diag["d_perp_m"], "in_tube": diag["in_tube"],
               "action": "hold" if diag["in_tube"] else "recover"}
        if self.obstacle and self.obstacle.hole is not None:
            x3 = np.asarray(x, float).ravel()[:3]
            d_ax = float(np.linalg.norm(x3[:2] - self.obstacle.hole[:2]))
            out["hole_axis_gap_m"] = round(abs(d_ax - self.obstacle.r), 6)
        return out

    def to_dict(self):
        return {"name": self.name, "process": self.process.to_dict(),
                "obstacle": (self.obstacle.to_dict() if self.obstacle else
                             {"available": False, "reason": "未接入引擎几何"}),
                "world": {"enabled": bool(self.world and self.world.enabled),
                          "gain": (self.world.gain if self.world else None)}}


# ══════════════════════════════════════════════════════════════════
# 总装机记忆 · 记忆层联络策略 (逐层开关)
# ══════════════════════════════════════════════════════════════════
class MemoryLayerBridge:
    """四层联络: L2 势场 → L3 流程势场 → L4 全局势场 → 总装机仲裁。
    逐层开关 (默认全关) → 老倪逐步打开; 全关时本类**恒等不干预** (可断言零回退)。
    """

    LAYERS = ("L2", "L3", "L4", "assembly")

    def __init__(self, root="/home/ubuntu/lerobot-smolvla-lew", layers=None, fields=None,
                 process=None, global_field=None, durations=None, reason="", obstacle=None,
                 world=None):
        self.root = root
        self.fields = list(fields or [])
        self.process = process
        self.global_field = global_field
        self.reason = reason
        self.obstacle, self.world = obstacle, world
        self._gates = self._load_gates()
        if layers:
            self._gates.update({k: int(bool(v)) for k, v in layers.items() if k in self.LAYERS})

    # ── 开关文件 (老倪逐步打开的地方) ──
    def _gates_path(self):
        return os.path.join(self.root, LAYERS_FILE)

    def _load_gates(self):
        d = {k: 0 for k in self.LAYERS}
        try:
            with open(self._gates_path(), encoding="utf-8") as f:
                j = json.load(f) or {}
            for k in self.LAYERS:
                if k in j:
                    d[k] = int(bool(j[k]))
        except Exception:                                              # noqa: BLE001
            pass
        return d

    def gates(self):
        return dict(self._gates)

    def set_gate(self, layer, on, persist=True):
        if layer not in self.LAYERS:
            raise KeyError(f"层名必须是 {self.LAYERS}")
        self._gates[layer] = int(bool(on))
        if persist:
            p = self._gates_path()
            os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
            cur = {}
            try:
                cur = json.load(open(p, encoding="utf-8")) or {}
            except Exception:                                          # noqa: BLE001
                pass
            cur.update({layer: int(bool(on))})
            cur["updated"] = time.strftime("%F %T")
            with open(p, "w", encoding="utf-8") as f:
                json.dump(cur, f, ensure_ascii=False, indent=1)
        return self.gates()

    def any_on(self):
        return any(self._gates[k] for k in ("L2", "L3", "L4"))

    # ── 联络策略描述 (画布/日志展示用) ──
    def describe(self):
        return {
            "L2 肌肉记忆": {"gate": self._gates["L2"], "载体": "skill_potential_fields",
                            "向上传": ["Φ_SK 函数", "−∇Φ_SK 梯度场", "谷底 x_g", "谷宽 σ",
                                       "触发条件 (evidence)", "速度上限 v_cap"],
                            "数据": "data/muscle_memory.json champ_x/io (真跑冠军轨迹)",
                            "本层技能": [f.code for f in self.fields]},
            "L3 工艺流程记忆": {"gate": self._gates["L3"], "载体": "process_potential_field",
                                "向上传": ["技能序列", "权重 w_k(t)", "谷底时变轨迹", "切换边界"],
                                "数据": "段时长 = 各技能真跑帧数归一 (muscle_memory io.frames)",
                                "组合": (self.process.to_dict() if self.process else None)},
            "L4 物理工作空间记忆": {"gate": self._gates["L4"], "载体": "global_potential_field",
                                    "向上传": ["全局势场", "激活势场选择", "异常/恢复触发"],
                                    "叠加": {"障碍": bool(self.obstacle and self.obstacle.hole is not None),
                                             "世界模型预测": bool(self.world and self.world.enabled)}},
            "总装机记忆": {"gate": self._gates["assembly"], "载体": "assembly ledger + 仲裁",
                           "职责": ["跨层仲裁 (接触段技能优先)", "台账 (任务/层开关/结果)", "逐层开关持久化"]},
        }

    def status(self):
        return {"gates": self.gates(), "any_on": self.any_on(),
                "skills": [f.code for f in self.fields], "n_skills": len(self.fields),
                "process": bool(self.process), "obstacle": bool(self.obstacle),
                "world": bool(self.world and self.world.enabled), "reason": self.reason}

    # ── 组合势场 (只按已开的层) ──
    def _active(self, x, t):
        """当前技能: t 给定 → 按时钟; t=None → **按状态** (模型直驱时时钟与实际相位不同步)"""
        if self.process is None:
            return None
        if t is None:
            a, _ = self.process.active_from_state(x)
            return a
        return self.process.active(t)

    def compose(self, x, t=None):
        """返回 (Φ 或 None, 各层贡献明细)。全关 → (None, {...all 0, 'active': False})"""
        if not self.any_on():
            return None, {"active": False, "reason": "所有记忆层已关 (零干预)",
                          "L2": 0.0, "L3": 0.0, "L4": 0.0}
        contrib = {"active": True, "x": [round(float(v), 5) for v in np.asarray(x, float).ravel()[:3]],
                   "t": (None if t is None else round(float(t), 4))}
        phi = 0.0
        act = self._active(x, t)
        if self._gates["L2"] and act is not None:
            phi += act.phi(x)
            contrib["L2"] = round(float(act.phi(x)), 6)
            contrib["L2_skill"] = act.code
        if self._gates["L3"] and self.process is not None:
            p2 = self.process.phi(x, t)
            contrib["L3"] = round(float(p2), 6)
            phi += p2
        if self._gates["L4"]:
            po = self.obstacle.phi(x) if self.obstacle else 0.0
            pw = self.world.phi(x, t) if self.world else 0.0
            contrib["L4_obstacle"], contrib["L4_world"] = round(float(po), 6), round(float(pw), 6)
            phi += po + pw
        contrib["phi_total"] = round(float(phi), 6)
        return float(phi), contrib

    def grad(self, x, t=None):
        """按已开层算梯度 (全关 → 零向量)"""
        g = np.zeros(3)
        if not self.any_on() or self.process is None:
            return g
        if self._gates["L2"]:
            a = self._active(x, t)
            if a is not None:
                g = g + a.grad(x)
        if self._gates["L3"]:
            g = g + self.process.grad(x, t)
        if self._gates["L4"]:
            if self.obstacle:
                g = g + self.obstacle.grad(x)
            if self.world:
                g = g + self.world.grad(x, t)
        if g[0] == g[1] == g[2] == 0:
            return np.zeros(3)
        # 逐层打开的语义: L2/L3 是"方向" (单位场), L4 的障碍是"修正" → 归一后按层权重合成
        n = float(np.linalg.norm(g))
        return g / n if n > 1e-12 else np.zeros(3)

    def intent(self, x, t=None, v_cap=None):
        """意图 (给 INTACT/执行器): 3D 单位方向 + 步长(m/s) + 当前技能 + 置信。
        t=None → **相位由状态定** (推荐: 模型直驱时时钟与实际相位不同步); t 给定 → 按时钟权重。"""
        act, d_use = None, None
        if self.process is not None:
            if t is None:
                act, d_use = self.process.active_from_state(x)
            else:
                act = self.process.active(t)
        g = self.grad(x, t)
        if not self.any_on() or act is None:
            return {"active": False, "dir": [0.0, 0.0, 0.0], "step_m": 0.0,
                    "skill": None, "conf": 0.0, "reason": "记忆层全关"}
        diag = act.diagnostics(x)
        conf = float(np.exp(-(diag["d_perp_m"] ** 2) / (2.0 * (3.0 * act.sigma) ** 2)))
        spd = float(v_cap if v_cap is not None else (act.v_cap or 0.2))
        return {"active": True, "dir": [float(v) for v in (-g)],
                "step_m": round(spd, 5), "skill": act.code, "stage": act.stage,
                "conf": round(conf, 4), "d_perp_m": diag["d_perp_m"],
                "d_goal_m": diag["d_goal_m"], "phase_from": ("clock" if t is not None else "state"),
                "gates": self.gates()}

    def blend_action(self, u_model, x, t=None, w_max=0.5, k_act=0.5, w_floor=0.2, d_max=0.5,
                     w_far=0.85, d_near_m=0.03, d_far_m=0.15):
        """执行钩子 (逐步打开): u = (1−w)·u_model + w·u_field, w = w_max·max(conf, w_floor)。
        层全关 → w=0, 恒等返回 (可断言零回退)。
        w_floor = **恢复下限**: 出轨迹管时 (conf→0) 仍留一部分场权, 把状态拉回管里 (L4 的
          "失败自主恢复"语义); 设 0 即纯置信门。
        d_max = 覆盖范围闸: 离**所有**轨迹管都超过 d_max (默认 500mm) → 记忆不覆盖该状态,
          不干预 (诚实边界, 不硬拽)。

        ── 🚀 2026-09-14 增益调度 (阶梯第一版实测暴露的真问题) ──
        第一版 30 格实测: 模型直驱 0/30 全失败 (插入距离 585~611mm, 模型塌缩到均值动作),
        而记忆层**每步都介入** (3000/3000) 但 w̄ 恒 = 0.1 = w_max·w_floor (现场 conf 恒 0) →
        10% 的场权根本扳不动 600mm 模型误差 ⇒ L2/L23/L234/总装 与 off 的差异只有噪声级
        (609.4 vs 588.5mm) = **不算提升**。
        修法 (增益调度, 不是拍脑袋): **离轨迹管越远 → 场权越大**; 贴管附近 (模型本来就跟得住)
        维持原公式不动 (保证不回退)。
            far = clip((d_perp − d_near) / (d_far − d_near), 0, 1)
            w   = max(w_max·max(conf, w_floor),  w_far·far)
        默认 d_near=30mm (在管内, 场不抢权) / d_far=150mm (远场, 场主导 w=0.85)。
        参数全部可在调用处覆盖; 说明写进结果 (far / w_far 字段) 以便同口径对比。
        """
        u = np.asarray(u_model, float).ravel()[:4].copy()
        it = self.intent(x, t)
        if not it["active"]:
            return u, {"w": 0.0, "applied": False, "reason": "记忆层全关 → u 原样"}
        conf = float(it["conf"])
        d_perp = float(it.get("d_perp_m") or 0.0)
        if d_perp > float(d_max):
            return u, {"w": 0.0, "applied": False, "reason": f"离最近轨迹管 {it['d_perp_m']*1000:.0f}mm "
                                                            f"> 覆盖上限 {d_max*1000:.0f}mm → 不干预",
                       "skill": it["skill"], "conf": conf, "d_perp_m": it["d_perp_m"]}
        far = float(np.clip((d_perp - float(d_near_m)) / max(float(d_far_m) - float(d_near_m), 1e-9),
                            0.0, 1.0))
        w = max(float(w_max * max(conf, w_floor)), float(w_far) * far)
        if w <= 1e-6:
            return u, {"w": 0.0, "applied": False, "reason": "置信≈0 且无恢复下限 → 不干预",
                       "skill": it["skill"], "conf": conf, "d_perp_m": it["d_perp_m"]}
        uf = np.asarray(it["dir"], float) * float(it["step_m"]) / max(k_act, 1e-6)  # → env ±1 量纲
        u[:3] = np.clip((1.0 - w) * u[:3] + w * np.clip(uf, -1, 1), -1.0, 1.0)
        return u, {"w": round(w, 4), "applied": True, "skill": it["skill"], "conf": conf,
                   "d_perp_m": it["d_perp_m"], "d_goal_m": it["d_goal_m"],
                   "far": round(far, 3), "w_far_gain": round(float(w_far) * far, 4),
                   "phase_from": it["phase_from"], "u_model": [round(float(v), 4) for v in u_model],
                   "u_field": [round(float(v), 4) for v in uf],
                   "u_out": [round(float(v), 4) for v in u]}

    # ── 总装机记忆台账 + 跨层仲裁 ──
    def arbitrate(self, stage, contact_p=0.0):
        """跨层仲裁 (总装机记忆职责): 接触段 (<插入) 以技能势场(L2)为主, 自由段以流程势场(L3)为主"""
        contact = bool(stage in ("下降", "抓取", "插入")) or float(contact_p) > 0.3
        prim = "L2" if contact else "L3"
        return {"stage": stage, "contact": contact, "primary_layer": prim,
                "gain_scale": (1.0, 0.6) if contact else (0.6, 1.0),
                "note": "接触段技能势场优先 (局部精对准) / 自由段流程势场优先 (长程引导)"}

    def record_outcome(self, task, done, steps=None, insert_mm=None, layers=None, note=""):
        p = os.path.join(self.root, LEDGER_FILE)
        try:
            d = json.load(open(p, encoding="utf-8")) if os.path.isfile(p) else {"runs": []}
        except Exception:                                              # noqa: BLE001
            d = {"runs": []}
        d.setdefault("runs", []).append({
            "ts": time.strftime("%F %T"), "task": task, "done": bool(done), "steps": steps,
            "insert_mm": insert_mm, "layers": (layers if layers is not None else self.gates()),
            "note": note, "reason": self.reason})
        d["updated"] = time.strftime("%F %T")
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        return d["runs"][-1]

    def ledger(self, n=5):
        p = os.path.join(self.root, LEDGER_FILE)
        try:
            d = json.load(open(p, encoding="utf-8"))
            return {"n": len(d.get("runs") or []), "last": (d.get("runs") or [])[-n:]}
        except Exception:                                              # noqa: BLE001
            return {"n": 0, "last": []}

    # ── 从真实数据装配 (L2/L3/L4) ──
    @classmethod
    def from_real_data(cls, root="/home/ubuntu/lerobot-smolvla-lew", seed=104, use_engine_geom=True):
        """用 data/muscle_memory.json 的冠军轨迹建 L2, 按时序建 L3, 引擎几何建 L4。缺数据不编。"""
        mpath = os.path.join(root, "data", "muscle_memory.json")
        if not os.path.isfile(mpath):
            return cls(root=root, reason=f"缺 {mpath}")
        mm = json.load(open(mpath, encoding="utf-8"))
        sk_meta = {}
        try:                                                          # 技能元数据 (v_cap/evidence)
            import sys
            sp = os.path.join(root, "src")
            if sp not in sys.path:
                sys.path.insert(0, sp)
            from lerobot.policies.left_right.state_space.skills.atomic_skills import SKILLS  # noqa: PLC0415
            for s in SKILLS:
                nm = getattr(s, "stage", "")
                key = [k for k in STAGE_TO_SK if k and k in str(nm)]
                if key:
                    sk_meta[key[0]] = {"name": getattr(s, "name", ""), "desc": getattr(s, "desc", ""),
                                       "evidence": getattr(s, "evidence", ""),
                                       "ctrl": getattr(s, "ctrl", {}) or {}}
        except Exception:                                              # noqa: BLE001
            sk_meta = {}

        fields, durs, missing = [], [], []
        for stg in STAGE_ORDER:
            rec = mm.get(f"{seed}|{stg}")
            if rec is None or not rec.get("champ_x"):
                missing.append(stg)
                continue
            code = STAGE_TO_SK.get(stg, "SK--")
            try:
                f = SkillPotentialField.from_muscle(code, stg, rec, sk_meta=sk_meta.get(stg))
                fields.append(f)
                durs.append((rec.get("io") or {}).get("frames") or len(rec["champ_x"]))
            except Exception as e:                                     # noqa: BLE001
                missing.append(f"{stg}({type(e).__name__})")
        proc = ProcessPotentialField(fields, durations=durs) if fields else None
        obstacle, why = (ObstacleField.from_engine(root) if use_engine_geom else (None, "未启用"))
        world = WorldField(gain=0.5)                                   # 无预测器 → enabled=False
        gf = GlobalPotentialField(proc, obstacle, world) if proc else None
        reason = ("ok" if fields else "无可用技能轨迹") + (f" · 缺阶段 {missing}" if missing else "") \
            + ("" if obstacle else f" · 障碍场未接 ({why[:60]})")
        return cls(root=root, fields=fields, process=proc, global_field=gf, durations=durs,
                   obstacle=obstacle, world=world, reason=reason)


# ══════════════════════════════════════════════════════════════════
# 自检 (python -m lerobot.memory.potential_field 或直接跑本文件)
# ══════════════════════════════════════════════════════════════════
def _selftest():
    P = np.stack([np.linspace(0, 0.12, 25),
                  np.zeros(25) + 0.02 * np.sin(np.linspace(0, 3, 25)),
                  np.linspace(0.20, 0.16, 25)], axis=1)
    f = SkillPotentialField("SK01", "接近", P, exit=P[-1], entry=P[0], n_ok=3, v_cap=0.35)
    x1 = P[0] + np.array([0.004, 0.004, 0.004])
    h = 1e-6
    num = np.array([(f.phi(x1 + np.eye(3)[j] * h) - f.phi(x1 - np.eye(3)[j] * h)) / (2 * h)
                    for j in range(3)])
    print("① 解析梯度 vs 数值梯度 最大绝对误差 = %.3e" % float(np.abs(num - f.grad(x1)).max()))
    # ② 同弧长位置比较 (公平): 轨迹上 d⊥=0 → 横向势 0; 横向偏移 5/10/20mm → 单调上升
    i = 12
    perp = np.array([0.0, 1.0, 0.0])
    print("② 横向(管壁)势 Φ_tube 同点比较: 轨迹上 %.6f < 偏 5mm %.6f < 10mm %.6f < 20mm %.6f (应单调升)" % (
        f.phi_tube(P[i]), f.phi_tube(P[i] + perp * 0.005),
        f.phi_tube(P[i] + perp * 0.010), f.phi_tube(P[i] + perp * 0.020)))
    # ③ 真实执行律: ẋ = −∇Φ 单位方向 × v_clip(k_p·d_goal, 0, v_cap)  (引擎 dt=0.02)
    x = P[0] + np.array([0.006, -0.006, 0.0])
    hist = [float(f.phi(x))]
    n_step, info = 0, {}
    while n_step < 3000:
        v, info = f.velocity(x, k_p=2.0, dt=0.02)
        x = x + 0.02 * v
        hist.append(float(f.phi(x)))
        n_step += 1
        if info["at_goal"]:
            break
    print("③ 沿 −∇Φ 收敛 (v=clip(k_p·d,0,v_cap), dt=0.02): %d 步 · 终点距谷底 %.6f m · "
          "Φ 单调降 (至 at_goal)=%s · 末速 %.4f m/s" % (
              n_step, float(np.linalg.norm(x - f.x_g)),
              all(hist[i + 1] < hist[i] + 1e-12 for i in range(len(hist) - 2)), info.get("v_m_s", 0)))
    g2 = SkillPotentialField("SK02", "对位", P + np.array([0, 0, -0.04]), exit=P[-1] + np.array([0, 0, -0.04]))
    proc = ProcessPotentialField([f, g2], durations=[30, 20], blend=0.3)
    ws = np.array([proc.weights(t) for t in np.linspace(0, 1, 41)])
    print("④ L3 权重: Σw 误差 %.2e · 谷底序列 %s" % (
        float(np.abs(ws.sum(1) - 1).max()), [c for _, c, _ in proc.goal_path(6)]))
    ob, why = ObstacleField.from_engine("/home/ubuntu/lerobot-smolvla-lew")
    print("⑤ L4 障碍场接引擎几何: %s %s" % (ob is not None, ("· " + str(ob.to_dict())) if ob else "· 原因: " + why))
    br = MemoryLayerBridge(root="/home/ubuntu/lerobot-smolvla-lew", fields=[f, g2], process=proc,
                           obstacle=ob, world=WorldField())
    print("⑥ 联络策略: 全关 compose=%s · intent=%s" % (br.compose(P[5], 0.5)[0], br.intent(P[5], 0.5)["active"]))
    u = np.array([0.3, 0.0, -0.1, 0.6])
    print("⑦ blend_action 全关恒等 =", bool(np.allclose(br.blend_action(u, P[5], 0.5)[0], u)))
    return True


if __name__ == "__main__":
    _selftest()
