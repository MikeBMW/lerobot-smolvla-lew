#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L5→L4→L3→L2 拉通审计 第三轮 —— L2 真在役检测器 (光模块权重) + 全链每帧

① L2 单层对比: 在役 models/yolo_peg_live.pt  vs  通用 yolov8s.pt
   · 输入 = 产线真实帧 (/home/ubuntu/zmax_ss_remote/cam_rs.png)  (真件)
   · 输入 = 引擎渲染帧 (仿真域, 检验域差)
② 全链每帧 (L5=taskplanner · L2=在役检测器 · L4=vote[unified,intact] · L3=dispatch)
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


def _det_summary(yp, img, tag):
    t0 = time.time()
    det = yp.detect(img)
    ms = (time.time() - t0) * 1000
    rows = []
    for d in (det or []):
        if isinstance(d, dict):
            rows.append({k: (round(float(v), 3) if isinstance(v, (int, float)) else v)
                         for k, v in d.items() if k in ("cls", "name", "conf", "xyxy", "box", "label")})
        else:
            rows.append(str(d)[:80])
    return {"tag": tag, "model": os.path.basename(getattr(yp, "weights", "") or "?"),
            "n_det": len(det or []), "ms": round(ms, 1), "det": rows[:5]}


hr("① L2 真检测器对比 (在役光模块权重 vs 通用 yolov8s)")
from multi_layer_pipeline import _default_live_weights                       # noqa: E402
from yolo_perception import YoloPerception                                   # noqa: E402
LIVE = _default_live_weights()
print("  在役权重: %s" % LIVE)

import cv2                                                                   # noqa: E402
prod = None
try:
    bgr = cv2.imread("/home/ubuntu/zmax_ss_remote/cam_rs.png")
    if bgr is not None:
        prod = cv2.cvtColor(cv2.resize(bgr, (640, 480)), cv2.COLOR_BGR2RGB)
        print("  产线真帧: %s mean=%.1f std=%.1f" % (prod.shape, prod.mean(), prod.std()))
except Exception as e:                                                       # noqa: BLE001
    print("  ⚠️ 产线帧读取失败: %s" % e)

res = {"live_weights": LIVE, "prod_frame": prod is not None}
if prod is not None:
    yp_live = YoloPerception(weights=LIVE)
    yp_live._load()
    res["prod_live"] = _det_summary(yp_live, prod, "prod+live")
    yp_coco = YoloPerception()          # 默认 yolov8s.pt (COCO 80类)
    yp_coco._load()
    res["prod_coco"] = _det_summary(yp_coco, prod, "prod+coco")
    print("  在役权重: %s" % json.dumps(res["prod_live"], ensure_ascii=False))
    print("  COCO通用: %s" % json.dumps(res["prod_coco"], ensure_ascii=False))
EVID["L2_weights_compare"] = res


# ── ② 全链每帧 ──
class Rec:
    def __init__(self, inner):
        self._inner = inner
        self.frames = []

    def __getattr__(self, k):
        return getattr(self._inner, k)

    def step(self, fr, obs_source=None, skill_ctx=None):
        out = self._inner.step(fr, obs_source=obs_source, skill_ctx=skill_ctx)
        L = getattr(out, "layers", None) or {}
        rec = {}
        for k, v in L.items():
            d = v.data or {}
            rec[k] = {"src": v.src, "ok": bool(v.ok), "conf": round(float(v.conf), 3),
                      "ms": round(float(v.latency_ms), 1),
                      "det_n": (len(d.get("det") or []) if k == "L2" else None)}
        self.frames.append({"std": round(float(np.asarray(fr).std()), 2), "layers": rec})
        return out


hr("② 全链每帧 · L5=taskplanner · L2=在役检测器 · L4=vote[unified,intact] · L3=dispatch")
for k in ("SS_INTACT", "SS_L4_INTACT_SHADOW"):
    os.environ.pop(k, None)
os.environ["SS_L4_INTACT"] = "1"
os.environ.setdefault("SS_INTACT_EVERY", "8")

from multi_layer_pipeline import PipelineNode, build_default_spec          # noqa: E402
from state_space_sim_real import RealStateSpaceSim                         # noqa: E402

spec = build_default_spec(L5="planner.taskplanner", L2="detect.yolo", L4="node.unified",
                          L3="dispatch.engine")
spec["L4"] = {"impl": "node.unified", "on": True, "combine": "vote", "peers": ["node.intact"]}
sim = RealStateSpaceSim(seed=104, vision=False, mode="insert", log=lambda *a: None)
node = Rec(PipelineNode(spec=spec, sim=sim))
sim.attach_intact(node, None)
t0 = time.time()
tr = sim.run(max_steps=STEPS)
wall = time.time() - t0
st = dict(getattr(sim, "_l4_stats", {}) or {})

lk = {}
for f in node.frames:
    for k, v in f["layers"].items():
        d = lk.setdefault(k, {"calls": 0, "ok": 0, "src": {}, "ms": [], "det": []})
        d["calls"] += 1
        d["ok"] += int(v["ok"])
        d["src"][v["src"]] = d["src"].get(v["src"], 0) + 1
        d["ms"].append(v["ms"])
        if v["det_n"] is not None:
            d["det"].append(v["det_n"])

row = {
    "steps": len(tr["t"]), "done": bool(tr["done"][-1]) if tr.get("done") else False,
    "min_dist_mm": round(float(np.min(tr["dist"])) * 1000, 1) if tr.get("dist") else None,
    "wall_s": round(wall, 1), "pipeline_frames": len(node.frames),
    "layers": {k: {"calls": v["calls"], "ok": v["ok"], "src": v["src"],
                   "avg_ms": round(float(np.mean(v["ms"])), 2), "det_per_frame": v["det"]}
               for k, v in lk.items()},
    "frame_std": [min(f["std"] for f in node.frames), max(f["std"] for f in node.frames)],
    "engine": {"calls": st.get("calls", 0), "reuse": st.get("reuse", 0), "refused": st.get("refused", 0),
               "w_zero": st.get("w_zero", 0), "blend": st.get("blend", 0), "err": st.get("err")},
    "l2_gate": {"veto": st.get("l2_veto", 0), "veto_dir": st.get("l2_veto_dir", 0),
                "veto_mag": st.get("l2_veto_mag", 0)},
}
print("  ▶ " + json.dumps(row, ensure_ascii=False)[:1600])
EVID["full_pipeline_live_L2"] = row

out = os.path.join(REPO, "docs", "pipeline_audit3_%s.json" % TS)
json.dump(EVID, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("\n✅ 证据: %s" % out)
