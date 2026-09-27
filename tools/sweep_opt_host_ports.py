#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sweep_opt_host_ports.py — 把工控机 192.168.23.23 的 TCP 端口扫一遍(只 connect, 不发数据)。

目的: 老倪要「表面检测这一格有画面」。已知 10083 只有 POST /capture_detect(无取图路由),
那就要先证明**没有别的 HTTP 服务**能取表面相机图 —— 否则就是我漏了。
判据: 对每个开着且像 HTTP 的端口, 试几个取图路径的 OPTIONS(零副作用)。
"""
import socket
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HOST = "192.168.23.23"
PORTS = list(range(1, 65536))
TIMEOUT = 0.35


def is_open(port):
    s = socket.socket()
    s.settimeout(TIMEOUT)
    try:
        return port, (s.connect_ex((HOST, port)) == 0)
    finally:
        s.close()


def http_probe(port, path):
    url = "http://%s:%d%s" % (HOST, port, path)
    req = urllib.request.Request(url, method="OPTIONS",
                                headers={"User-Agent": "zmax-probe"})
    try:
        with urllib.request.urlopen(req, timeout=3.0) as r:
            return r.status, (r.headers.get("Allow") or ""), (r.headers.get("Server") or "")
    except urllib.error.HTTPError as e:
        return e.code, (e.headers.get("Allow") or ""), (e.headers.get("Server") or "")
    except Exception as e:                                                        # noqa: BLE001
        return 0, str(e)[:50], ""


def main():
    open_ports = []
    with ThreadPoolExecutor(max_workers=600) as ex:
        for port, ok in ex.map(is_open, PORTS):
            if ok:
                open_ports.append(port)
    open_ports.sort()
    print("开着的 TCP 端口 (%d 个): %s" % (len(open_ports), open_ports))
    for p in open_ports:
        first = http_probe(p, "/")
        print("  :%-6d OPTIONS / → %s  Allow=%s  Server=%s" % (p, first[0], first[1] or "-",
                                                               first[2] or "-"))
        for path in ("/picture", "/capture_detect", "/last_result"):
            st, allow, _s = http_probe(p, path)
            if st and st != 404:
                print("          %-18s → %s Allow=%s" % (path, st, allow or "-"))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
