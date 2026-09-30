#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_10083_deep.py — 10083 路由穷举(零副作用) + 常用 HTTP 口清点。

第一阶段: 对 10083 试一大批命名(只 OPTIONS), 看还有没有"能取图"的路由;
第二阶段: 把 .23.23 上像 HTTP 服务的端口挑出来(标准 web 口 + 10080~10100), 看有没有
          第三个能取表面相机图的服务。
"""
import socket
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HOST = "192.168.23.23"

PATHS = [
    "/api/picture", "/api/v1/picture", "/v1/picture", "/api/image", "/api/capture_detect",
    "/pic", "/pic.jpg", "/jpg", "/png", "/camera", "/camera/picture", "/cam", "/cam/picture",
    "/raw", "/origin", "/topview", "/natural", "/crop", "/crop.jpg", "/surface", "/surface.jpg",
    "/housing", "/last", "/latest", "/recent", "/current", "/now", "/get", "/read", "/show_image",
    "/image/last", "/images/last", "/result_image", "/image_result", "/detect/picture",
    "/capture_detect_image", "/capture_detect.jpg", "/detect.jpg", "/preview.jpg", "/view.jpg",
    "/live.mjpg", "/stream.jpg", "/video.jpg", "/snapshot.jpg", "/frame/png", "/grab", "/grab.jpg",
    "/photos/last", "/img/last", "/image?kind=origin", "/picture?kind=topview", "/meta", "/metrics",
    "/version", "/swagger", "/openapi.json", "/favicon.ico", "/robots.txt",
    # 中文/拼音命名(现场程序偶见)
    "/tupian", "/tuxiang", "/paizhao", "/jiance",
]

WEB_PORTS = [80, 81, 443, 1080, 3000, 3306, 5000, 5001, 5601, 7001, 7070, 8000, 8008, 8010,
             8043, 8080, 8081, 8088, 8090, 8443, 8888, 9000, 9001, 9090, 9200, 9443, 9999,
             10250, 2375, 2376, 10081, 10082, 10083, 10084, 10085, 10086, 10100]


def opt(port, path, timeout=3.5):
    url = "http://%s:%d%s" % (HOST, port, path)
    req = urllib.request.Request(url, method="OPTIONS", headers={"User-Agent": "zmax-probe"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, (r.headers.get("Allow") or "")
    except urllib.error.HTTPError as e:
        return e.code, (e.headers.get("Allow") or "")
    except Exception:                                                             # noqa: BLE001
        return 0, ""


def main():
    print("═══ ① 10083 深挖: 除 /capture_detect 之外还有没有能取图的路由 ═══")
    found = []
    with ThreadPoolExecutor(max_workers=12) as ex:
        for path, (st, allow) in zip(PATHS, ex.map(lambda p: opt(10083, p), PATHS)):
            if st and st != 404:
                found.append((path, st, allow))
    if not found:
        print("  ✗ 一个都没有 —— 10083 确实只有 POST /capture_detect")
    for path, st, allow in found:
        print("  %-30s %s Allow=%s" % (path, st, allow or "-"))

    print()
    print("═══ ② 这台工控机上还有没有别的 HTTP 服务(能取表面相机图) ═══")
    def up(p):
        s = socket.socket()
        s.settimeout(0.5)
        try:
            return p, s.connect_ex((HOST, p)) == 0
        finally:
            s.close()
    ports = []
    with ThreadPoolExecutor(max_workers=40) as ex:
        for p, ok in ex.map(up, WEB_PORTS):
            if ok:
                ports.append(p)
    if not ports:
        print("  常用口全闭")
    for p in sorted(ports):
        st, allow = opt(p, "/")
        st2, allow2 = opt(p, "/picture")
        print("  :%-6d OPTIONS / → %-4s Allow=%-18s | /picture → %-4s Allow=%s"
              % (p, st or "超时", allow or "-", st2 or "超时", allow2 or "-"))


if __name__ == "__main__":
    main()
