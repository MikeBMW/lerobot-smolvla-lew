# -*- coding: utf-8 -*-
"""⚖️ Step 1 三臂 A/B — INTACT 动作进前馈加速器 (u_ff 槽位) 是否回退

三臂 (同一引擎、同 seed、同重复数; 只换 u_ff 来源):
  A analytic : 现状默认 (SS_INTACT 不设) — 蒸馏 MLP 主路径 + 插入段解析伺服
  B shadow   : SS_INTACT=1 SS_INTACT_SHADOW=1 — INTACT **真推理真记录**, 但不接管 (零回退风险)
  C intact   : SS_INTACT=1 — INTACT 经标定映射 (models/intact_action_map.json) **接管** u_ff xyz
               (gripper 仍由状态机决定 — 与 SS_L3 同一纪律)

红线 (老倪): C 臂成功率不得低于 A 臂。若 C < A → 结论就是"不回退不成立", 只保留开关+影子,
默认仍是 A (不硬改默认档)。

记录: done/steps + INTACT 调用次数/拒绝映射次数 + |Δu| 分布 (shadow 臂) + 数据源=engine_render。
用法: MUJOCO_GL=egl gui-venv311/bin/python tools/ab_intact_uff.py --seeds 0,1,2 --reps 2
"""
import argparse
import json
import os
import statistics as st
import sys
import time

import numpy as np

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
os.environ.setdefault("MUJOCO_GL", os.environ.get("MUJOCO_GL", "egl"))
_CACHE = os.environ.get("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache")
if os.path.isdir(_CACHE):
    os.environ.setdefault("STABLEWM_HOME", _CACHE)
    os.environ.setdefault("LOCAL_DATASET_DIR", _CACHE)
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

ARMS = {
    "A_analytic": {},
    "B_shadow": {"SS_INTACT": "1", "SS_INTACT_SHADOW": "1"},
    "C_intact": {"SS_INTACT": "1"},
}


def _goal_frame(seed, max_steps):
    """goal 帧 = 该 seed 基线轮的**末帧** (任务完成态; 与 Step0 探针同口径)。

    为什么必须这么做: INTACT 的 goal_displacement 意图**需要目标帧**; 引擎里原来没给它 goal
    → 第一版 A/B 实测报错 "goal_displacement 模式需要 goal 帧" (影子臂 0 次真推理)。
    """
    from state_space_sim_real import RealStateSpaceSim            # noqa: PLC0415
    frames = []
    sim = RealStateSpaceSim(seed=seed, vision=False, mode="insert", log=lambda *a: None)
    sim._frame_sink = lambda s, a, o: frames.append(np.asarray(s.env.render()))
    sim.run(max_steps=max_steps)
    try:
        sim.env.close()
    except Exception:
        pass
    return frames[-1] if frames else None


def one(arm, seed, rep, max_steps, device, goal=None):
    for k in ("SS_INTACT", "SS_INTACT_SHADOW"):
        os.environ.pop(k, None)
    os.environ.update(ARMS[arm])
    import cv2                                                    # noqa: PLC0415
    from state_space_sim_real import RealStateSpaceSim            # noqa: PLC0415
    from lerobot.manifold.intact_node import (IntactActionAdapter,  # noqa: PLC0415
                                              IntactNode, IntactRuntime)
    sim = RealStateSpaceSim(seed=seed, vision=False, mode="insert", log=lambda *a: None)
    if arm in ("B_shadow", "C_intact"):
        rt = IntactRuntime(device=device)
        node = IntactNode(horizon=int(os.environ.get("SS_INTACT_HORIZON", "8")), runtime=rt)
        if goal is not None:
            node.set_goal(cv2.resize(np.asarray(goal), (224, 224), interpolation=cv2.INTER_AREA)
                          .transpose(2, 0, 1).astype(np.float32))
        ad = IntactActionAdapter()
        sim.attach_intact(node, ad)          # 引擎侧挂载 (SS_INTACT=1 时每 N 步真推理)
    tr = sim.run(max_steps=max_steps)
    done = bool(tr["done"][-1]) if tr.get("done") else False
    stats = dict(getattr(sim, "_intact_stats", {}) or {})
    row = {"arm": arm, "seed": seed, "rep": rep, "done": done, "steps": len(tr["t"]),
           "intact_calls": stats.get("intact_calls", 0),
           "refused_map": stats.get("refused_map", 0),
           "shadow_uncalibrated": stats.get("shadow_uncalibrated", 0),
           "chunk_norm_mean": (round(float(np.mean(stats["chunk_norm"])), 4)
                               if stats.get("chunk_norm") else None),
           "err": stats.get("err"),
           "shift_mean": (round(float(np.mean(stats["shift"])), 5) if stats.get("shift") else None),
           "u_ff_src": stats.get("u_ff_src"),
           "insert_mm": (round(float(tr["dist"][-1]) * 1000, 1) if tr.get("dist") else None)}
    try:
        sim.env.close()
    except Exception:
        pass
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="0,1,2")
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--max-steps", type=int, default=600)
    ap.add_argument("--device", default=os.environ.get("INTACT_DEVICE", "cpu"))
    ap.add_argument("--arms", default="A_analytic,B_shadow,C_intact")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    seeds = [int(s) for s in a.seeds.split(",") if s.strip()]
    arms = [x for x in a.arms.split(",") if x]
    rows, t0 = [], time.time()
    goals = {}
    for seed in seeds:                      # 每个 seed 先跑一遍基线取 goal 帧 (末帧=完成态)
        goals[seed] = _goal_frame(seed, a.max_steps)
        print(f"  [goal] seed={seed}: {'已取末帧' if goals[seed] is not None else '⚠️ 无帧'}",
              flush=True)
    for arm in arms:
        for seed in seeds:
            for rep in range(a.reps):
                r = one(arm, seed, rep, a.max_steps, a.device, goal=goals.get(seed))
                rows.append(r)
                print(f"  [{arm:10s}] seed={seed} rep={rep} done={r['done']} steps={r['steps']} "
                      f"INTACT调用={r['intact_calls']} 拒绝映射={r['refused_map']} "
                      f"|Δu|={r['shift_mean']} err={r['err']}", flush=True)
    print("\n═══ 汇总 (同 seed/重复数同口径) ═══")
    summ = {}
    for arm in arms:
        rs = [r for r in rows if r["arm"] == arm]
        succ = sum(1 for r in rs if r["done"])
        stp = [r["steps"] for r in rs]
        calls = [r["intact_calls"] for r in rs]
        summ[arm] = {"success": succ, "n": len(rs),
                     "steps_mean": round(st.mean(stp), 1) if stp else None,
                     "intact_calls_mean": round(st.mean(calls), 1) if calls else 0,
                     "refused_map_total": sum(r["refused_map"] for r in rs),
                     "shadow_uncalibrated_total": sum(r.get("shadow_uncalibrated") or 0 for r in rs),
                     "chunk_norm_mean": (round(st.mean([r["chunk_norm_mean"] for r in rs
                                                        if r.get("chunk_norm_mean")]), 4)
                                         if any(r.get("chunk_norm_mean") for r in rs) else None)}
        print(f"  {arm:10s}: success {succ}/{len(rs)} · 步数均值 {summ[arm]['steps_mean']} · "
              f"INTACT 真推理均值 {summ[arm]['intact_calls_mean']} · "
              f"拒绝映射 {summ[arm]['refused_map_total']} · "
              f"影子未标定 {summ[arm]['shadow_uncalibrated_total']} · "
              f"|chunk|={summ[arm]['chunk_norm_mean']}")
    A = summ.get("A_analytic", {}).get("success", 0)
    C = summ.get("C_intact", {})
    _calls = (C or {}).get("intact_calls_mean", 0) or 0
    if not C:
        verdict = "C 臂未跑"
    elif _calls <= 0:
        verdict = (f"⚠️ C 臂**未真正接管** (INTACT 调用 0 次 · 拒绝映射 "
                   f"{C.get('refused_map_total')} 次) → 本轮只证明「管线通 + 守卫生效」, "
                   f"**不构成「接管不回退」的证据** (接管前提=标定通过)")
    elif C["success"] >= A:
        verdict = f"✅ C 臂真接管 (调用 {_calls:.0f} 次/轮) 且成功率 {C['success']} ≥ A {A} → 红线通过"
    else:
        verdict = f"❌ C 臂 {C['success']} < A 臂 {A} → **回退成立, 默认保持 A**, 只保留开关+影子"
    print(f"   红线裁决: {verdict}")
    out = a.out or os.path.join(ROOT, "reports", f"ab_intact_uff_{time.strftime('%Y%m%d_%H%M%S')}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"meta": {"seeds": seeds, "reps": a.reps, "max_steps": a.max_steps,
                            "device": a.device, "elapsed_s": round(time.time() - t0, 1),
                            "arms": ARMS, "verdict": verdict,
                            "note": "INTACT 走 engine_render 真渲染帧; 零搜索 candidate_sequences=0; "
                                    "gripper 仍由状态机 (同 SS_L3 纪律)"},
                   "summary": summ, "rows": rows}, f, ensure_ascii=False, indent=2)
    print(f"   → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
