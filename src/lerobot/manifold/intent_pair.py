#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""INTACT 二态意图 × 接触/性能流形 —— L4 意图层 (Manifold Intent Pair)

设计原则(老倪 2026-09-11 拍板):
  **保留现有流形预测模式**(接触流形 + 性能流形), 在其之上加"意图层", 不替换流形。
  流形提供"物理接地"(状态在哪个曲面上、约束是什么), 意图层提供"规划能力"(往哪走)。

INTACT 原文的两个调用:
  m_local = z_{t+1} − z_t         局部意图 (物理上可恢复的状态变化 → 肌肉记忆)
  m_goal  = sg(z_g) − z_t         目标意图 (动作前的目标意图 → 规划)

在本仓库流形上的**精确对应**(不是类比, 是同一物理量):
  m_local ≡ −e_par     接触流形 decompose() 的切向分量(沿通道/测地线的推进方向)
                        → "下一步沿流形往哪走", 严格遵守接触约束 (物理铁律)
  m_goal  ≡ −∇V_p     性能流形 evaluate() 的负梯度(最优对准方向, 指向 η=1 完成态)
                        → "往目标怎么走", 只看方向不看过程 (靶子)

同构但非对称 (INTACT 精髓, 原文: shared feature grammar/parameters, 但不共享数值分布/编码器梯度):
  · 共享:  两者都是 Δz ∈ R³ 的"意图向量" → 同一语法, 同一算子可消费 (sha_ 前缀接口)
  · 不共享数值分布: m_goal 的幅值是"几十毫米的量级差", m_local 是"毫米级窗口步长"
  · 不对称梯度: m_local 用于塑造编码器(逐帧物理真值); m_goal 走 stop-gradient(目标端不反传)

对接方式:
  引擎 L4 档 → intent_pair 产 (m_local, m_goal) → 共享算子 shared_encode() → L3/L2 前馈槽位
"""
import numpy as np

_TAG = "[intent_pair]"


# ── 共享算子 (INTACT 的 G_eta 的最简形式: 结构共享, 参数共享) ──────────────
class SharedIntentEncoder:
    """共享意图编码器 —— 对应 INTACT 的 shared predictor backbone。

    同一个算子处理两种意图: 输入 (z_t, m) → 动作块方向 (4D)。
    **结构共享是本质**: 不允许为 m_local / m_goal 各建一套网络(那就是"表征割裂")。
    这里给的是显式版(线性投影 + 非线性), 训练版替换 self.W 即可, 接口不变。
    """

    def __init__(self, z_dim=6, act_dim=4, gain=1.0, stop_grad_on_goal=True):
        self.z_dim, self.act_dim = int(z_dim), int(act_dim)
        self.gain = float(gain)
        self.stop_grad_on_goal = bool(stop_grad_on_goal)
        # 显式投影: 意图向量(3) → 动作前 3 维; 第 4 维(夹爪)由状态机管, 这里不动
        self.W = np.eye(3, act_dim - 1)          # 占位; 训练时会被替换

    # ---- 语法入口: **两态走同一个函数** (这是"共享"的工程含义) ----
    def __call__(self, z_t, m, kind="local"):
        """z_t: 状态(流形坐标或潜表示), m: 意图向量 R³, kind: local|goal

        ⚠️ 非对称梯度的正确含义 (INTACT): **前向两态都正常产生动作**;
           差别在**反向** —— m_goal 路径 stop-gradient, 不塑造"感知物理的编码器"。
           (早先误写成"把 m_goal 置零"是错的: 那样目标意图就不产生动作了。)
        """
        m = np.asarray(m, float).ravel()[:3]
        u = np.zeros(self.act_dim, float)
        u[:3] = self.gain * (self.W.T @ m)          # 前向: 两态同语法、同算子
        # 🚫 反向标记: 训练时据此对 goal 路径做 detach (编码器不被"远处的靶子"改写)
        self.last_stop_grad = bool(kind == "goal" and self.stop_grad_on_goal)
        self.last_kind = kind
        return u


# ── 二态意图对 (流形实现) ────────────────────────────────────────────────
class ManifoldIntentPair:
    """把接触/性能流形的几何量, 显式化为 INTACT 的二态意图。

    用法:
        pair = ManifoldIntentPair(contact_manifold, perf_manifold)
        m_loc, info_loc = pair.local(hand, peg_head, target, v, stage)   # 肌肉记忆方向
        m_gol, info_gol = pair.goal(peg_head, stage)                     # 目标意图方向
        同构核验: pair.isomorph(m_loc, m_gol)
    """

    def __init__(self, contact=None, perf=None, eps=1e-9):
        self.contact = contact
        self.perf = perf
        self.eps = float(eps)
        self.stats = {"local_calls": 0, "goal_calls": 0, "degenerate": 0}

    # ---- ① 局部意图 = 接触流形切向 (z_{t+1} − z_t 的物理形式) ----
    def local(self, hand, peg_head, target, v=None, stage=None):
        """返回 (m_local, info): m_local = **指向阶段目标的单位方向**(共享语法)。

        ⚠️ 接触流形的误差符号约定**因段而异**(读源码实锤, 不是 bug 是原设计):
          · 插入/完成段: e = peg_head − hole_pos  (当前位置−目标) → 推进方向 = −e
          · 自由空间段:  e = target   − hand       (目标−当前位置) → 推进方向 = +e
        两态要"同构"(共享语法), 就必须在这里统一成同一语义: **指向目标的单位向量**。
        """
        if self.contact is None:
            return None, {"m_type": "local", "err": "no_contact_manifold"}
        v = np.zeros(3) if v is None else v
        r = self.contact.decompose(hand, peg_head, target, v, stage)
        e_par = np.asarray(r.get("e_par", np.zeros(3)), float).ravel()
        _st = str(stage or "")
        _e_is_pos_minus_goal = _st in ("插入", "完成")     # 该段 e = 位置−目标
        d = (-e_par) if _e_is_pos_minus_goal else e_par     # → 统一为"指向目标"
        n = float(np.linalg.norm(d))
        self.stats["local_calls"] += 1
        if n < self.eps:
            self.stats["degenerate"] += 1
            return np.zeros(3), dict(r, m_type="local", mag=0.0, note="已在流形上(e_par≈0)")
        # 方向 = 沿切向推进 (指向目标); 幅值单列, 交给下游按时长/速度标定
        return d / n, dict(r, m_type="local", mag=n, sign_convention="pos−goal" if _e_is_pos_minus_goal else "goal−pos",
                           dir_hat=(d / n).round(4).tolist())

    # ---- ② 目标意图 = 性能流形负梯度 (sg(z_g) − z_t 的物理形式) ----
    def goal(self, peg_head, stage=None):
        if self.perf is None:
            return None, {"m_type": "goal", "err": "no_perf_manifold"}
        r = self.perf.evaluate(peg_head, stage)
        g = -np.asarray(r.get("grad", np.zeros(3)), float).ravel()   # 最优对准方向
        n = float(np.linalg.norm(g))
        self.stats["goal_calls"] += 1
        if n < self.eps:
            self.stats["degenerate"] += 1
            return np.zeros(3), dict(r, m_type="goal", mag=0.0, note="已在完成态(∇V_p≈0)")
        return g / n, dict(r, m_type="goal", mag=n, eta=float(r.get("eta", 0.0)),
                           dir_hat=(g / n).round(4).tolist())

    # ---- ③ 同构核验 (INTACT: 共享语法, 不共享数值分布) ----
    def isomorph(self, m_local, m_goal):
        """核验两态是否"同构但不同分布": 结构一致(维度/语法), 数值分布可差很远。"""
        a = np.asarray(m_local, float).ravel() if m_local is not None else np.zeros(3)
        b = np.asarray(m_goal, float).ravel() if m_goal is not None else np.zeros(3)
        na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
        cos = float(np.dot(a, b) / (na * nb)) if na > self.eps and nb > self.eps else 0.0
        return {
            "same_dim": a.shape == b.shape,                     # 共享语法 ✓
            "same_kind": "both are Δz∈R3 intent vectors",       # 同构
            "cos_sim": round(cos, 4),                           # 两态方向是否一致(局部 vs 全局)
            "norm_local": round(na, 6), "norm_goal": round(nb, 6),
            "parallel": abs(cos) > 0.9,                          # 局部与全局同向 → 无需换策略
            "note": "同构: 结构/语法一致; 非对称: 数值分布与梯度处理不同",
        }
