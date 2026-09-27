#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""annot_push_feishu.py — 把**最新一批**自动标注的结果拼成一张总图 + 场景理解摘要, 推到飞书

老倪 (2026-09-27): 「开始自动标注; 我现在到飞书端与你人机交互」→
  数据由 tools/auto_annotate.py 持续产出(annotations.jsonl + 每批 summary.json),
  本脚本负责"把它变成飞书上能看的一眼东西": 2×3 标注总图 + 六路场景描述 + 有无可操作物体。

用法:
  python3 tools/annot_push_feishu.py                # 推最新一批(默认只推比上次更新的批次)
  python3 tools/annot_push_feishu.py --force        # 不管是否推过, 强推一次
  python3 tools/annot_push_feishu.py --text-only    # 只推文字(不发图)

设计: 去重靠 ~/zmax_data/auto_annotate/.pushed 记最后推送的批次名 ⇒ 定时跑也不会重复刷屏。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cv2                                                             # noqa: E402
import numpy as np                                                     # noqa: E402
import aoi_feishu_push as P                                            # noqa: E402

ROOT = os.path.expanduser("~/zmax_data/auto_annotate")
MARK = os.path.join(ROOT, ".pushed")
SHEET = "/tmp/annot_sheet_latest.jpg"
CAMS = [("arm", "🤖臂上"), ("local", "💻笔记本"), ("local2", "📺MAXHUB"),
        ("depth", "🟠深度"), ("aoi_gold", "🟡金手指"), ("aoi_surface", "⚪表面")]


def latest_batch() -> str:
    bs = sorted(glob.glob(os.path.join(ROOT, "batch_*")), key=os.path.getmtime)
    return bs[-1] if bs else ""


def sheet(d: str) -> str:
    tiles = []
    for k, lab in CAMS:
        im = cv2.imread(os.path.join(d, k + "_ann.jpg"))
        if im is None:
            continue
        im = cv2.resize(im, (640, 480))
        cv2.rectangle(im, (0, 0), (639, 34), (0, 0, 0), -1)
        cv2.putText(im, lab, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (0, 255, 0), 2)
        tiles.append(im)
    if not tiles:
        return ""
    while len(tiles) < 6:
        tiles.append(np.zeros((480, 640, 3), np.uint8))
    rows = [np.hstack(tiles[i:i + 3]) for i in (0, 3)]
    body = np.vstack(rows)
    hdr = np.zeros((46, body.shape[1], 3), np.uint8)
    cv2.putText(hdr, "Z-MAX L5 auto-annotate  " + os.path.basename(d), (10, 32),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 2)
    cv2.imwrite(SHEET, np.vstack([hdr, body]), [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    return SHEET


def caption(s: dict) -> str:
    L = ["🤖 Z-MAX 自动标注 · 批次 %s · %d/%d 路成功 · %d 个物体 · 用时 %.0fs"
         % (s.get("batch"), s.get("ok"), s.get("n_cams"), s.get("n_objects"), s.get("elapsed_s") or 0)]
    for c in s.get("cams") or []:
        L.append("· %-12s %s (%s 个)" % (c["cam"], c.get("scene") or c.get("err") or "-", c.get("n_obj") or 0))
    L.append("")
    L.append("数据: ~/zmax_data/auto_annotate/ (每路 json 标注 + _ann.jpg 标注图; annotations.jsonl 追加式数据集)")
    L.append("口径: L5 视觉语言层按左上原点像素给框, 已映回原图; 只看清才框, 看不清不猜。")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--text-only", action="store_true")
    a = ap.parse_args()
    d = latest_batch()
    if not d:
        print("没有批次"); return 1
    name = os.path.basename(d)
    if not a.force and os.path.isfile(MARK) and open(MARK).read().strip() == name:
        print("最新批次 %s 已推过, 跳过(要强推加 --force)" % name); return 0
    s = json.load(open(os.path.join(d, "summary.json"), encoding="utf-8"))
    txt = caption(s)
    if a.text_only:
        r = P.send_text(txt)
    else:
        p = sheet(d)
        r = P.send_image(p, caption=txt) if p else P.send_text(txt)
    if r.get("ok"):
        open(MARK, "w").write(name)
    try:                                     # 给飞书端/HIL 人机在环留一份"一眼可读"的最新状态
        with open(os.path.join(ROOT, "LATEST.md"), "w", encoding="utf-8") as f:
            f.write("# Z-MAX 自动标注 · 最新一批\n\n```\n" + txt + "\n```\n")
    except Exception:                                       # noqa: BLE001
        pass
    print(json.dumps({k: r.get(k) for k in ("ok", "code", "msg", "image_key", "message_id")}, ensure_ascii=False))
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
