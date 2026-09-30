#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🚀 run_all_models.py — 把**所有在役模型**按档位真跑一遍并逐层取证 (老倪: 「运行所有模型」)

跑什么 (与 GUI 勾选框等价, 用 GUI 同一代码路径 RealStateSpaceSim):
  · L2 档  : R1 真实视觉 = metaworld 渲染 → YOLO detect_3d 每帧真推理 (SS_L2_YOLO)
  · L3 档  : L3 模型接管 = SmolVLA+LEW 策略真推理出动作 (SS_L3=1)
  · L4 档  : INTACT 节点执行 (SS_INTACT=1) + L2 兼容 (SS_USE_MLP=1: 前馈 MLP 真身 + YOLO 同档)
  · L5 档  : L5 规划/标注链 (planner + 视觉决策)

取证口径 (不看日志口气, 看计数与落盘):
  · 每档: 步数 / done / 终点距离 / YOLO 出帧数与检出数 / 前馈 MLP 真身次数 n_mlp / INTACT 调用数 /
    阶段覆盖 / 墙钟 —— 并落一份 reports/run_all_models_<时间>.json (逐档一行, 可对比)
  · 日志里的模型执行行原样留档 (samples), 便于人工核

用法:
  ./gui-venv311/bin/python tools/run_all_models.py                 # 默认 l2,l3,l4,l5 各 150 步
  ./gui-venv311/bin/python tools/run_all_models.py --caps l3,l4 --steps 120
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "tools"), os.path.join(ROOT, "src"), os.path.join(ROOT, "tools", "gui")]

import numpy as np  # noqa: E402

# 每档要设的开关 (与 simulink_module.py 装配块逐条对应)
CAP_ENV = {
    "l2": {"vision": True, "set": {}, "pop": ["SS_L3", "SS_INTACT", "SS_USE_MLP", "SS_L4_INTACT"]},
    "l3": {"vision": True, "set": {"SS_L3": "1"}, "pop": ["SS_INTACT", "SS_USE_MLP", "SS_L4_INTACT"]},
    "l4": {"vision": True, "set": {"SS_INTACT": "1", "SS_USE_MLP": "1"}, "pop": ["SS_L3", "SS_L4_INTACT"]},
    "l5": {"vision": True, "set": {}, "pop": ["SS_L3", "SS_INTACT", "SS_USE_MLP", "SS_L4_INTACT"]},
}
PATS = {
    "yolo": re.compile(r"YOLO"),
    "mlp真身": re.compile(r"MLP ?真身|前馈加速器"),
    "intact": re.compile(r"INTACT"),
    "l3策略": re.compile(r"L3|SmolVLA|smolvla"),
    "l5规划": re.compile(r"L5|planner|规划|DeepSeek|VLM"),
}


def wire_intact(sim) -> tuple[bool, list[str]]:
    """按 GUI 同一装配器 (install_direct_act) 把 INTACT 节点接进引擎 — 与 simulink_module 逐行同源。

    GUI 口径: cap=L4 且勾选「🤖 L4 用 INTACT 节点执行」→ IntactRuntime(task='pusht', device='cpu')
    + install_direct_act(每帧真推理) + attach_intact, 并**关掉 SS_INTACT**(避免 u_ff 槽位重复注入)。
    """
    import intact_direct_rollout as _idr  # noqa: PLC0415

    from lerobot.manifold.intact_node import IntactNode, IntactRuntime  # noqa: PLC0415

    msgs: list[str] = []
    rti = IntactRuntime(task="pusht", device="cpu")
    nd = IntactNode(horizon=8, runtime=rti)
    if not getattr(nd.runtime, "trained", False):
        msgs.append("❌ INTACT 未就绪 (%s) → 保持解析链" % getattr(nd.runtime, "reason", "?"))
        return False, msgs
    gf = os.path.join(ROOT, "reports", "intact_goal_frame.npy")
    stf, why = _idr.resolve_stats()
    msgs.append(why)
    if not (os.path.isfile(gf) and os.path.isfile(stf)):
        msgs.append("❌ 缺目标帧/归一化统计 → 保持解析链")
        return False, msgs
    nd.set_goal(np.load(gf))
    am, asd, _m = _idr.load_stats(stf)
    rec, stt = _idr.install_direct_act(sim, nd, am, asd, infer_every=1)
    sim.attach_intact(nd, None)
    sim._intact_drive = {"node": nd, "rec": rec, "state": stt}
    os.environ.pop("SS_INTACT", None)          # 防 u_ff 重复注入 (GUI 同口径)
    msgs.append("🤖 L4 = INTACT 节点直驱装配完成 (每帧 模型动作→env.step)")
    return True, msgs


def run_one(cap: str, steps: int, seed: int) -> dict:
    cfg = CAP_ENV[cap]
    for k in cfg["pop"]:
        os.environ.pop(k, None)
    for k, v in cfg["set"].items():
        os.environ[k] = v
    # L2 档的 R1 视觉开关 (GUI: SS_L2_YOLO 默认开)
    os.environ.pop("SS_L2_YOLO", None) if cfg["vision"] else os.environ.setdefault("SS_L2_YOLO", "0")

    from state_space_sim_real import RealStateSpaceSim  # noqa: PLC0415

    logs: list[str] = []
    t0 = time.time()
    sim = RealStateSpaceSim(seed=seed, vision=cfg["vision"], vision_every=1, mode="full",
                            log=lambda *a: logs.append(" ".join(str(x) for x in a)))
    load_s = time.time() - t0
    wire_msgs: list[str] = []
    intact_wired = False
    if cap == "l4":
        try:
            intact_wired, wire_msgs = wire_intact(sim)
        except Exception as e:  # noqa: BLE001
            wire_msgs = ["❌ INTACT 装配异常: %s: %s" % (type(e).__name__, e)]
    acc = sim.accel
    tr = sim.run(max_steps=steps, cap=cap)
    el = time.time() - t0
    vis = getattr(sim, "_vis", {}) or {}
    istat = dict(getattr(sim, "_intact_stats", {}) or {})
    idrv = getattr(sim, "_intact_drive", None) or {}
    dst = dict(idrv.get("state") or {})            # 直驱通道: state['calls'] = 模型真推理次数
    intact_calls = int(dst.get("calls", 0) or 0) or int(istat.get("intact_calls", 0) or 0)
    l4 = {}
    for attr in ("_l4_stats", "_intact_stats"):
        d = getattr(sim, attr, None)
        if isinstance(d, dict) and d:
            l4 = d
            break
    dist = tr.get("dist") or []
    meta = tr.get("_meta") or {}
    counts = {k: sum(1 for l in logs if p.search(l)) for k, p in PATS.items()}
    samples = {}
    for k, p in PATS.items():
        hit = [l for l in logs if p.search(l)]
        if hit:
            samples[k] = hit[-1][:220]
    return {
        "cap": cap.upper(), "steps_req": steps, "steps": len(tr.get("t") or []),
        "done": bool((tr.get("done") or [False])[-1]) if tr.get("done") else None,
        "dist_min_mm": round(float(np.min(dist)) * 1000, 2) if dist else None,
        "dist_last_mm": round(float(dist[-1]) * 1000, 2) if dist else None,
        "yolo_shots": int(vis.get("shot") or 0), "yolo_dets": int(vis.get("n") or 0),
        "yolo_per_frame": (round(float(vis.get("n") or 0) / float(vis.get("shot") or 1), 2)
                           if vis.get("shot") else None),
        "n_mlp": int(getattr(acc, "n_mlp", -1)), "n_guard": int(getattr(acc, "n_guard", -1)),
        "intact_wired": intact_wired, "intact_wire_msgs": wire_msgs,
        "intact_calls": intact_calls, "intact_drive_state": {k: v for k, v in dst.items()
                                                             if isinstance(v, (int, float, str, bool))},
        "intact_u_ff_src": istat.get("u_ff_src", ""),
        "intact_gate_pass": int(l4.get("gate_pass", 0) or 0),
        "intact_refused": int(l4.get("refused", 0) or 0),
        "model_calls": int(meta.get("calls", 0) or 0) if isinstance(meta.get("calls"), (int, float)) else None,
        "stage_counts": (lambda s: {x: s.count(x) for x in sorted(set(s))})(list((meta.get("rec") or {}).get("stage") or [])),
        "log_counts": counts, "log_samples": samples,
        "load_s": round(load_s, 1), "elapsed_s": round(el, 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--caps", default="l2,l3,l4,l5")
    ap.add_argument("--steps", type=int, default=150)
    ap.add_argument("--seed", type=int, default=104)
    a = ap.parse_args()

    rows = []
    for cap in [c.strip().lower() for c in a.caps.split(",") if c.strip()]:
        print("▶ 档位 %s 起跑 (steps=%d)…" % (cap.upper(), a.steps), flush=True)
        try:
            r = run_one(cap, a.steps, a.seed)
        except Exception as e:  # noqa: BLE001
            r = {"cap": cap.upper(), "error": "%s: %s" % (type(e).__name__, e)}
            print("  ❌ %s" % r["error"], flush=True)
        rows.append(r)
        if "error" not in r:
            print("  ✅ %s: 步数 %s · done=%s · 终点 %.2fmm · YOLO %s 帧/%s 检出(每帧 %s) · MLP真身 %s · "
                  "INTACT 真推理 %s%s · 墙钟 %ss" % (
                      r["cap"], r["steps"], r["done"], r["dist_min_mm"] or -1,
                      r["yolo_shots"], r["yolo_dets"], r["yolo_per_frame"],
                      r["n_mlp"], r["intact_calls"],
                      " (直驱已装配)" if r.get("intact_wired") else "", r["elapsed_s"]), flush=True)

    out = {"ts": time.strftime("%F %T"), "seed": a.seed, "steps": a.steps, "rows": rows}
    p = os.path.join(ROOT, "reports", "run_all_models_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("\n=== 汇总 (证据: %s) ===" % p)
    print("%-6s %6s %6s %9s %12s %8s %10s %7s" % (
        "档位", "步数", "done", "终点mm", "YOLO帧/检出", "MLP真身", "INTACT真推理", "墙钟s"))
    for r in rows:
        if "error" in r:
            print("%-6s  ❌ %s" % (r["cap"], r["error"][:70]))
            continue
        print("%-6s %6s %6s %9s %12s %8s %10s %7s" % (
            r["cap"], r["steps"], r["done"], r["dist_min_mm"],
            "%s/%s" % (r["yolo_shots"], r["yolo_dets"]), r["n_mlp"], r["intact_calls"], r["elapsed_s"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
