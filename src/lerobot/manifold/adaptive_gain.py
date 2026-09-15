# -*- coding: utf-8 -*-
"""🎚 adaptive_gain.py — 卡尔曼式**自适应增益** (老倪 2026-09-16 设计)

老倪原话: "前馈 MLP 主执行这个通道, 需要参考卡尔曼滤波增益的方式, 即系统根据算法结构自动调整增益:
增益大了则更相信 L4 (导航增益), 增益小了默认使用 L2 前馈加速器 (肌肉记忆, 直接连物理世界);
L3 是流程增益 (DiT 把 L4 意图转成流程动作), 流程动作又被 L2 肌肉记忆修正, 最终物理执行。"

本模块把这句话写成**可算、可查、可回退**的东西 (纯 numpy, 不依赖 torch/引擎):

    先验 (L2 肌肉记忆/解析伺服, 直接连物理):  u⁻ = u_l2
    先验不确定度:                            P⁻ = κ·P + Q0 + Σ(事件项 Q_i)
    观测 (上层, 二路):                        y_nav = L4 意图 (对齐后), y_flow = L3 DiT 流程动作
    观测噪声:                                 R_i = (标定残差)² + R0_i
    卡尔曼增益:                               K_i = P⁻ / (P⁻ + R_i)        ← 唯一"自动调整"机制
    更新:                                     u = u⁻ + K_nav·(y_nav−u⁻) + K_flow·(y_flow−u⁻)
    后验:                                     P = (1 − K_eff)·P⁻
    肌肉记忆修正 (L2 收口):                     u ← u + K_mm·(u_champ − u),  K_mm = K_mm0·(1−K_nav)

读法 (物理直觉):
  · 熟场景: 肌肉记忆有标杆 (mm 命中) + 无 OOD 事件 → Q≈Q0, P 逐步被 κ 衰减 → K→K_min → **默认 L2**;
  · 泛化/受扰: 布局超出蒸馏域 (σ 超门) / 没练过 (无标杆) / 新息异常大 (模型跟不上) / 进程停滞 (V 不降)
    → 事件项抬 Q → P 涨 → **K 自动抬升 → 更信 L4 导航 / L3 流程**;
  · 事件消失后 κ 把它拉回 → 增益自动回落, 不会长期脱离 L2 (稳定性锚在 L2 势函数)。

硬约束 (与 capability_stack 同一纪律):
  I1 单出口: 本模块只产**参考**; 执行仍由引擎 sched.decide + safety.saturate 收口。
  I2 收缩: u 投影进 U_L2 (lo,hi), 全量夹紧并记账; 上层增益有上界 (nav/flow 各 ≤0.5)。
  I5 零回退: `enabled=False` 或增益=0 时 `u` **逐位等于** u_l2 (见 self_test 的 hash 判据)。

自检: python src/lerobot/manifold/adaptive_gain.py   (含 5 组结构性判据 + hash 零回退)
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import numpy as np

# ── 默认常数 (全部可覆盖; 出厂值经自检校准, 见文末 self_test) ──────────────────
KMIN = 0.0            # 增益下界 (0 = 完全回到 L2)
KMAX_NAV = 0.5        # L4 导航增益上界 (上层不许翻身当执行者)
KMAX_FLOW = 0.5       # L3 流程增益上界
KAPPA = 0.90          # 每步先验方差衰减 (稳定后自动"忘记"上层 → 增益回落)
P0 = 0.02             # 初始先验不确定度 (小 = 一开始就信 L2)
Q0 = 1e-4             # 每步过程噪声 (常态漂移)
R0_NAV = 0.10         # L4 观测噪声底 (对齐层残差量级; 标定后可用真残差替换)
R0_FLOW = 0.06        # L3 流程观测噪声底
Q_OOD = 0.05          # 域外事件 (σ 超门) 的 Q 抬升
Q_MM_MISS = 0.03      # 没练过 (无肌肉记忆标杆) 的 Q 抬升
Q_INNOV = 0.04        # 新息异常 (受扰/模型跟不上) 的 Q 抬升
Q_STALL = 0.06        # 进程停滞 (李雅普诺夫势不降) 的 Q 抬升
K_MM0 = 0.35          # 肌肉记忆修正强度底 (仅当 K_nav 小时起作用)
INNOV_K = 3.0         # 新息异常判据: |ν| > INNOV_K·√R
# 熟场景零增益闸: 无事件时 P 收敛到 Q0/(1−κ) ≈ 1e-3 → 增益残留 ~1e-2 (不是"默认用 L2")。
# 低于该阈值 ⇒ 增益**硬置 0** (逐位回到 L2, 也给 A/B 一个干净的"熟场景=纯 L2"判据)。
P_ZERO_K = 1.6        # 阈值 = P_ZERO_K · Q0/(1−κ)


def vec_hash(v) -> str:
    """逐位取证 (零回退判据)。"""
    if v is None:
        return "none"
    a = np.asarray(v, dtype=np.float64)
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()[:16]


@dataclass
class GainOut:
    """一帧增益结算 (每一路都必须能回答: 谁给的 / 多信 / 为什么)。"""
    u: np.ndarray                 # 融合后的**参考** (未执行; 执行仍由 L2 收口)
    k_nav: float = 0.0            # L4 导航增益
    k_flow: float = 0.0           # L3 流程增益
    k_mm: float = 0.0             # L2 肌肉记忆修正增益
    p_prior: float = 0.0          # 先验不确定度 (本轮)
    q_event: float = 0.0          # 本轮事件项抬升量
    innov_nav: float = 0.0        # L4 新息 ‖y_nav − u⁻‖
    innov_flow: float = 0.0       # 流程新息 ‖y_flow − u⁻‖
    clip: float = 0.0             # 夹紧量 L∞ (收缩投影记账)
    events: dict = field(default_factory=dict)   # 触发了哪些事件 (可查)
    reason: str = ""


class GainScheduler:
    """卡尔曼式三层增益调度 (纯 numpy, 无状态全局量)。

    enabled=False 时 `step()` 直接返回原值 (逐位), 供 A/B 与零回退取证。
    """

    def __init__(self, enabled: bool = True, bounds: tuple[float, float] = (-1.0, 1.0),
                 kmin: float = KMIN, kmax_nav: float = KMAX_NAV, kmax_flow: float = KMAX_FLOW,
                 kappa: float = KAPPA, p0: float = P0, q0: float = Q0,
                 r_nav: float = R0_NAV, r_flow: float = R0_FLOW, k_mm0: float = K_MM0) -> None:
        self.enabled = bool(enabled)
        self.lo, self.hi = float(bounds[0]), float(bounds[1])
        self.kmin, self.kmax_nav, self.kmax_flow = kmin, kmax_nav, kmax_flow
        self.kappa, self.q0 = float(kappa), float(q0)
        self.r_nav, self.r_flow = float(r_nav), float(r_flow)
        self.k_mm0 = float(k_mm0)
        self.p = float(p0)                     # 当前先验不确定度 (标量: 三轴共享, 逐轴可扩)
        self.p_zero = P_ZERO_K * self.q0 / max(1e-9, 1.0 - self.kappa)   # 熟场景零增益闸
        self.n = 0
        self.stats: dict = {"steps": 0, "k_nav_sum": 0.0, "k_flow_sum": 0.0, "k_mm_sum": 0.0,
                            "events": {k: 0 for k in ("ood", "mm_miss", "innov", "stall",
                                                      "stage_switch")},
                            "p_hist": [], "k_nav_hist": [], "k_flow_hist": [],
                            "clipped": 0, "clip_max": 0.0}

    # ── 事件 → 过程噪声 (唯一的"自动调整"入口) ─────────────────────────────
    @staticmethod
    def event_q(ood_sigma: float = 0.0, mm_miss: float = 0.0, innov_z: float = 0.0,
                stall: float = 0.0, stage_switch: float = 0.0) -> tuple[float, dict]:
        """把可观测的结构信号折算成 Q 抬升量 (全部真实可测, 无凭感觉系数)。

        ood_sigma   : 归一化观测超出蒸馏域 (max|xn|/DOMAIN_SIGMA − 1, ≥0) → 泛化场景
        mm_miss     : 1 = 该 (场景,阶段) 无肌肉记忆标杆 (没练过) → 该信导航
        innov_z     : 归一化新息超门幅度 (|ν|/(INNOV_K·√R) − 1, ≥0) → 受扰/模型跟不上
        stall       : 李雅普诺夫势近期不降 (进度停滞/滑脱) ∈ [0,1]
        stage_switch: 刚切阶段 ∈ [0,1]
        """
        ev = {"ood": max(0.0, float(ood_sigma)), "mm_miss": float(mm_miss),
              "innov": max(0.0, float(innov_z)), "stall": max(0.0, float(stall)),
              "stage_switch": float(stage_switch)}
        q = (Q_OOD * ev["ood"] + Q_MM_MISS * ev["mm_miss"] + Q_INNOV * ev["innov"]
             + Q_STALL * ev["stall"] + 0.02 * ev["stage_switch"])
        return float(q), {k: v for k, v in ev.items() if v > 0.0}

    # ── 主结算 ─────────────────────────────────────────────────────────
    def step(self, u_l2, u_nav=None, u_flow=None, u_champ=None, r_nav: float | None = None,
             r_flow: float | None = None, ood_sigma: float = 0.0, mm_miss: float = 0.0,
             stall: float = 0.0, stage_switch: float = 0.0) -> GainOut:
        """一帧: 先验(L2) → 增益 → 融合 → 后验 → 肌肉记忆修正。

        u_l2     : L2 执行参考 (肌肉记忆/解析伺服; ★直接连物理世界的那一层)
        u_nav    : L4 导航参考 (意图解码器→对齐层之后的**动作量纲**; None = 该路缺席)
        u_flow   : L3 流程参考 (DiT 从 L4 意图生成的流程动作; None = 该路缺席)
        u_champ  : L2 肌肉记忆标杆该帧值 (None = 没固化/无标杆)
        返回 GainOut (u = 参考, 仍由 L2 收口执行)。
        """
        base = np.asarray(u_l2, dtype=float).reshape(-1).copy()
        if not self.enabled:
            return GainOut(u=base, reason="增益层关闭 → 逐位等于 L2 原值 (零回退)")

        self.n += 1
        q_ev_raw, ev_hit = self.event_q(ood_sigma, mm_miss, 0.0, stall, stage_switch)
        p_prior = self.kappa * self.p + self.q0 + q_ev_raw

        def _gain(y, r):
            if y is None:
                return 0.0, 0.0
            yy = np.asarray(y, dtype=float).reshape(-1)[: base.size]
            if yy.size < base.size:
                yy = np.pad(yy, (0, base.size - yy.size))
            nu = float(np.linalg.norm(yy[:3] - base[:3]))
            if p_prior <= self.p_zero:      # 熟场景闸: 无事件且不确定度落到地板 → 硬置 0
                return 0.0, nu
            k = p_prior / (p_prior + max(1e-9, float(r)))
            return k, nu

        k_nav, nu_nav = _gain(u_nav, self.r_nav if r_nav is None else r_nav)
        k_flow, nu_flow = _gain(u_flow, self.r_flow if r_flow is None else r_flow)

        # 新息异常 (受扰/模型跟不上) → 二次抬 Q 再算一遍 (结构闭环: 事件驱动增益)
        innov_z = 0.0
        if u_nav is not None and nu_nav > INNOV_K * float(np.sqrt(self.r_nav)):
            innov_z = nu_nav / (INNOV_K * float(np.sqrt(self.r_nav))) - 1.0
            q2, ev2 = self.event_q(ood_sigma, mm_miss, innov_z, stall, stage_switch)
            p_prior = self.kappa * self.p + self.q0 + q2
            ev_hit.update(ev2)
            k_nav, _ = _gain(u_nav, self.r_nav if r_nav is None else r_nav)
            k_flow, _ = _gain(u_flow, self.r_flow if r_flow is None else r_flow)

        k_nav = float(np.clip(k_nav, self.kmin, self.kmax_nav)) if u_nav is not None else 0.0
        k_flow = float(np.clip(k_flow, self.kmin, self.kmax_flow)) if u_flow is not None else 0.0

        u = base.copy()
        if u_nav is not None:
            u[:3] = u[:3] + k_nav * (np.asarray(u_nav, float).reshape(-1)[:3] - base[:3])
        if u_flow is not None:
            uf = np.asarray(u_flow, float).reshape(-1)[:3]
            u[:3] = u[:3] + k_flow * (uf - base[:3])

        # L2 肌肉记忆修正 (老倪: "流程动作又被 L2 层肌肉记忆修正, 最终物理执行")
        k_mm = 0.0
        if u_champ is not None:
            k_mm = float(np.clip(self.k_mm0 * (1.0 - k_nav), 0.0, 1.0))
            uc = np.asarray(u_champ, float).reshape(-1)[: base.size]
            u[:3] = u[:3] + k_mm * (uc[:3] - u[:3])

        a = np.asarray(u, float)
        u = np.clip(a, self.lo, self.hi)
        clip = float(np.max(np.abs(u - a))) if a.size else 0.0

        k_eff = float(np.clip(1.0 - (1.0 - k_nav) * (1.0 - k_flow), 0.0, 1.0))   # 联合更新比例
        self.p = float(max(1e-6, (1.0 - k_eff) * p_prior))

        s = self.stats
        s["steps"] += 1
        s["k_nav_sum"] += k_nav
        s["k_flow_sum"] += k_flow
        s["k_mm_sum"] += k_mm
        for k in ev_hit:
            s["events"][k] = s["events"].get(k, 0) + 1
        if clip > 0.0:
            s["clipped"] += 1
            s["clip_max"] = max(s["clip_max"], clip)
        s["p_hist"].append(self.p)
        s["k_nav_hist"].append(k_nav)
        s["k_flow_hist"].append(k_flow)

        why = ("默认 L2 (肌肉记忆/解析伺服主导)" if (k_nav <= 0 and k_flow <= 0)
               else "抬增益: 更信 " + "+".join(k for k, v in (("L4导航", k_nav > 0),
                                                             ("L3流程", k_flow > 0)) if v))
        return GainOut(u=u, k_nav=k_nav, k_flow=k_flow, k_mm=k_mm, p_prior=p_prior,
                       q_event=q_ev_raw, innov_nav=nu_nav, innov_flow=nu_flow, clip=clip,
                       events=ev_hit, reason=why)

    # ── 证据摘要 ───────────────────────────────────────────────────────
    def summary(self) -> dict:
        n = max(1, s := self.stats["steps"]) if (s := self.stats["steps"]) else 1
        h = lambda v: [round(float(x), 5) for x in v[-8:]]  # noqa: E731
        return {"steps": self.stats["steps"], "p_last": round(self.p, 6),
                "k_nav_mean": round(self.stats["k_nav_sum"] / n, 5),
                "k_flow_mean": round(self.stats["k_flow_sum"] / n, 5),
                "k_mm_mean": round(self.stats["k_mm_sum"] / n, 5),
                "events": self.stats["events"], "clipped": self.stats["clipped"],
                "clip_max": round(self.stats["clip_max"], 6),
                "k_nav_tail": h(self.stats["k_nav_hist"]),
                "k_flow_tail": h(self.stats["k_flow_hist"]),
                "p_tail": h(self.stats["p_hist"])}


# ────────────────────────── 自检 (结构性判据 + 零回退) ──────────────────────────
def self_test() -> int:
    print("🎚 adaptive_gain 自检 — 卡尔曼式三层增益 (L4导航/L3流程/L2执行)")
    ok = True

    # ① 零回退: 关闭 / 无上层参考 → 逐位等于 L2
    u_l2 = np.array([0.20, -0.10, 0.05, 1.0])
    g0 = GainScheduler(enabled=False)
    o0 = g0.step(u_l2, u_nav=np.array([0.9, -0.9, 0.8, 1.0]))
    same_off = vec_hash(o0.u) == vec_hash(u_l2)
    g1 = GainScheduler(enabled=True)
    o1 = g1.step(u_l2)
    same_none = vec_hash(o1.u) == vec_hash(u_l2)
    print(f"① 零回退: 关闭={same_off} · 无上层参考={same_none} "
          f"(hash {vec_hash(u_l2)}) → {'✓' if same_off and same_none else '✗'}")
    ok &= same_off and same_none

    # ② 结构: 熟场景 (无事件) → 增益单调衰减到 0; 受扰 (OOD) → 增益抬升
    g = GainScheduler()
    knav = []
    for _ in range(60):
        knav.append(g.step(u_l2, u_nav=np.array([0.45, -0.30, 0.20, 1.0])).k_nav)
    ks = np.asarray(knav)
    mono = bool(np.all(np.diff(ks[:40]) <= 1e-12))
    dec = mono and float(ks[-1]) == 0.0
    print(f"② 熟场景无事件: K_nav 首={ks[0]:.4f} → 末={ks[-1]:.6f} (单调不增={mono} · "
          f"落到 0={float(ks[-1]) == 0.0}) → {'✓ 自动回到 L2 (增益硬置 0)' if dec else '✗'}")
    ok &= dec

    before = ks[-1]
    o_ood = g.step(u_l2, u_nav=np.array([0.45, -0.30, 0.20, 1.0]),
                   ood_sigma=1.5, mm_miss=1.0, stall=1.0)
    rise = o_ood.k_nav > before + 1e-3
    print(f"② 受扰帧 (σ超门1.5 + 无标杆 + 停滞): K_nav {before:.6f} → {o_ood.k_nav:.4f} "
          f"事件={o_ood.events} → {'✓ 增益被抬升' if rise else '✗'}")
    ok &= rise

    # ③ 事件回落: 扰动消失后增益再次衰减 (不会长期脱离 L2)
    tail = [g.step(u_l2, u_nav=np.array([0.45, -0.30, 0.20, 1.0])).k_nav for _ in range(50)]
    back = tail[-1] < tail[0] * 0.5
    print(f"③ 扰动消失后: {tail[0]:.4f} → {tail[-1]:.6f} 回落={back} → "
          f"{'✓ 增益自动降回 L2 侧' if back else '✗'}")
    ok &= back

    # ④ 收缩性 (I2): 5000 组随机越界参考 → 必夹紧, 增益有上界, 无违规
    rng = np.random.default_rng(0)
    gg = GainScheduler()
    viol, clip_n, kmax = 0, 0, 0.0
    for _ in range(5000):
        b = rng.normal(0, 0.15, 4)
        nav = rng.normal(0, 1.5, 4)
        fl = rng.normal(0, 1.5, 4)
        o = gg.step(b, u_nav=nav, u_flow=fl, ood_sigma=float(rng.random()),
                    mm_miss=float(rng.random() < 0.3), stall=float(rng.random() < 0.2))
        if np.any(o.u < gg.lo - 1e-12) or np.any(o.u > gg.hi + 1e-12):
            viol += 1
        clip_n += int(o.clip > 0)
        kmax = max(kmax, o.k_nav, o.k_flow)
    print(f"④ 收缩性: 越界违规={viol}/5000 · 夹紧帧={clip_n} · 增益上界实测 max={kmax:.4f} "
          f"(帽 {max(gg.kmax_nav, gg.kmax_flow)}) → {'✓' if viol == 0 and kmax <= 0.5 + 1e-9 else '✗'}")
    ok &= (viol == 0 and kmax <= 0.5 + 1e-9)

    # ⑤ 三层语义: 肌肉记忆修正方向 = 标杆 (K_nav 小时强, K_nav 大时让位给导航)
    gA, gB = GainScheduler(), GainScheduler()
    base = np.array([0.30, 0.0, 0.0, 1.0])
    champ = np.array([0.10, 0.0, 0.0, 1.0])      # L2 肌肉记忆标杆 (练熟的动作)
    nav = np.array([0.60, 0.0, 0.0, 1.0])        # L4 导航意图 (对齐后动作量纲)
    a = [gA.step(base, u_champ=champ).u[0] for _ in range(40)][-1]
    b2 = float(base[0])
    for _ in range(40):
        b2 = float(gB.step(base, u_nav=nav, u_champ=champ,
                           ood_sigma=2.0, mm_miss=1.0).u[0])
    ok5 = (a < base[0] - 1e-6) and (b2 > a + 1e-6) and (b2 > base[0] + 1e-6)
    print(f"⑤ 肌肉记忆修正: 熟场景 u0 {base[0]:.3f}→{a:.5f} (被标杆 {champ[0]:.2f} 拉回) · "
          f"受扰+有导航 u0→{b2:.5f} (肌肉记忆让位, 向导航 {nav[0]:.2f} 走) → "
          f"{'✓ 三层分工成立' if ok5 else '✗'}")
    ok &= ok5

    print(f"── 自检结论: {'全部通过' if ok else '有判据未过'} ──")
    print("摘要示例:", {k: v for k, v in GainScheduler().summary().items()})
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(self_test())
