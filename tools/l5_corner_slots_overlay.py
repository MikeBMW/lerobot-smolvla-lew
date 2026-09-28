#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""l5_corner_slots_overlay.py — 把「治具 + 四角光模块 + 14 槽位」写进场景叠加规格(arm 相机路)

🔴 关键口径(用户投诉过的缺陷): **只增改 arm 相机路里 origin=l5corners 的框**,
   其它相机路 / 其它 origin(sim/vlm/det/human)一律不动 —— 走 scene_overlay.merge_origin(),
   不是整份重建。改完回读 /scene.json 复核条数。

用法:
  python3 tools/l5_corner_slots_overlay.py                    # 用最新一次 marks_*/slots_marks.json
  python3 tools/l5_corner_slots_overlay.py --marks <path>     # 指定
  python3 tools/l5_corner_slots_overlay.py --clear            # 只撤掉 origin=l5corners 的框
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import scene_overlay as SO                                              # noqa: E402

OUTROOT = Path.home() / "zmax_data" / "l5_corners"
ORIGIN = "l5corners"
CAM = "arm"


def latest_marks() -> Path:
    cands = sorted(OUTROOT.glob("marks_*/slots_marks.json"))
    if not cands:
        raise SystemExit("✗ 找不到 marks_*/slots_marks.json —— 先跑 tools/l5_corner_slots_mark.py")
    return cands[-1]


def build(m: dict) -> list:
    boxes = []
    f = m["fixture_aabb"]
    boxes.append({"label": "fixture", "origin": ORIGIN, "kind": "fixture",
                  "xyxy": [float(v) for v in f], "box2d": [float(v) for v in f], "conf": 0.85,
                  "why": "黑塑料托盘外沿(灰度<60 大连通域 + 目检边界)"})
    for k, md in m["modules"].items():
        a = md["aabb"]
        boxes.append({"label": "MOD_%s" % k, "origin": ORIGIN, "kind": "corner_module",
                      "xyxy": [float(v) for v in a], "box2d": [float(v) for v in a], "conf": 0.9,
                      "mm_per_px": md["mm_per_px_from_40mm"],
                      "size_mm_spec": m["module_mm_spec"],
                      "green_blob": md["green_blob"]})
    for s in m["slots"]:
        b = [float(v) for v in s["box"]]
        low = bool(s.get("covered_by"))          # 被模块盖住的 4 个: 位置是外推 ⇒ 明确低可信
        boxes.append({"label": s["id"], "origin": ORIGIN, "kind": "slot",
                      "row": s["row"], "col": s["col"], "xyxy": b, "box2d": b,
                      "conf": 0.35 if low else 0.7, "occluded_by": s.get("covered_by"),
                      "mm_per_px": s["mm_per_px"], "size_mm": s["size_mm"],
                      "center_mm_from_TL": s["center_mm_from_TL"],
                      "why": "位置由四角光模块 40mm 定标 + 治具几何推算" + ("(被模块盖住⇒外推)" if low else "(暗区实测+视觉复核)")})
    return boxes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--marks", default="")
    ap.add_argument("--clear", action="store_true")
    a = ap.parse_args()
    spec = SO.load_spec()
    before = {c: len((v or {}).get("boxes") or []) for c, v in (spec.get("cameras") or {}).items()}
    other_origins_before = sorted({b.get("origin") for c, v in (spec.get("cameras") or {}).items()
                                  for b in ((v or {}).get("boxes") or [])})
    if a.clear:
        boxes = []
        mp = None
    else:
        mp = Path(a.marks) if a.marks else latest_marks()
        m = json.loads(mp.read_text(encoding="utf-8"))
        boxes = build(m)
    meta = {"marks": str(mp) if mp else None, "ts": time.strftime("%F %T"), "origin": ORIGIN,
            "ruler": "光模块 40mm ↔ 白色本体像素长(mm/px: TL .406 / TR .382 / BL .343 / BR .321)",
            "note": "四角光模块 + 上排7/下排7 槽位 + 治具整体; 被模块盖住的 4 个槽位 conf=0.35 (外推)"}
    spec = SO.merge_origin(spec, CAM, ORIGIN, boxes, meta=meta)
    spec["source"] = "四角光模块(40mm标尺)+治具几何 → 14 槽位 (l5corners, %s)" % (mp.name if mp else "cleared")
    SO.save_spec(spec)
    # 回读复核
    back = SO.load_spec()
    arm_boxes = ((back.get("cameras") or {}).get(CAM) or {}).get("boxes") or []
    n_origin = sum(1 for b in arm_boxes if b.get("origin") == ORIGIN)
    n_other = len(arm_boxes) - n_origin
    all_origins_after = sorted({b.get("origin") for c, v in (back.get("cameras") or {}).items()
                               for b in ((v or {}).get("boxes") or [])})
    print("marks=%s" % mp)
    print("写前 arm boxes=%s  全仓 origins=%s" % (before.get(CAM), other_origins_before))
    print("写后 arm boxes=%d (origin=%s: %d · 其它来源: %d)  全仓 origins=%s"
          % (len(arm_boxes), ORIGIN, n_origin, n_other, all_origins_after))
    print("spec.mode=%s  updated_at=%s" % (back.get("mode"), back.get("updated_at")))
    kinds = {}
    for b in arm_boxes:
        kinds[b.get("kind", "?")] = kinds.get(b.get("kind", "?"), 0) + 1
    print("arm 路框构成: %s" % kinds)
    if n_other == 0 and not a.clear:
        print("✅ 只写了 arm 相机路(其它相机路与其它 origin 未被触碰)")
    print("spec 片段:")
    print(json.dumps({"cameras": {CAM: {"boxes": arm_boxes[:3], "...": "%d 条" % len(arm_boxes),
                                        "by_origin": ((back.get("cameras") or {}).get(CAM) or {}).get("by_origin")},
                                "其它相机路": [c for c in (back.get("cameras") or {}) if c != CAM]}},
                     ensure_ascii=False, indent=1)[:1800])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
