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
        # 取回判决图 (base64 或 URL 两种形态都兼容)
        img_b64 = r.get("image_b64") or r.get("judge_b64") or ""
        img_path = ""
        if img_b64:
            img_path = os.path.join(ANN, "cap_%s_%d.png" % (ts, i))
            with open(img_path, "wb") as f:
                f.write(base64.b64decode(img_b64.split(",")[-1]))
        elif r.get("judge_url") or r.get("image_url"):
            url = r.get("judge_url") or r.get("image_url")
            img_path = os.path.join(ANN, "cap_%s_%d.png" % (ts, i))
            with urllib.request.urlopen(url, timeout=20, context=CTX) as rr, open(img_path, "wb") as f:
                f.write(rr.read())
        stub = {
            "image": os.path.basename(img_path) if img_path else None,
            "ts": time.strftime("%F %T"),
            "source": CAM,
            "size": r.get("size") or "960x960",          # 训练/推理同源口径 (老倪: topview 960×960)
            "verdict": r.get("verdict") or r.get("result") or None,
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--capture", action="store_true", help="从 10082 取帧 + 建标注模板 (只读)")
    ap.add_argument("--n", type=int, default=1)
    ap.add_argument("--check", action="store_true", help="校验现有标注")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
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
