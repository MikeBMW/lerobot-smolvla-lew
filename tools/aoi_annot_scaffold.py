#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aoi_annot_scaffold.py — 🎯 AOI 标注脚手架 (等 A2 授权即可现场采第一批, 全程只读)

老倪: 现场开发 AOI 视觉 (连工控机 + Orin), 我为主节点。
现状: data/yolo_aoi_annot/ 里 4 张 960×960 **boxes 全空** → 无法训质量检测头。

本脚本做三件事 (只读, 零动作下发):
  ① 从 10082 取一帧判决图 (POST /capture_detect, 只读触发), 存原图 + 时间戳
  ② 落一个**标注模板 JSON** (含图尺寸/来源/时间/空 boxes + 口径说明), 你在页面上框选后填 boxes
  ③ `--check` 校验已有标注 (boxes 是否合法/是否越界/框面积是否合理) 并统计可用样本数

用法:
  python3 tools/aoi_annot_scaffold.py --capture              # 取一帧 + 建标注模板
  python3 tools/aoi_annot_scaffold.py --capture --n 5        # 连取 5 帧
  python3 tools/aoi_annot_scaffold.py --check                # 校验现有标注可用性
  python3 tools/aoi_annot_scaffold.py --check --json         # 机器可读
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import ssl
import sys
import time
import urllib.request

ROOT = "/home/ubuntu/zmax_rel"
ANN = os.path.join(ROOT, "data/yolo_aoi_annot")
CAM = os.environ.get("ZMAX_AOI_CAM", "http://192.168.23.23:10082")     # 工控机金手指相机
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def _post(url, payload, timeout=30):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return json.loads(r.read().decode() or "{}")


def _get(url, timeout=15):
    with urllib.request.urlopen(url, timeout=timeout, context=CTX) as r:
        return json.loads(r.read().decode() or "{}")


def capture(n=1):
    os.makedirs(ANN, exist_ok=True)
    made = []
    for i in range(n):
        ts = time.strftime("%Y%m%d_%H%M%S")
        try:
            r = _post(CAM + "/capture_detect", {})
        except Exception as e:                                                # noqa: BLE001
            print("❌ 10082 /capture_detect 失败: %s: %s" % (type(e).__name__, str(e)[:120]))
            print("   (现场需要 A2 授权 + 工控机可达; 现在只做脚手架准备)")
            return made
        # 🎯 实测真路由 (2026-09-26): POST /capture_detect = 受理触发; 图走 GET /picture (全分辨率 PNG);
        #    判决走 GET /last_result (JSON: count/defects/detect_type/ms)
        img_path = os.path.join(ANN, "cap_%s_%d.png" % (ts, i))
        try:
            with urllib.request.urlopen(CAM + "/picture", timeout=60, context=CTX) as rr:
                data = rr.read()
            open(img_path, "wb").write(data)
        except Exception as e:                                                # noqa: BLE001
            print("   ⚠️ /picture 取图失败: %s" % str(e)[:80])
            img_path = ""
        try:
            with urllib.request.urlopen(CAM + "/last_result", timeout=30, context=CTX) as rr:
                r = json.loads(rr.read().decode() or "{}")
        except Exception:                                                     # noqa: BLE001
            pass
        stub = {
            "image": os.path.basename(img_path) if img_path else None,
            "ts": time.strftime("%F %T"),
            "source": CAM,
            "size": r.get("size") or "2448x2048 (相机原图; 训练同源口径 960×960 需按老倪口径裁减)",
            "verdict": {"count": r.get("count"), "defects": (r.get("defects") or [])[:5],
                        "detect_type": r.get("detect_type"), "ms": r.get("ms")},
            "boxes": [],                                  # ← 现场框选后填 [[x1,y1,x2,y2,cls], ...]
            "classes": ["gold_finger", "defect", "foreign"],   # 光模块金手指 / 缺陷 / 异物
            "caliber_note": "判据图口径: 手选框 > 原图自裁 > 拉长图 (老倪口径)",
            "status": "TODO_ANNOTATE",
        }
        sp = os.path.join(ANN, "cap_%s_%d.json" % (ts, i))
        json.dump(stub, open(sp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        made.append((img_path, sp))
        print("  ✅ 取样: %s (+ %s)" % (os.path.basename(img_path) if img_path else "-", os.path.basename(sp)))
        time.sleep(0.5)
    print("\n下一步: 打开这两个文件, 在 boxes 里填 [[x1,y1,x2,y2,'gold_finger'], ...] 并把 status 改成 DONE")
    print("校验: python3 tools/aoi_annot_scaffold.py --check")
    return made


def check(as_json=False):
    if not os.path.isdir(ANN):
        print("标注目录不存在: %s" % ANN)
        return 1
    rows, done, bad = [], 0, []
    for f in sorted(os.listdir(ANN)):
        if not f.endswith(".json"):
            continue
        try:
            d = json.load(open(os.path.join(ANN, f), encoding="utf-8"))
        except Exception as e:                                                # noqa: BLE001
            bad.append((f, "JSON 解析失败 %s" % str(e)[:40]))
            continue
        nb = len(d.get("boxes") or [])
        if nb:
            done += 1
        for j, b in enumerate(d.get("boxes") or []):
            if not (isinstance(b, (list, tuple)) and len(b) >= 5):
                bad.append((f, "box%d 格式应为 [x1,y1,x2,y2,cls]" % j))
            else:
                x1, y1, x2, y2 = b[:4]
                if not (x2 > x1 and y2 > y1):
                    bad.append((f, "box%d 坐标非法 (x2<=x1 or y2<=y1)" % j))
                w = x2 - x1
                h = y2 - y1
                if w > 960 or h > 960:
                    bad.append((f, "box%d 越界 %dx%d (>960)" % (j, w, h)))
                if w * h < 100:
                    bad.append((f, "box%d 面积过小 %d px² (<100)" % (j, w * h)))
        rows.append((f, nb, d.get("status")))
    out = {"dir": ANN, "files": len(rows), "annotated": done, "issues": bad[:20],
           "need_for_train": max(0, 20 - done), "rows": rows[:20]}
    if as_json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        print("📁 %s · 文件 %d · 已标注 %d · 待标注 %d" % (ANN, len(rows), done, len(rows) - done))
        if bad:
            print("⚠️ 问题 %d 条:" % len(bad))
            for f, m in bad[:10]:
                print("   %s: %s" % (f, m))
        else:
            print("✅ 标注格式全部合法")
        print("训练最少样本建议: 再补 %d 张带框样本 (当前已标注 %d)" % (out["need_for_train"], done))
    return 0


def from_origin(src_dir: str) -> int:
    """从**已落盘的 origin 真图**生成标注底图 (自裁口径 960×960) + 机器预框 —— 不真拍, 零打扰产线

    预框来源 = 自裁 meta 的**实测几何** (kept_rows + x_trim.x_span), 明确标注"机器预框, 需人工确认"
    """
    import glob as _glob
    import sys as _sys

    import cv2 as _cv
    import numpy as _np
    _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import aoi_exposure_fix as _FX
    files = sorted(_glob.glob(os.path.join(src_dir, "origin_*.png")))
    ok = 0
    print("🎯 从已落盘原图生成标注底图: %d 张 (自裁口径, 不真拍)" % len(files))
    for f in files:
        img = _cv.imread(f)
        if img is None:
            continue
        try:
            clean, meta = _FX.clean_judge_frame(img, out=960, return_natural=True)
        except Exception as e:                                                  # noqa: BLE001
            print("   ✗ %s: %s" % (os.path.basename(f), str(e)[:70]))
            continue
        if clean is None:
            print("   ✗ %s: 未找到合格条带 (如实跳过)" % os.path.basename(f))
            continue
        cimg = clean[0] if isinstance(clean, tuple) else clean
        base = os.path.splitext(os.path.basename(f))[0]
        ip = os.path.join(ANN, "anno_%s.png" % base)
        _cv.imwrite(ip, _np.asarray(cimg))
        kr = meta.get("kept_rows") or [None, None]
        xs = (meta.get("x_trim") or {}).get("x_span") or [None, None]
        cand = None
        if None not in (kr[0], xs[0]):
            cand = [int(xs[0]), int(kr[0]), int(xs[1]), int(kr[1])]
        stub = {
            "image": os.path.basename(ip), "ts": time.strftime("%F %T"), "from": os.path.relpath(f),
            "caliber": "原图自裁(切过曝带+死白列) → 960x960  (老倪口径第 2 档; 第 1 档=手动框选)",
            "facts": {"kept_rows": kr, "x_span": xs, "sat_before": meta.get("sat_before"),
                      "sat_after": meta.get("sat_after"), "dropped_sat_rows": meta.get("dropped_sat_rows"),
                      "dropped_pct": meta.get("dropped_pct"), "cliff": meta.get("cliff"),
                      "rule": meta.get("rule")},
            "candidate_box": cand,
            "candidate_note": "机器预框(由饱和≤0.4 + 边缘密集 + 高≥20行 实测导出) — **需人工确认或改框**; 若场景换料/换姿态须重跑",
            "candidate_box_origin_coords": True,
            "boxes": [], "classes": ["gold_finger", "defect", "foreign"],
            "status": "TODO_ANNOTATE",
        }
        json.dump(stub, open(os.path.join(ANN, "anno_%s.json" % base), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        ok += 1
        print("   ✅ %s  保留行 %s · 列 %s · 饱和 %.1f%%→%.1f%% · 预框 %s" %
              (os.path.basename(ip), kr, xs, (meta.get("sat_before") or 0) * 100,
               (meta.get("sat_after") or 0) * 100, cand))
    print("\n生成 %d 张标注底图 (含机器预框) → %s" % (ok, ANN))
    print("下一步: 打开 anno_*.png 目检/框选 → 把 boxes 填好, status 改 DONE → python3 tools/aoi_annot_scaffold.py --check")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--capture", action="store_true", help="从 10082 取帧 + 建标注模板 (只读)")
    ap.add_argument("--from-origin", dest="from_origin", default="",
                    help="从已落盘原图目录生成标注底图(自裁口径)+机器预框 (不真拍)")
    ap.add_argument("--n", type=int, default=1)
    ap.add_argument("--check", action="store_true", help="校验现有标注")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.from_origin:
        return from_origin(a.from_origin)
    if a.capture:
        print("🎯 AOI 标注脚手架 · 取帧 (源 %s, 只读)" % CAM)
        capture(a.n)
        return 0
    if a.check:
        return check(a.json)
    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
