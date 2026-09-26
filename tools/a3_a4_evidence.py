#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""a3_a4_evidence.py — A3/A4 取证: 10083 缺口实证 + 10082 判据图口径对比 (真拍一帧, 老倪已授权 A1~A9)

A3 目标: 证明 "10083 表面相机缺 /picture" 的真实性 + 交接单可执行性 (工控机 SSH 关 → 只能现场粘补丁)
A4 目标: 在**同一张真图**上比三种口径, 用数字决定判据图口径:
        ① 工控机拉长图 ?kind=topview (工厂现用, 已知 73% 死白)
        ② 工控机原图 ?kind=origin
        ③ **4060 侧自裁** (tools/aoi_exposure_fix.clean_judge_frame)  ← 老倪口径: 手选框 > 原图自裁 > 拉长图
指标: 灰度均值/std · 饱和(≥250)占比 · 死白行数 · Tenengrad (细节能量)
用法: ./gui-venv311/bin/python tools/a3_a4_evidence.py [--grab]
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
import urllib.request

import numpy as np

R = "/home/ubuntu/zmax_rel"
sys.path.insert(0, os.path.join(R, "tools"))
CAM = "http://192.168.23.23:10082"
SUR = "http://192.168.23.23:10083"


def _get_img(url, timeout=30):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return np.frombuffer(r.read(), np.uint8)


def _decode(buf):
    import cv2
    return cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)


def stats(g, tag):
    if g is None:
        return {"口径": tag, "状态": "取不到"}
    sat = float((g >= 250).mean() * 100)
    deadrows = int((g >= 250).all(axis=1).sum()) if g.ndim == 2 else -1
    gx = np.abs(np.diff(g.astype(np.float32), axis=1)).mean() if g.ndim == 2 else 0
    gy = np.abs(np.diff(g.astype(np.float32), axis=0)).mean() if g.ndim == 2 else 0
    ten = float((gx ** 2 + gy ** 2).mean())
    return {"口径": tag, "尺寸": "%dx%d" % (g.shape[1], g.shape[0]), "均值": round(float(g.mean()), 1),
            "std": round(float(g.std()), 1), "饱和%": round(sat, 1), "死白行": deadrows,
            "Tenengrad": round(ten, 0)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--grab", action="store_true", help="真拍一帧 (A1~A9 已授权; 缺省复用最近一次)")
    a = ap.parse_args()
    out = {"ts": time.strftime("%F %T"), "a3": {}, "a4": []}

    print("═" * 78)
    print("A3 · 10083 表面相机缺口实证 (只读 OPTIONS 探路由, 零副作用)")
    print("═" * 78)
    for port, name in ((10082, "金手指"), (10083, "表面")):
        B = "http://192.168.23.23:%d" % port
        row = {}
        for path in ("/capture_detect", "/picture", "/crop_info", "/region", "/last_result"):
            try:
                req = urllib.request.Request(B + path, method="OPTIONS")
                with urllib.request.urlopen(req, timeout=10) as r:
                    allow = r.headers.get("Allow", "")
                row[path] = "存在 (%s)" % allow
            except Exception as e:                                              # noqa: BLE001
                code = getattr(e, "code", None)
                row[path] = "无路由 (HTTP %s)" % code if code in (404, 405) else type(e).__name__
        out["a3"][name] = row
        print("  %s :10083" % name if port == 10083 else "  %s :10082" % name)
        for k, v in row.items():
            print("     %-16s %s" % (k, v))
    patch = os.path.join(R, "docs/patch/opt_surface_10083_add_picture_route.md")
    has_patch = os.path.isfile(patch)
    out["a3"]["交接单"] = {"文件": os.path.relpath(patch, R) if has_patch else None, "存在": has_patch,
                          "行数": len(open(patch, encoding="utf-8").read().splitlines()) if has_patch else 0,
                          "工控机可达性": "SSH/RDP/VNC 全关 (技能记载 + 实测), 只有 HTTP 口 → 只能现场粘贴"}
    print("  交接单: %s (%s 行) · 工控机 SSH/RDP/VNC 全关 → **只能现场粘补丁**" %
          ("存在" if has_patch else "缺失", out["a3"]["交接单"]["行数"]))

    print("\n" + "═" * 78)
    print("A4 · 同一张真图的三种判据图口径对比%s" % (" (真拍)" if a.grab else " (复用最近)"))
    print("═" * 78)
    if a.grab:
        try:
            req = urllib.request.Request(CAM + "/capture_detect", data=b"{}",
                                         headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=90) as r:
                print("  真拍: HTTP %s %s" % (r.status, r.read()[:60].decode("utf-8", "ignore")))
            time.sleep(6)                       # 等后台 worker 出判决/裁减
        except Exception as e:                                                  # noqa: BLE001
            print("  ❌ 拍照失败: %s" % str(e)[:120])
            return 1
    rows = []
    for kind, tag in (("topview", "① 工控机拉长图 (工厂现用)"), ("origin", "② 工控机原图")):
        try:
            g = _decode(_get_img(CAM + "/picture?kind=" + kind))
            rows.append(stats(g, tag))
        except Exception as e:                                                  # noqa: BLE001
            rows.append({"口径": tag, "状态": "取不到: %s" % str(e)[:60]})
    # ③ 4060 侧自裁
    try:
        g_ori = _decode(_get_img(CAM + "/picture?kind=origin"))
        import aoi_exposure_fix as FX
        fn = getattr(FX, "clean_judge_frame", None)
        if fn is None:
            rows.append({"口径": "③ 4060 侧自裁", "状态": "aoi_exposure_fix 无 clean_judge_frame"})
        else:
            g_fix = fn(g_ori)
            if isinstance(g_fix, tuple):
                g_fix = g_fix[0]
            rows.append(stats(np.asarray(g_fix), "③ 4060 侧自裁 (老倪口径)")
                        if isinstance(g_fix, np.ndarray) else {"口径": "③ 4060 侧自裁", "状态": "返回非图像"})
    except Exception as e:                                                      # noqa: BLE001
        rows.append({"口径": "③ 4060 侧自裁", "状态": "%s: %s" % (type(e).__name__, str(e)[:60])})
    out["a4"] = rows
    print("  %-26s %-11s %6s %6s %7s %6s %10s" % ("口径", "尺寸", "均值", "std", "饱和%", "死白行", "Tenengrad"))
    for r_ in rows:
        if "状态" in r_:
            print("  %-26s %s" % (r_["口径"], r_["状态"]))
        else:
            print("  %-26s %-11s %6s %6s %7s %6s %10s" % (r_["口径"], r_["尺寸"], r_["均值"], r_["std"],
                                                          r_["饱和%"], r_["死白行"], r_["Tenengrad"]))
    dst = os.path.join(R, "reports", "a3_a4_evidence_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    json.dump(out, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n取证: %s" % dst)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
