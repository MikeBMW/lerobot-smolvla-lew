#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_cog_event_loop.py — 🧠 事件头进引擎闭环 取证 (真跑引擎, 逐帧真调用, 闭环 AUC)

判据:
  ① 引擎真跑通 (tr 帧数 > 0) 且 7 个 cog_ev_* 键长度 == 帧数
  ② **逐帧真调用**: sim._cog_ev_calls == 帧数 (证明是"每帧真调真权重", 不是占位/抽样)
  ③ 值域: 全部概率 ∈ [0,1] 且非 -1 (证明真推理出结果)
  ④ 单帧耗时中位 < 20ms/帧 (不拖慢引擎闭环)
  ⑤ 闭环信号: 用 tr 自己算真事件标签 → 算 AUC (夹爪闭合 / 手在动 / 到位), 与离线口径同定义
  ⑥ 诚实开关: SS_COG_EVENT=0 → 引擎写 -1 (拿不到不冒充)
用法: gui-venv311/bin/python tools/verify_cog_event_loop.py [--steps 120] [--seed 0]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

ROOT = "/home/ubuntu/zmax_rel"
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
sys.path.insert(0, os.path.join(ROOT, "src"))

KEYS = ("gc_5", "gc_10", "rz_5", "rz_10", "mh_5", "mh_10")


def tkey(k):
    """事件名 → 引擎 tr 键 (引擎口径: cog_ev_gc5, 无下划线)"""
    return "cog_ev_" + k.replace("_", "", 1).replace("_", "") if False else "cog_ev_" + k.split("_")[0] + k.split("_")[1]
ok = []


def chk(n, c, d=""):
    ok.append(bool(c))
    print("  %s %s%s" % ("✅" if c else "❌", n, (" — " + d) if d else ""), flush=True)


def auc(p, y):
    p, y = np.asarray(p, float), np.asarray(y, float)
    if y.sum() == 0 or y.sum() == len(y):
        return float("nan")
    order = np.argsort(p)
    ranks = np.empty(len(p), float)
    ranks[order] = np.arange(1, len(p) + 1)
    npos = float(y.sum())
    return float((ranks[y == 1].sum() - npos * (npos + 1) / 2) / (npos * (len(y) - npos)))


def event_labels(obs, kind, H):
    """与训练完全同定义 (只用 obs[0:7])"""
    hand = obs[:, 0:3]
    L = len(obs)
    if kind == "gc":
        ev = np.zeros(L, bool)
        ev[1:] = (obs[1:, 3] < 0.5) & (obs[:-1, 3] >= 0.5)
    elif kind == "mh":
        dh = np.linalg.norm(np.diff(hand, axis=0), axis=1)
        ev = np.zeros(L, bool)
        ev[1:] = dh > 0.001
    else:                                        # rz
        z_end = float(obs[-1, 2])
        ev = np.abs(obs[:, 2] - z_end) < 0.002
    lab = np.zeros(L, bool)
    for t in range(L - H):
        lab[t] = bool(ev[t + 1:t + 1 + H].any())
    return lab[:L - H]


def run_engine(steps, seed):
    from state_space_sim_real import RealStateSpaceSim                 # noqa: PLC0415
    sim = RealStateSpaceSim(seed=seed, vision=False, mode="insert", log=lambda *a: None)
    t0 = time.time()
    tr = sim.run(max_steps=steps)
    return sim, tr, time.time() - t0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=120)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    print("═" * 74)
    print("🧠 事件级认知头 · 引擎闭环取证 (seed=%d, steps=%d)" % (a.seed, a.steps))
    print("═" * 74)

    sim, tr, el = run_engine(a.steps, a.seed)
    n = len(tr["t"])
    print("  引擎真跑: %d 帧 / %.1fs (%.0f 帧/s)" % (n, el, n / max(el, 1e-6)))
    chk("① 引擎真跑通 (帧数 > 0)", n > 0, "%d 帧" % n)
    lens = {k: len(tr.get(tkey(k), [])) for k in KEYS}
    chk("① 7 个事件键长度 == 帧数", all(v == n for v in lens.values()) and len(tr.get("cog_ev_ms", [])) == n,
        "lens=%s ms=%d" % (lens, len(tr.get("cog_ev_ms", []))))
    calls = int(getattr(sim, "_cog_ev_calls", 0))
    chk("② 逐帧真调用 (calls == 帧数)", calls == n, "calls=%d / frames=%d" % (calls, n))
    allv = np.array([tr[tkey(k)] for k in KEYS], float)
    chk("③ 概率值域 ∈ [0,1] 且非 -1", bool((allv >= 0).all() and (allv <= 1).all()),
        "min=%.3f max=%.3f" % (allv.min(), allv.max()))
    ms = np.array(tr["cog_ev_ms"], float)
    chk("④ 单帧耗时中位 < 20ms", float(np.median(ms)) < 20.0, "中位 %.3f ms · 最大 %.1f ms" % (np.median(ms), ms.max()))

    print("⑤ 闭环信号 (真标签由 tr 自己算, 与训练同定义):")
    obs = np.array(tr["obs"], float)
    res = {}
    for kind, key in (("gc", "gc"), ("mh", "mh"), ("rz", "rz")):
        for H in (5, 10):
            lab = event_labels(obs, kind, H)
            pred = np.array(tr[tkey("%s_%d" % (key, H))], float)[:len(lab)]
            au = auc(pred, lab)
            res["%s_H%d" % (kind, H)] = {"auc_loop": round(au, 4) if au == au else None,
                                         "pos_rate": round(float(lab.mean()), 4)}
            print("     %s_H%-3d 闭环AUC=%.4f (正例率 %.3f)" % (kind, H, au, lab.mean()))
    big = [k for k, v in res.items() if v["auc_loop"] and v["auc_loop"] > 0.7]
    chk("⑤ 闭环内事件头有信号 (≥1 项 AUC>0.7)", bool(big), "强项=%s" % (big or "无"))

    print("⑥ 诚实开关 SS_COG_EVENT=0:")
    os.environ["SS_COG_EVENT"] = "0"
    sim2, tr2, _ = run_engine(min(20, a.steps), a.seed)
    os.environ.pop("SS_COG_EVENT", None)
    zero = set(tr2[tkey("gc_5")])
    chk("⑥ 关掉开关 → 写 -1 (不冒充 0)", zero == {-1.0}, "gc5 取值集合=%s" % sorted(zero)[:3])

    head = getattr(sim, "_cog_ev", None)
    out = {"ts": time.strftime("%F %T"), "seed": a.seed, "frames": n, "engine_s": round(el, 1),
           "calls": calls, "head": (head.info() if head is not None else None),
           "loop_auc": res, "judges_pass": "%d/%d" % (sum(ok), len(ok))}
    dst = os.path.join(ROOT, "reports", "cog_event_loop_verify_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    json.dump(out, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if head is not None:
        print("  认知头: %s | calls=%d" % (head.info()["source"], head.info()["calls"]))
    print("\n判据通过: %d/%d · 取证: %s" % (sum(ok), len(ok), dst))
    return 0 if all(ok) else 3


if __name__ == "__main__":
    raise SystemExit(main())
