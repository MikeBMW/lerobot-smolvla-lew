#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_aoi_routes.py — 零副作用探路由 (只用 OPTIONS/HEAD, 绝不拍照/不触发检测)。

为什么: 老倪要「表面检测 10083 这一格有画面」。已知文档记录 10083 只有 POST /capture_detect,
但要在**不看工控机源码**的前提下把可能性穷举干净 —— OPTIONS 只看 Allow 头, 不会真拍照。

用法:
  python3 tools/probe_aoi_routes.py                 # 默认探 10083 + 10081
  python3 tools/probe_aoi_routes.py --ports 10081 10082 10083
"""
import argparse
import urllib.error
import urllib.request

HOST = "192.168.23.23"

CANDIDATES = [
    "/", "/index", "/health", "/status", "/info", "/api", "/routes",
    # 10082 同族命名
    "/picture", "/picture?kind=origin", "/crop_info", "/region", "/last_result",
    # 常见的取图/取流命名(别的写法)
    "/image", "/images", "/img", "/photo", "/photos", "/snapshot", "/snap", "/frame",
    "/frame.jpg", "/image.jpg", "/picture.jpg", "/capture", "/capture_image",
    "/get_picture", "/get_image", "/getimage", "/last_image", "/last_pic", "/show",
    "/view", "/preview", "/video", "/stream", "/stream.mjpg", "/mjpg", "/live", "/live.jpg",
    "/download", "/file", "/files", "/static", "/static/", "/surface_images", "/surface_images/",
    "/goldfinger_images", "/result", "/results", "/detect_result", "/last_detect",
    "/detect", "/detect_image", "/debug", "/logs", "/config", "/capture_detect",
]


def probe(port: int, path: str, timeout: float = 4.0):
    url = "http://%s:%d%s" % (HOST, port, path)
    req = urllib.request.Request(url, method="OPTIONS", headers={"User-Agent": "zmax-probe"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, (r.headers.get("Allow") or ""), len(r.read(64))
    except urllib.error.HTTPError as e:
        return e.code, (e.headers.get("Allow") or ""), 0
    except Exception as e:                                                        # noqa: BLE001
        return 0, str(e)[:60], 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ports", type=int, nargs="+", default=[10083, 10081, 10082])
    a = ap.parse_args()
    for port in a.ports:
        print("═══ :%d ═══" % port)
        hits = []
        for path in CANDIDATES:
            code, allow, _n = probe(port, path)
            if code and code < 500 and code != 404:
                hits.append((path, code, allow))
        if not hits:
            print("  (所有候选路径都 404 —— 该端口没有这些路由)")
        for path, code, allow in hits:
            print("  %-28s %s   Allow: %s" % (path, code, allow or "-"))
        print()


if __name__ == "__main__":
    main()
