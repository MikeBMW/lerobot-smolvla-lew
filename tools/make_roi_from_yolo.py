#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_roi_from_yolo.py — 用**在役权重**给一个会话生成模块区域侧车 roi.jsonl (S0/S2 的 ROI 来源)

为什么需要: 差分质心会把"模块+夹爪"合成运动混在一起 (演练实测: 不收口到模块, 标签 IoU 0.0)。
ROI 只用来"选区域", **不产生标签** (标签仍来自几何真值) → 不构成自证循环。

口径 (写死, 不猜):
  · 权重 = models/yolo_peg_live.pt (在役单点指针) —— 记录 sha256, 可追溯
  · 只用 **peg** 类; conf ≥ --conf (默认 0.20, 低于在役权重在真机帧上的实测 ~0.295 一档)
  · 每帧取**面积最大**的一个框作 ROI; 一帧多框时如实记 n_boxes
  · conf 默认 **0.50** (实测: 在役权重在真机帧上 0.91~0.94 是常规, 0.21 那种是贴边残框)
  · **贴边框剔除**: 框触到画面边缘 = 模块被裁掉 → 不算可用 ROI (实测出现过 9.8x131px 贴右边框)
  · 检不到 / 贴边 → **不写该帧** (缺口如实留空, 下游按"该帧无 ROI → 保守不发标签"处理)

用法:
  gui-venv311/bin/python tools/make_roi_from_yolo.py --session data/yolo_annot/sessions/<会话>
  gui-venv311/bin/python tools/make_roi_from_yolo.py --frames <目录> --out <roi.jsonl> --conf 0.2
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import sys
import time

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
LIVE = os.path.join(_REPO, "models", "yolo_peg_live.pt")


def sha256_file(p, n=1 << 20):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while True:
            b = f.read(n)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default=None, help="会话目录 (自动取 frames/ + truth.jsonl + roi.jsonl)")
    ap.add_argument("--frames", default=None, help="直接给 frames 目录")
    ap.add_argument("--truth", default=None, help="truth.jsonl (可选: 从框中心读 TCP 做抽检)")
    ap.add_argument("--out", default=None, help="roi.jsonl 落盘 (默认写在会话目录)")
    ap.add_argument("--weights", default=LIVE)
    ap.add_argument("--conf", type=float, default=0.50)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--cls", default="peg")
    a = ap.parse_args()

    frames_dir = a.frames or (os.path.join(a.session, "frames") if a.session else None)
    if not frames_dir or not os.path.isdir(frames_dir):
        print("❌ 需要 --session <会话目录> 或 --frames <frames目录>")
        return 1
    out = a.out or (os.path.join(a.session, "roi.jsonl") if a.session else
                    os.path.join(os.path.dirname(frames_dir), "roi.jsonl"))
    truth_f = a.truth or (os.path.join(a.session, "truth.jsonl") if a.session else None)

    w = os.path.realpath(a.weights) if os.path.exists(a.weights) else None
    if w is None:
        print(f"❌ 权重不存在: {a.weights} (在役指针 models/yolo_peg_live.pt)")
        return 1
    try:
        from ultralytics import YOLO
    except ImportError as e:
        print(f"❌ 需要 ultralytics: {e}")
        return 1

    files = sorted(glob.glob(os.path.join(frames_dir, "*.jpg")))
    if not files:
        print(f"❌ {frames_dir} 里没有 jpg")
        return 1
    truth = {}
    if truth_f and os.path.isfile(truth_f):
        for ln in open(truth_f, encoding="utf-8"):
            ln = ln.strip()
            if ln:
                try:
                    r = json.loads(ln)
                    truth[str(r.get("stem"))] = r.get("truth", {})
                except ValueError:
                    pass

    wsha = sha256_file(w)[:16]            # 只算一次 (循环里反复开权重文件会拿到坏 fd)
    import cv2
    model = YOLO(w)
    names = model.names
    rows, miss, multi = [], 0, 0
    for fp in files:
        stem = os.path.splitext(os.path.basename(fp))[0]
        img = cv2.imread(fp)
        if img is None:
            miss += 1
            continue
        r = model.predict(img, imgsz=a.imgsz, conf=a.conf, verbose=False)[0]
        cand = []
        for cf, cl, xy in zip(r.boxes.conf.tolist(), r.boxes.cls.tolist(), r.boxes.xyxy.tolist()):
            if names.get(int(cl), "") != a.cls:
                continue
            cand.append((float(cf), [float(v) for v in xy]))
        if not cand:
            miss += 1
            continue
        if len(cand) > 1:
            multi += 1
        ih, iw = img.shape[:2]          # 别用 w (那是权重路径变量)
        cand = [c for c in cand if c[1][0] > 2 and c[1][1] > 2 and c[1][2] < iw - 2 and c[1][3] < ih - 2]
        if not cand:
            miss += 1                      # 只有贴边残框 → 不算可用 ROI
            continue
        cand.sort(key=lambda t: (t[1][2] - t[1][0]) * (t[1][3] - t[1][1]), reverse=True)   # 取面积最大
        cf, xy = cand[0]
        rows.append({"stem": stem, "box": [round(v, 1) for v in xy], "conf": round(cf, 4),
                     "n_boxes": len(cand), "src": "yolo:peg(yolo_peg_live.pt)",
                     "weights_sha256": wsha, "tcp": (truth.get(stem) or {}).get("tcp")})

    with open(out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    confs = [r["conf"] for r in rows]
    print(f"权重: {w} (sha256 {wsha}) · conf≥{a.conf} · imgsz {a.imgsz} · 类 {a.cls}")
    print(f"帧 {len(files)} → 写出 ROI {len(rows)} 条 · 未检出 {miss} 帧 (缺口留空不补) · 多框 {multi} 帧")
    if rows:
        print(f"conf: 中位 {np.median(confs):.3f} · 最小 {min(confs):.3f} · 最大 {max(confs):.3f}")
        ws = [r["box"][2] - r["box"][0] for r in rows]
        hs = [r["box"][3] - r["box"][1] for r in rows]
        print(f"ROI 尺寸: 宽中位 {np.median(ws):.1f}px · 高中位 {np.median(hs):.1f}px")
    print(f"📄 {out}")
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
