#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L5→L4→L3→L2 pipeline 拉通审计 第二轮 —— 全真件 + 零回退 A/B

① L5 真 TaskPlanner 可用性 (本 venv)
② 基线臂: 引擎原生解析链 (不挂 pipeline)      → done/steps/insert_mm
③ 全真件臂: L5=planner.taskplanner · L2=detect.yolo(在役) · L4=vote[unified,intact] · L3=dispatch
④ 逐帧: 每层 src/ok/conf/ms + L2 收口闸 veto 计数
"""
import json
import os
import sys
import time

REPO = "/home/ubuntu/lerobot-smolvla-lew"
for _p in (REPO + "/tools", REPO + "/tools/gui", REPO + "/src"):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import numpy as np  # noqa: E402

TS = time.strftime("%Y%m%d_%H%M%S")
EVID = {"ts": time.strftime("%Y-%m-%d %H:%M:%S")}
STEPS = int(os.environ.get("AUDIT_STEPS", "400"))


def hr(t):
    print("\n" + "=" * 78 + "\n" + t + "\n" + "=" * 78, flush=True)


# ── ① L5 真 TaskPlanner ──
hr("① L5 真 TaskPlanner (state_space/planner.py) 可用性")
try:
    from lerobot.policies.left_right.state_space.planner import TaskPlanner  # noqa: PLC0415
    _pl = TaskPlanner()
    _tk = _pl.plan("把光模块插入治具")
    _ok = bool(_pl.validate(_tk)) if _tk else False
    EVID["L5_taskplanner"] = {"import": True, "n_tokens": len(_tk or []), "validate": _ok,
                              "tokens": [str(t)[:40] for t in (_tk or [])[:8]]}
    print("  ✅ TaskPlanner: %d tokens · validate=%s" % (len(_tk or []), _ok))
    L5_IMPL = "planner.taskplanner"
except Exception as e:                                                   # noqa: BLE001
    EVID["L5_taskplanner"] = {"import": False, "err": "%s: %s" % (type(e).__name__, e)[:200]}
    print("  ❌ TaskPlanner 不可用: %s" % e)
    L5_IMPL = "planner.rules"


class Rec:
    """记录每帧各层输出"""
    def __init__(self, inner):
        self._inner = inner
        self.frames = []

    def __getattr__(self, k):
        return getattr(self._inner, k)

    def step(self, fr, obs_source=None, skill_ctx=None):
        out = self._inner.step(fr, obs_source=obs_source, skill_ctx=skill_ctx)
        L = getattr(out, "layers", None) or {}
        self.frames.append({"std": round(float(np.asarray(fr).std()), 2),
                            "layers": {k: {"src": v.src, "ok": bool(v.ok),
                                           "conf": round(float(v.conf), 3),
                                           "ms": round(float(v.latency_ms), 1)}
                                       for k, v in L.items()}})
        return out


def run_arm(tag, spec=None, l4=True):
    """spec=None → 基线臂 (不挂 pipeline)"""
    for k in ("SS_INTACT", "SS_L4_INTACT", "SS_L4_INTACT_SHADOW", "SS_INTACT"):
        os.environ.pop(k, None)
    from state_space_sim_real import RealStateSpaceSim                # noqa: PLC0415
    sim = RealStateSpaceSim(seed=104, vision=False, mode="insert", log=lambda *a: None)
    node = None
    if spec is not None:
        os.environ["SS_L4_INTACT"] = "1"
        os.environ.setdefault("SS_INTACT_EVERY", "8")
        from multi_layer_pipeline import PipelineNode                 # noqa: PLC0415
        node = Rec(PipelineNode(spec=spec, sim=sim))
        sim.attach_intact(node, None)
    t0 = time.time()
    tr = sim.run(max_steps=STEPS)
    wall = time.time() - t0
    st = dict(getattr(sim, "_l4_stats", {}) or {})
    row = {"arm": tag, "steps": len(tr["t"]), "done": bool(tr["done"][-1]) if tr.get("done") else False,
           "insert_mm": round(float(tr["dist"][-1]) * 1000, 1) if tr.get("dist") else None,
           "min_dist_mm": round(float(np.min(tr["dist"])) * 1000, 1) if tr.get("dist") else None,
           "wall_s": round(wall, 1)}
    if node is not None:
        lk = {}
        for f in node.frames:
            for k, v in f["layers"].items():
                d = lk.setdefault(k, {"calls": 0, "ok": 0, "src": {}, "ms_sum": 0.0})
                d["calls"] += 1
                d["ok"] += int(v["ok"])
                d["src"][v["src"]] = d["src"].get(v["src"], 0) + 1
                d["ms_sum"] += v["ms"]
        row["pipeline"] = {
            "frames": len(node.frames),
            "layers": {k: {"calls": v["calls"], "ok": v["ok"], "src": v["src"],
                           "avg_ms": round(v["ms_sum"] / max(v["calls"], 1), 2)}
                       for k, v in lk.items()},
            "frame_std": [min(f["std"] for f in node.frames), max(f["std"] for f in node.frames)],
            "engine": {"calls": st.get("calls", 0), "reuse": st.get("reuse", 0),
                       "refused": st.get("refused", 0), "w_zero": st.get("w_zero", 0),
                       "blend": st.get("blend", 0), "u_ff_src": st.get("u_ff_src"),
                       "err": st.get("err")},
            "l2_gate": {"veto": st.get("l2_veto", 0), "veto_dir": st.get("l2_veto_dir", 0),
                        "veto_mag": st.get("l2_veto_mag", 0)},
        }
    print("  ▶ " + json.dumps(row, ensure_ascii=False)[:1500])
    return row


hr("② 基线臂 · 引擎原生解析链 (不挂 pipeline)")
EVID["baseline"] = run_arm("baseline_analytic", spec=None)

hr("③ 全真件臂 · L5=%s · L2=detect.yolo · L4=vote[unified,intact] · L3=dispatch" % L5_IMPL)
from multi_layer_pipeline import build_default_spec                    # noqa: E402
_spec = build_default_spec(L5=L5_IMPL, L2="detect.yolo", L4="node.unified",
                           L3="dispatch.engine")
_spec["L4"] = {"impl": "node.unified", "on": True, "combine": "vote", "peers": ["node.intact"]}
EVID["full_pipeline"] = run_arm("full_pipeline", spec=_spec)

b, f = EVID["baseline"], EVID["full_pipeline"]
EVID["zero_regression"] = {"baseline_done": b["done"], "pipeline_done": f["done"],
                           "baseline_insert_mm": b["insert_mm"],
                           "pipeline_insert_mm": f["insert_mm"],
                           "same_or_better": bool(f["done"] and (f["insert_mm"] or 1e9)
                                                  <= (b["insert_mm"] or 1e9) + 1e-6)}

out = os.path.join(REPO, "docs", "pipeline_audit2_%s.json" % TS)
json.dump(EVID, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("\n✅ 证据: %s" % out)
print("零回退判据: " + json.dumps(EVID["zero_regression"], ensure_ascii=False))
