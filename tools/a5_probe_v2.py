#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""a5_probe_v2.py — 严谨探针: ①取图新鲜度(文件名变化) ②CLAHE 抗曝光归一 ③局部变化簇定位

上一轮的取证不足 (如实): 位姿1/2 是暗帧(std 34/饱和0), 我用 Canny(60,160) 判"无新边缘" → 暗部结构会被漏掉;
且没验证图像是不是**真新拍**(工控机 /picture 返回"最近一次保存"的图)。
本轮: 每次拍完读 /last_result.origin 文件名 → 变了才算新帧; 用 CLAHE 归一后做差, 找**局部变化簇**(臂的位置)。
用法: ./gui-venv311/bin/python tools/a5_probe_v2.py --amp 40
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request

import numpy as np
import cv2

R = "/home/ubuntu/zmax_rel"
sys.path.insert(0, os.path.join(R, "tools"))
import a5_handeye_collect as A5                                                   # noqa: E402

CAM = "http://192.168.23.23:10082"
OUT = os.path.join(R, "data/handeye")
os.makedirs(OUT, exist_ok=True)


def last_origin():
    try:
        with urllib.request.urlopen(CAM + "/last_result", timeout=15) as r:
            return json.loads(r.read().decode() or "{}").get("origin")
    except Exception:                                                             # noqa: BLE001
        return None


def grab(tag):
    """触发真拍 → 等新帧 → 取 origin 原图 (返回 (img, origin名, 是否新帧))"""
    before = last_origin()
    req = urllib.request.Request(CAM + "/capture_detect", data=b"{}",
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=90) as r:
        r.read()
    name = before
    for _ in range(12):                       # 最多等 24s 等新文件名出现
        time.sleep(2)
        now = last_origin()
        if now and now != before:
            name = now
            break
    with urllib.request.urlopen(CAM + "/picture?kind=origin", timeout=40) as r:
        img = cv2.imdecode(np.frombuffer(r.read(), np.uint8), cv2.IMREAD_COLOR)
    p = os.path.join(OUT, "v2_%s.png" % tag)
    if img is not None:
        cv2.imwrite(p, img)
    return img, name, (name != before)


def clahe_gray(img):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(g)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--amp", type=float, default=40.0, help="探针位移 mm (默认 40)")
    a = ap.parse_args()
    s0 = A5.state()
    print("═══ 三查 ═══ %s" % s0)
    if s0["operation"] != "idle":
        print("非 idle → 停"); return 1
    t0 = A5.tcp()
    print("起始 TCP = (%.6f, %.6f, %.6f)" % tuple(t0["p"]))
    imgs = {}
    for tag, dx in (("A", 0.0), ("B", a.amp)):
        if dx:
            A5.move_pose([t0["p"][0] + dx / 1000.0, t0["p"][1], t0["p"][2]], t0["q"], 30.0, A5.joints())
            A5.wait_idle()
            tt = A5.tcp()
            print("位姿B 实测 ΔTCP = (%.3f, %.3f, %.3f) mm" % tuple((tt["p"][i] - t0["p"][i]) * 1000 for i in range(3)))
        img, name, fresh = grab(tag)
        imgs[tag] = img
        print("  取图 %s: %s · 新帧=%s" % (tag, os.path.basename(name or "?"), "✅" if fresh else "❌(可能是旧图!)"))
    A5.move_pose(t0["p"], t0["q"], 30.0, A5.joints()); A5.wait_idle()
    print("  已回原位")

    if imgs["A"] is None or imgs["B"] is None:
        print("❌ 图片缺失, 无法比较"); return 1
    ga, gb = clahe_gray(imgs["A"]), clahe_gray(imgs["B"])
    print("\n═══ 亮度对照 (解释上一轮为何误判) ═══")
    for tag, g in (("A", ga), ("B", gb)):
        raw = cv2.cvtColor(imgs[tag], cv2.COLOR_BGR2GRAY)
        print("  %s: raw 均值%.1f std%.1f 饱和%.1f%% | CLAHE 后 std%.1f" %
              (tag, raw.mean(), raw.std(), (raw >= 250).mean() * 100, g.std()))
    d = np.abs(ga.astype(np.int16) - gb.astype(np.int16))
    thr = max(25, int(np.percentile(d, 99.5)))
    mask = (d >= thr).astype(np.uint8)
    # 形态学去噪 + 连通域 → 最大簇 = 运动/变化最集中的区域 (候选=臂)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    mask = cv2.dilate(mask, np.ones((9, 9), np.uint8), iterations=2)
    n_lab, lab, stats_, cent = cv2.connectedComponentsWithStats(mask, 8)
    clusters = []
    for i in range(1, n_lab):
        x, y, w, h, area = stats_[i]
        if area >= 800:
            clusters.append({"area": int(area), "bbox": [int(x), int(y), int(w), int(h)],
                             "centroid": [round(float(cent[i][0]), 1), round(float(cent[i][1]), 1)],
                             "pct_of_frame": round(area / mask.size * 100, 2)})
    clusters.sort(key=lambda c: -c["area"])
    print("\n═══ CLAHE 归一后差异簇 (阈值 d>=%d) ═══" % thr)
    print("  变化像素占比 %.2f%% · 连通簇(≥800px) %d 个" % (mask.mean() * 100, len(clusters)))
    for c in clusters[:4]:
        print("   面积%7d (%.2f%%) 质心(u,v)=%s bbox=%s" % (c["area"], c["pct_of_frame"], c["centroid"], c["bbox"]))
    # 存可视化: A|B|diff 热力图
    vis = np.hstack([cv2.resize(imgs["A"], (816, 683)), cv2.resize(imgs["B"], (816, 683)),
                     cv2.applyColorMap(cv2.resize(mask * 255, (816, 683)), cv2.COLORMAP_JET)])
    cv2.imwrite(os.path.join(OUT, "v2_compare.jpg"), vis)
    print("\n  可视化: data/handeye/v2_compare.jpg (左=A 中=B 右=差异热图)")
    ok = bool(clusters) and clusters[0]["pct_of_frame"] < 25
    print("  判读: %s" % ("✅ 变化**局部集中** ⇒ 臂在视野里且可追踪 (差异簇=臂的像)" if ok
                          else ("⚠️ 变化过于全局 (%.1f%%) ⇒ 仍是曝光/场景整体变化" % (mask.mean() * 100))))
    json.dump({"ts": time.strftime("%F %T"), "amp_mm": a.amp, "tcp0": t0, "clusters": clusters,
               "diff_pct": round(mask.mean() * 100, 2)},
              open(os.path.join(OUT, "v2_probe_%s.json" % time.strftime("%Y%m%d_%H%M%S")), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
