#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_overlay_from_det.py — 真机 YOLO 检测 → 边界框规格 (origin="det")
════════════════════════════════════════════════════════════════
用**在役权重** models/yolo_peg_live.pt（软链 → runs/detect/.../best.pt）跑当前实帧，
把检测框写进叠加规格。与仿真投影/大模型框并列显示、互不覆盖。

坑: ultralytics 传 numpy 时按 **BGR** 直接吃（imread 的图直接用，别转 RGB）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scene_overlay as SO   # noqa: E402

REPO = Path(__file__).resolve().parent.parent
WEIGHTS = REPO / "models" / "yolo_peg_live.pt"


def main_cli(cam: str = "arm", conf: float = 0.25, path: str = "") -> str:
    if not WEIGHTS.exists():
        return "✗ 在役权重不存在: %s" % WEIGHTS
    raw = SO.fetch_frame(cam, path=path)
    if not raw:
        return "✗ 取不到 %s 的实帧" % cam
    import cv2
    import numpy as np
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return "✗ 帧解码失败"
    from ultralytics import YOLO
    m = YOLO(str(WEIGHTS))
    res = m.predict(img, conf=conf, verbose=False)     # 直接吃 BGR ndarray
    boxes = []
    for r in res:
        names = r.names
        for b in (r.boxes or []):
            xyxy = [float(v) for v in b.xyxy[0].tolist()]
            boxes.append({"label": names.get(int(b.cls[0]), "obj"), "origin": "det",
                          "xyxy": xyxy, "conf": round(float(b.conf[0]), 3)})
    spec = SO.load_spec()
    SO.merge_origin(spec, cam, "det", boxes, meta={
        "weights": str(WEIGHTS.name), "conf_thr": conf, "n": len(boxes),
        "cam": cam})
    if not spec.get("source"):
        spec["source"] = "真机 YOLO 检测 (在役权重)"
    SO.save_spec(spec)
    return "真机检测: %d 框 (conf>=%.2f, 权重 %s)" % (len(boxes), conf, WEIGHTS.name)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cam", default="arm", choices=["arm", "local"])
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--frame", default="")
    a = ap.parse_args()
    print("  " + main_cli(a.cam, a.conf, a.frame))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
