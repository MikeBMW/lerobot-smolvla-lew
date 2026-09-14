# -*- coding: utf-8 -*-
"""🔁 ab_intent_line_closedloop.py — 直连线**闭环 A/B** (同权重同 seed, 只改臂)

口径 (老倪: 有提升非仅不回退; 每次 A/B 同口径):
  权重 = 当前 L4 指针 (intact_l4_current → r11 ep1, 2026-09-15 01:29 切换)
  四臂 × 每 seed:
    analytic    : SS_L4_INTACT 不设 → 解析链 (对照锚)
    direct      : SS_L4_INTACT=1, 直连线关     → 本轮"直驱"基准
    line_w0     : 直连线开但 w=0 (真推理不注入) → 验证"不注入≈基准"
    line_w1     : 直连线开且注入 (w=1)          → 待验证是否有提升
  指标 (全部取自引擎真跑): done · steps · 末端插入 mm (tr["dist"][-1]) · 末端 peg头↔目标 mm ·
  全程最小 peg头↔目标 mm (过冲/未插入的诊断量) · u_ff 轨迹 hash · 直连线证据 (ran/applied/clip)

输出: reports/ab_intent_line_closedloop_<ts>.json + 同目录 .log
用法: MUJOCO_GL=egl gui-venv311/bin/python tools/ab_intent_line_closedloop.py [--seeds 0,1,2] [--steps 600]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time

import numpy as np

os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("DISPLAY", ":0")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUI = os.path.join(ROOT, "tools", "gui")
for _p in (ROOT, os.path.join(ROOT, "src"), os.path.join(ROOT, "tools"), GUI):
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.chdir(GUI)
os.environ.setdefault("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache")
os.environ.setdefault("LOCAL_DATASET_DIR", "/home/ubuntu/stable-wm-cache")
os.environ.setdefault("INTACT_RUNTIME", "root")
os.environ.setdefault("INTACT_POLICY", "intact_l4_current")      # 指针 = r11 ep1
os.environ.setdefault("OMP_NUM_THREADS", "6")
_S6 = "接近,对位,下降,抓取,抬起,转移"
_S7 = _S6 + ",插入"                      # 插入段解禁 (原白名单故意排除"插入")
# 臂: (L4直驱?, 直连线?, 注入权重, 阶段白名单)
ARMS = {"analytic":        (False, False, 0.0, None),
        "direct":          (True, False, 0.0, None),
        "line_w0":         (True, True, 0.0, None),
        "line_w1":         (True, True, 1.0, None),
        "direct_ins":      (True, False, 0.0, _S7),
        "line_w1_ins":     (True, True, 1.0, _S7)}


def hh(a) -> str:
    a = np.ascontiguousarray(np.asarray(a, float))
    return hashlib.sha256(a.tobytes()).hexdigest()[:16]


def run_one(seed: int, arm: str, steps: int) -> dict:
    l4, line, w, stages = ARMS[arm]
    if l4:
        os.environ["SS_L4_INTACT"] = "1"
    else:
        os.environ.pop("SS_L4_INTACT", None)
    if stages:
        os.environ["SS_L4_INTACT_STAGES"] = stages
    else:
        os.environ.pop("SS_L4_INTACT_STAGES", None)
    if line:
        os.environ["SS_L4_INTENT_LINE"] = "1"
        os.environ["SS_L4_INTENT_LINE_W"] = str(w)
    else:
        os.environ.pop("SS_L4_INTENT_LINE", None)
        os.environ.pop("SS_L4_INTENT_LINE_W", None)
    from state_space_sim_real import RealStateSpaceSim
    from lerobot.manifold.intact_node import IntactNode, IntactRuntime
    t0 = time.time()
    sim = RealStateSpaceSim(seed=seed, vision=False, mode="insert", log=lambda *x: None)
    node = IntactNode(horizon=8, runtime=IntactRuntime(task="pusht", device="cpu"))
    sim.attach_intact(node)
    tr = sim.run(max_steps=steps)
    dist = np.asarray(tr.get("dist") or [], float)
    peg = np.asarray(tr.get("peg_head") or [], float).reshape(-1, 3) if tr.get("peg_head") else None
    tgt = np.asarray(tr.get("target") or [], float).reshape(-1, 3) if tr.get("target") else None
    g2g = (np.linalg.norm(peg - tgt, axis=1) if (peg is not None and tgt is not None
                                                and len(peg) == len(tgt) and len(peg)) else None)
    uff = np.asarray(tr.get("u_ff_vec") or [], float)
    ils = sim.l4_intent_line_summary()
    stg = [str(x).replace("阶段 ", "") for x in (tr.get("stage") or [])]
    from collections import Counter
    return {"seed": seed, "arm": arm, "steps": int(len(tr.get("t", []))),
            "stage_counts": dict(Counter(stg)),
            "done": bool(tr.get("done", [False])[-1]),
            "insert_mm_end": round(float(dist[-1]) * 1000, 1) if dist.size else None,
            "insert_mm_min": round(float(dist.min()) * 1000, 1) if dist.size else None,
            "peg_tgt_mm_end": round(float(g2g[-1]) * 1000, 1) if g2g is not None else None,
            "peg_tgt_mm_min": round(float(g2g.min()) * 1000, 1) if g2g is not None else None,
            "u_ff_hash": hh(uff) if uff.size else "none",
            "line": {k: ils.get(k) for k in ("enabled", "ran", "applied", "w_zero", "refused",
                                             "ready", "w_last", "clip_max", "err",
                                             "by_stage", "stages_env")},
            "sec": round(time.time() - t0, 1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="0,1,2")
    ap.add_argument("--steps", type=int, default=600)
    ap.add_argument("--arms", default="analytic,direct,line_w0,line_w1")
    a = ap.parse_args()
    seeds = [int(x) for x in a.seeds.split(",") if x.strip()]
    arms = [x.strip() for x in a.arms.split(",") if x.strip()]
    ts = time.strftime("%Y%m%d_%H%M%S")
    out = os.path.join(ROOT, "reports", f"ab_intent_line_closedloop_{ts}.json")
    log = os.path.join(ROOT, "reports", f"ab_intent_line_closedloop_{ts}.log")

    def say(s):
        print(s, flush=True)
        open(log, "a", encoding="utf-8").write(s + "\n")

    rows = []
    for sd in seeds:
        for arm in arms:
            try:
                r = run_one(sd, arm, a.steps)
            except Exception as e:                                          # noqa: BLE001
                r = {"seed": sd, "arm": arm, "error": f"{type(e).__name__}: {e}"}
            rows.append(r)
            json.dump({"ts": ts, "policy": os.environ.get("INTACT_POLICY"), "steps_cap": a.steps,
                       "rows": rows}, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            say(f"[seed{sd} {arm:9s}] done={r.get('done')} steps={r.get('steps')} "
                f"插入末端={r.get('insert_mm_end')}mm 最小={r.get('insert_mm_min')}mm · "
                f"peg-target 末端={r.get('peg_tgt_mm_end')}mm 最小={r.get('peg_tgt_mm_min')}mm · "
                f"line(ran={r.get('line',{}).get('ran')} applied={r.get('line',{}).get('applied')} "
                f"w={r.get('line',{}).get('w_last')}) · {r.get('sec')}s {r.get('error','')}")
    say(f"\n→ {os.path.relpath(out, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
