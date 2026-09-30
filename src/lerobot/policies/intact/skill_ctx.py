# -*- coding: utf-8 -*-
"""🧠 L2 原子技能上下文 (skill_ctx) —— **单一事实来源**

老倪 09-14 下令: "带着记忆层，适配训练 L4 的INTACT, 要能让L4看到 L2的原子技能，复用能力"
→ 训练数据 (tools/intact_insert_dataset_v5.py) 和闭环推理 (tools/intact_sw_optical_bridge.py)
**必须逐位同口径**构造这个向量, 否则模型学到的是另一种分布 (口径不一致 = 白训)。

向量 (24 维, 顺序写死, 改顺序 = 换版本):
  [0:13]  引擎相位 one-hot —— cognition.ActionModulator.STAGES (mode=full 全 13 段)
          前 8 段 = 接近/对位/下降/抓取/抬起/转移/插入/拔出 = L2 的 SK01..SK08 对应相位
  [13:21] L2 流程势场**按状态软判**的技能权重 w (Σ≤1; 全远离轨迹管时给 0 = 诚实"不在任何管附近")
  [21]    到最近 L2 冠军轨迹管的横向距离 d_perp (m)  ← "复用贴合度"
  [22]    沿该管弧长进度 arc_frac ∈ [0,1]
  [23]    夹爪指令 grip (引擎控制向量 u[3], 开=-1 / 停=0 / 闭=+1)

坐标口径红线 (v5.5.48 实锤): x **必须是夹爪真实位置 obs[0:3]** (引擎 self.x = o[0:3]),
不是 peg_head() —— 用错坐标系时 d_perp 恒 ~0.13m, 势场在自己坐标系外求梯度 = 意图是噪声。
"""
from __future__ import annotations

import numpy as np

# 引擎 cognition.ActionModulator.STAGES (mode=full); mode=insert 只用前 8 段
STAGE_ORDER = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入",
               "拔出", "AOI转移", "AOI检测", "回程", "放下", "完成"]
N_STAGE = len(STAGE_ORDER)
N_SKILL = 8
SKILL_CTX_DIM = N_STAGE + N_SKILL + 3          # 13 + 8 + (d_perp, arc_frac, grip) = 24


def stage_onehot(stage: str) -> np.ndarray:
    oh = np.zeros(N_STAGE, np.float32)
    s = str(stage or "").strip()
    oh[STAGE_ORDER.index(s) if s in STAGE_ORDER else N_STAGE - 1] = 1.0
    return oh


def build_skill_ctx(process, x_hand, stage: str, grip: float = 0.0) -> np.ndarray:
    """process = ProcessPotentialField (L2 原子技能序列势场) 或 None (无记忆层 → 只给相位/夹爪).

    x_hand: 夹爪真实位置 (引擎 obs[0:3]); stage: 引擎当前相位名; grip: 控制向量 u[3]
    """
    out = np.zeros(SKILL_CTX_DIM, np.float32)
    out[:N_STAGE] = stage_onehot(stage)
    out[-1] = float(grip)
    if process is None:
        return out
    try:
        from lerobot.memory.potential_field import polyline_length, project_polyline
    except ImportError:                                            # 记忆层不可用 → 相位/夹爪仍有效
        return out
    x = np.asarray(x_hand, float).ravel()[:3]
    w, d = process.weights_from_state(x)
    if w is not None:
        out[N_STAGE:N_STAGE + min(N_SKILL, len(w))] = np.asarray(w, np.float32)[:N_SKILL]
    if d is not None and len(d):
        k = int(np.argmin(d))
        P = process.fields[k].P
        # 🐛 2026-09-14 实锤: project_polyline 返回 **(最近点, 距离, 弧长, 段号) 4 元组** ——
        #   原来按 3 元组解包 → 每帧 ValueError → 被上游 sink 静默吞掉 → part 里**没有 skill_ctx**
        #   (老倪红线: 静默降级 = 白做)。现在 4 元组解包, 且只容忍 ImportError, 其余错误一律外抛。
        _, d_perp, s_arc, _ = project_polyline(x, P)
        out[N_STAGE + N_SKILL] = float(d_perp)
        L = float(polyline_length(P))
        out[N_STAGE + N_SKILL + 1] = float(s_arc / L) if L > 1e-9 else 0.0
    return out


def describe() -> dict:
    return {"dim": SKILL_CTX_DIM, "stages": N_STAGE, "skills": N_SKILL,
            "layout": "[stage13 | L2_w8 | d_perp | arc_frac | grip]",
            "coord": "x = 夹爪真实位置 obs[0:3] (v5.5.48 实锤)"}
