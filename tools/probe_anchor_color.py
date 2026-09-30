#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""锚框内到底是什么颜色? —— 定 绿掩膜 阈值用 (别拍脑袋调)。"""
import sys
from pathlib import Path

REPO = Path("/home/ubuntu/zmax")
sys.path.insert(0, str(REPO / "tools"))
import cv2                                                                           # noqa: E402
import numpy as np                                                                   # noqa: E402
import scene_overlay as SO                                                           # noqa: E402

raw = SO.fetch_frame("arm")
img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
H, W = img.shape[:2]
spec = SO.load_spec()
boxes = (spec.get("cameras", {}).get("arm", {}).get("boxes") or [])
print("臂帧 %dx%d" % (W, H))
for b in boxes:
    if not b.get("xyxy") or b.get("origin") not in ("vlm", "det"):
        continue
    x1, y1, x2, y2 = [int(round(float(v))) for v in b["xyxy"]]
    x1, y1, x2, y2 = max(0, x1), max(0, y1), min(W, x2), min(H, y2)
    sub = img[y1:y2, x1:x2]
    sh = hsv[y1:y2, x1:x2]
    if sub.size == 0:
        continue
    pb, pg, pr = float(sub[:, :, 0].mean()), float(sub[:, :, 1].mean()), float(sub[:, :, 2].mean())
    mh, ms, mv = (float(sh[:, :, 0].mean()), float(sh[:, :, 1].mean()), float(sh[:, :, 2].mean()))
    g1 = int(cv2.inRange(sh, (35, 60, 40), (95, 255, 255)).sum() // 255)
    g2 = int(cv2.inRange(sh, (30, 25, 15), (100, 255, 255)).sum() // 255)
    tot = sub.shape[0] * sub.shape[1]
    print("  [%s] %-10s xyxy=%s %dx%d(%dpx)" % (b.get("origin"), str(b.get("label"))[:10], b["xyxy"], x2 - x1, y2 - y1, tot))
    print("      BGR均值=(%.0f,%.0f,%.0f)  HSV均值=(%.0f,%.0f,%.0f)  绿掩膜(严)=%d(%.0f%%)  绿掩膜(宽)=%d(%.0f%%)"
          % (pb, pg, pr, mh, ms, mv, g1, 100.0 * g1 / max(1, tot), g2, 100.0 * g2 / max(1, tot)))

# 直接看 YOLO peg 框中心 20x20 的原始像素, 确认模块到底是什么颜色
det = [b for b in boxes if b.get("origin") == "det" and b.get("xyxy")]
if det:
    x1, y1, x2, y2 = [int(v) for v in det[0]["xyxy"]]
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
    print("  det 框心(%d,%d) 周围 9x9 的中位 BGR = %s · 中位 HSV = %s" % (
        cx, cy, np.median(img[cy - 4:cy + 5, cx - 4:cx + 5].reshape(-1, 3), axis=0).astype(int),
        np.median(hsv[cy - 4:cy + 5, cx - 4:cx + 5].reshape(-1, 3), axis=0).astype(int)))
