#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aoi_health.py — 产线 AOI (10082 金手指 / 10083 表面) 一条命令体检

现场把相机修好后, 直接跑这条就能判定"能不能看图/能不能检测", 不用逐个 curl 猜:
  gui-venv311/bin/python tools/aoi_health.py            # 只读接口 (不拍照)
  gui-venv311/bin/python tools/aoi_health.py --grab     # 含抓帧项 (会真拍/真 grab, 需现场同意)

判定口径 (2026-09-23 实测钉住):
  · 500 {"msg":"相机初始化失败"} → 工控机侧相机坏/被独占 → 抓帧类全废, 必须现场处理
  · 404 {"msg":"尚无照片: 先 POST /capture_detect 或 GET /picture?grab=1"} → 进程在但本轮没拍过照
  · 200 图 → 再看亮度: 暗画面(mean<60) 或 金覆盖=0 ⇒ 视野里没有金手指/没打光 (检测必然无目标)
"""
import argparse
import json
import subprocess
import sys
import tempfile

BASE_GOLD = "http://192.168.23.23:10082"
BASE_SURF = "http://192.168.23.23:10083"


def hit(url, method="GET", timeout=25, keep_full=False):
    tmp = tempfile.mktemp(suffix=".bin")
    r = subprocess.run(["curl", "-sS", "-X", method, "-o", tmp, "-w",
                        "%{http_code}|%{content_type}|%{size_download}|%{time_total}",
                        "--max-time", str(timeout), url], capture_output=True, text=True)
    code, ctype, size, t = ((r.stdout or "|||").strip().split("|") + ["", "", "", ""])[:4]
    body = b""
    try:
        with open(tmp, "rb") as f:
            body = f.read() if keep_full else f.read(400)
    except Exception:
        pass
    msg = ""
    if body[:1] == b"{":
        try:
            msg = str(json.loads(body.decode("utf-8", "ignore")).get("msg", ""))
        except Exception:
            msg = body.decode("utf-8", "ignore")[:80]
    return code, ctype, size, t, body, msg


def img_stats(path_or_body):
    try:
        import cv2
        import numpy as np
        arr = np.frombuffer(path_or_body, np.uint8)
        im = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
        if im is None:
            return None
        return im.shape, float(im.mean()), float(im.std())
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grab", action="store_true", help="含抓帧/拍照项 (会真拍, 需现场同意)")
    a = ap.parse_args()

    plan = [("①触发拍照检测  POST /capture_detect", "POST", BASE_GOLD + "/capture_detect", True),
            ("②实拍原图      GET  /picture?grab=1", "GET", BASE_GOLD + "/picture?grab=1", True),
            ("③拉长960       GET  /picture?kind=crop", "GET", BASE_GOLD + "/picture?kind=crop", False),
            ("④原比例        GET  /picture?kind=natural", "GET", BASE_GOLD + "/picture?kind=natural", False),
            ("⑤区域+对焦     GET  /region?grab=1", "GET", BASE_GOLD + "/region?grab=1", True),
            ("⑥裁剪质量指标  GET  /crop_info", "GET", BASE_GOLD + "/crop_info", False),
            ("⑦表面触发检测  POST :10083/capture_detect", "POST", BASE_SURF + "/capture_detect", True)]
    print("=" * 78)
    print("产线 AOI 体检 — 金手指 10082 / 表面 10083%s" % ("  (含抓帧项)" if a.grab else "  (只读, 不拍照)"))
    print("=" * 78)
    # ⓪ TCP 端口预检 (区分"程序没起/端口关了" vs "程序在但相机坏")
    import socket
    down = []
    for port, tag in ((10081, "10081 (第三套)"), (10082, "10082 金手指"), (10083, "10083 表面")):
        s = socket.socket()
        s.settimeout(3)
        try:
            s.connect(("192.168.23.23", port))
            print("  %-14s ✅ 端口在监听" % tag)
        except Exception as e:                                           # noqa: BLE001
            print("  %-14s ❌ %s (程序没在跑/端口关了)" % (tag, type(e).__name__))
            down.append(port)
        finally:
            s.close()
    if 10082 in down and 10083 in down:
        print("\n⇒ 金手指与表面**两套 AOI 程序都没在监听** → 先在 .23 上把程序启动起来, 再谈相机/图")
        print("=" * 78)
        return 1
    print("=" * 78)
    bad = 0
    for name, m, url, needs_grab in plan:
        if needs_grab and not a.grab:
            print("%-42s ⏭  需 --grab (会真拍)" % name)
            continue
        code, ctype, size, t, body, msg = hit(url, m, keep_full=True)
        verdict = "✅" if code == "200" else "❌"
        extra = ""
        if code == "200" and "image" in (ctype or ""):
            s = img_stats(body)
            if s:
                shape, mean, std = s
                extra = " | %s mean=%.1f std=%.1f" % (shape, mean, std)
                if mean < 60:
                    extra += " ⚠️偏暗(可能没打光/视野无料)"
        elif msg:
            extra = " | " + msg
            if "相机初始化失败" in msg:
                extra += "  → 该相机坏/被独占, 现场处理"
        if code != "200":
            bad += 1
        print("%-42s %s HTTP=%s %sB %.2fs%s" % (name, verdict, code, size, float(t or 0), extra))
    print("-" * 78)
    print("结论: " + ("✅ 看图链正常 — 可继续检测/伺服" if bad == 0 else
                     "❌ %d 项异常 — 先看上面的 msg; 相机类故障本机侧无解, 需在 .23 现场处理" % bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
