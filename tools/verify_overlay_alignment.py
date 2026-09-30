#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_overlay_alignment.py — 叠加框 vs 真机实测框 的对齐验证（端到端铁证）

口径: 两条**互相独立**的链，指向同一物体:
  · det 框: 真机 YOLO 在实帧上的 2D 检测 (纯图像侧, 不含任何几何)
  · sim 框: 深度实测 3D (base 系) → 手眼 X + 实时 TCP 真值 → 投影像素 (纯几何侧)
若投影链正确, sim 框应与 det 框高度重合 ⇒ 证明"仿真场景框叠加到真实视频"是**真几何**而非画上去的。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scene_overlay as SO   # noqa: E402


def iou(a, b):
    xa, ya = max(a[0], b[0]), max(a[1], b[1])
    xb, yb = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, xb - xa) * max(0.0, yb - ya)
    ar = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ar if ar > 0 else 0.0


def main() -> int:
    raw = SO.fetch_frame("arm")
    if not raw:
        print("  ✗ 取不到实帧"); return 1
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    H, W = img.shape[:2]
    tcp = SO.read_tcp()
    if tcp is None:
        print("  ✗ 读不到 TCP 真值"); return 1
    he = SO.load_handeye()
    objs = json.loads((SO.REPO / "data" / "scene" / "objects3d.json").read_text(encoding="utf-8"))["objects"]
    spec = SO.load_spec()

    K = SO.load_intrinsics(W, H)
    det_boxes = [b for b in (spec.get("cameras", {}).get("arm", {}).get("boxes") or [])
                 if b.get("origin") == "det"]
    print("  内参 %dx%d: fx=%.1f fy=%.1f cx=%.1f cy=%.1f%s"
          % (W, H, K["fx"], K["fy"], K["cx"], K["cy"], " (实测)" if not K.get("est") else " (外推)"))
    print("  手眼: %s · |t|=%.1fmm · 闭环 std=%.2fmm"
          % (he.get("method"), np.linalg.norm(he["X"][:3, 3]) * 1000, he.get("closed_loop_std_mm") or -1))
    print("  TCP 真值: (%.4f, %.4f, %.4f)m" % tuple(tcp[:3]))
    print()
    print("  ══ 对照表 ══")
    vis = img.copy()
    sim_boxes = []
    rows = []
    for o in objs:
        xy = SO.box3d_to_xyxy(o["center"], o.get("size", [40, 16, 12]), K, he["X"], tcp)
        if xy is None:
            print("    %-8s 投影不可见(视野外)" % o["name"]); continue
        sim_boxes.append((o["name"], xy, o))
    ok_pair = 0
    for nm, xy, o in sim_boxes:
        best, bd = None, None
        for b in det_boxes:
            d = abs((b["xyxy"][0] + b["xyxy"][2]) / 2 - (xy[0] + xy[2]) / 2)
            if bd is None or d < bd:
                bd, best = d, b
        if best is None:
            print("    %-8s sim框=%s  无 det 框可比" % (nm, [round(v, 1) for v in xy]))
            continue
        v = iou(xy, best["xyxy"])
        csim = [(xy[0] + xy[2]) / 2, (xy[1] + xy[3]) / 2]
        cdet = [(best["xyxy"][0] + best["xyxy"][2]) / 2, (best["xyxy"][1] + best["xyxy"][3]) / 2]
        dpx = float(np.hypot(csim[0] - cdet[0], csim[1] - cdet[1]))
        print("    %-8s sim框中心=(%5.1f,%5.1f)  det框中心=(%5.1f,%5.1f)  中心差=**%4.1f px**  框重叠 IoU=**%.3f**"
              % (nm, csim[0], csim[1], cdet[0], cdet[1], dpx, v))
        ok_pair += 1
        rows.append({"label": nm, "sim_xyxy": [round(q, 1) for q in xy],
                     "det_xyxy": [round(q, 1) for q in best["xyxy"]],
                     "center_err_px": round(dpx, 1), "iou": round(v, 3)})
        # 可视化: sim=绿实线, det=红虚线
        cv2.rectangle(vis, (int(xy[0]), int(xy[1])), (int(xy[2]), int(xy[3])), (94, 197, 34), 2)
        x1, y1, x2, y2 = [int(v2) for v2 in best["xyxy"]]
        for (px, py), (qx, qy) in (((x1, y1), (x1 + 14, y1)), ((x2 - 14, y1), (x2, y1)),
                                   ((x1, y1), (x1, y1 + 14)), ((x1, y2 - 14), (x1, y2)),
                                   ((x2, y1), (x2, y1 + 14)), ((x1, y2), (x1 + 14, y2)),
                                   ((x2 - 14, y2), (x2, y2)), ((x2, y2 - 14), (x2, y2))):
            cv2.line(vis, (px, py), (qx, qy), (60, 60, 235), 2)
        cv2.putText(vis, "sim(几何投影)", (int(xy[0]), max(12, int(xy[1]) - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (94, 197, 34), 1, cv2.LINE_AA)
        cv2.putText(vis, "det(真机YOLO)", (x1, min(H - 4, int(y2) + 14)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (60, 60, 235), 1, cv2.LINE_AA)

    if not rows:
        print("\n  ⚠ 无可对照对（需先跑 gen_overlay_from_det.py 产生 det 框）")
        return 1
    errs = np.array([r["center_err_px"] for r in rows])
    ious = np.array([r["iou"] for r in rows])
    print()
    print("  ══ 结论 ══")
    print("    对照 %d 对 · 中心误差 中位 %.1f px / 最大 %.1f px · IoU 中位 %.3f"
          % (len(rows), np.median(errs), errs.max(), np.median(ious)))
    print("    %s" % ("✅ 几何投影与真机检测重合 ⇒ 仿真框叠加是真实几何，不是画上去的"
                      if np.median(ious) > 0.2 else "⚠ IoU 偏低，需查（手眼旋转/物体尺寸）"))
    out = SO.REPO / "reports"
    out.mkdir(exist_ok=True)
    cv2.imwrite(str(out / "overlay_align_check.jpg"), vis)
    (out / "overlay_align_check.json").write_text(
        json.dumps({"rows": rows, "median_center_err_px": float(np.median(errs)),
                    "median_iou": float(np.median(ious)), "at": __import__("time").strftime("%F %T")},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    print("    证据图: %s" % (out / "overlay_align_check.jpg"))
    print("    数据:   %s" % (out / "overlay_align_check.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
