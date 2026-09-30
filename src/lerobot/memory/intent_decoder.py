#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""意图直读 decoder (v0, 零训练) — S3' 第一步

架构位置 (不动 L2 三大件):
    L4 世界模型/意图 ──▶ [本模块: 意图 → 动作基查表] ──▶ ⚡前馈加速器 u_ff
    ⚡前馈加速器 / 🔮自适应状态估计器 / 📈先验动力学预测器 全部原样保留。

意图定义 (INTACT): 目标状态 − 当前状态。
    段的可比表征 = (阶段 stage, 段入口状态 entry_3d)
    —— io 契约 (S2, memory_graph.skill_io) 已断言 entry → u 的映射, 本模块即其查表实现。

库来源: data/muscle_memory.json 的 42 条标杆 (6 seed × 7 阶段)
    每条: champ_u(n×4 动作序列) / champ_x(n×3) / io{entry, exit, entry_u, exit_u, frames}

与"按 seed 查"(muscle.get_champ(seed, stage))的区别:
    旧: 记忆 = 场景 id → 动作 (换个 seed 就失效, 无法共享)
    新: 记忆 = 意图(阶段+入口状态) → 动作 (跨场景共享 = 意图泛化)
"""
import json
import os

import numpy as np

STAGES = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入"]
# 与引擎快通道口径一致: 只有这 5 段用固化动作基; 转移/插入走实时毫米级决策
FAST_STAGES = ["接近", "对位", "下降", "抓取", "抬起"]


def _norm_stage(stage):
    return str(stage).replace("阶段 ", "").split("·")[0].strip()


class IntentDecoder:
    """意图 → 动作基 查表 (零训练)。接口与 muscle.get_champ 同形, 可直接替换前馈槽位来源。"""

    def __init__(self, path="data/muscle_memory.json", w_pos=1.0, w_dir=0.0):
        self.path = path
        self.w_pos = float(w_pos)      # 入口状态距离权重
        self.w_dir = float(w_dir)      # 意图方向一致性权重 (0=关闭, >0 需传 goal_pos)
        self.lib = []
        self.load(path)

    # ── 载入库 ──────────────────────────────────────────────
    def load(self, path=None):
        p = path or self.path
        self.lib = []
        if not os.path.exists(p):
            return self
        db = json.load(open(p))
        for k, e in db.items():
            if not isinstance(e, dict) or e.get("champ_u") is None:
                continue
            seed_s, _, stage = k.partition("|")
            try:
                seed = int(seed_s)
            except ValueError:
                continue
            io = e.get("io") or {}
            entry = np.asarray(io.get("entry", [np.nan] * 3), float)
            exit_ = np.asarray(io.get("exit", [np.nan] * 3), float)
            if not np.isfinite(entry).all():          # 兜底: 用 champ_x 首/末帧
                cx = np.asarray(e.get("champ_x"), float)
                if cx.size >= 3:
                    entry, exit_ = cx[0][:3], cx[-1][:3]
            u = np.asarray(e["champ_u"], float)
            self.lib.append(dict(
                stage=_norm_stage(stage), seed=seed,
                entry=entry, exit=exit_, dv=exit_ - entry,
                u=u, x=np.asarray(e.get("champ_x"), float), n_ok=int(e.get("n_ok", 0)),
            ))
        return self

    # ── 查询: (阶段, 当前状态) → 动作基 ─────────────────────
    def query(self, stage, cur_pos, goal_pos=None, k=1):
        """返回 (champ_u | None, meta)。meta 含命中来源, 供审计/上报。"""
        st = _norm_stage(stage)
        cands = [e for e in self.lib
                 if e["stage"] == st and np.isfinite(e["entry"]).all()]
        if not cands:
            return None, {"hit": False, "reason": "no_stage_in_lib", "stage": st}
        cur = np.asarray(cur_pos, float).ravel()[:3]
        gp = None if goal_pos is None else np.asarray(goal_pos, float).ravel()[:3]
        scored = []
        for e in cands:
            d = self.w_pos * float(np.linalg.norm(cur - e["entry"]))
            if self.w_dir > 0 and gp is not None:
                v1, v2 = gp - cur, e["dv"]
                n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
                if n1 > 1e-6 and n2 > 1e-6:
                    d += self.w_dir * float(1.0 - float(np.dot(v1, v2) / (n1 * n2)))
            scored.append((d, e))
        scored.sort(key=lambda t: t[0])
        d, e = scored[0]
        return e["u"], {"hit": True, "dist": round(d, 4), "stage": st,
                        "src_seed": e["seed"], "src_n_ok": e["n_ok"],
                        "src_entry": e["entry"].round(4).tolist(),
                        "frames": int(len(e["u"]))}

    # ── 统计 ────────────────────────────────────────────────
    def summary(self):
        from collections import Counter
        return {"n": len(self.lib),
                "per_stage": dict(Counter(e["stage"] for e in self.lib)),
                "seeds": sorted({e["seed"] for e in self.lib})}

    def leave_one_seed_out(self, stage, seed):
        """留一验证: 排除该 seed 后查询 (用于证明跨场景共享, 而非记住了那个场景)。"""
        st = _norm_stage(stage)
        return [e for e in self.lib if e["stage"] == st and e["seed"] != int(seed)]


if __name__ == "__main__":  # 自检
    dec = IntentDecoder(path=os.path.join(os.path.dirname(__file__), "..", "..", "..",
                                          "data", "muscle_memory.json"))
    print("库:", dec.summary())
    for st in ("接近", "下降"):
        u, meta = dec.query(st, [0.004, 0.60, 0.19])
        print(f"[{st}] cur=[0.004,0.60,0.19] → {meta} | u[0]={None if u is None else u[0].round(3)}")
