#!/usr/bin/env python3
"""一次性验证: 把三相机拼图 POST 到 ECS, 看它落到哪、/api/snapshot/latest 会不会跟着变。

只发**一张**, 不做循环推(推送速率要和老倪/web 商量, ECS 流量是成本)。
用法: python3 tools/ecs_push_test.py [--file reports/web/wall_3cam_wide.jpg]
"""
import argparse
import hashlib
import json
import os
import urllib.error
import urllib.request

BASE = "https://datadrive.world"


def call(method, path, data=None, ctype=None, timeout=25):
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if ctype:
        req.add_header("Content-Type", ctype)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read() or b""
    except Exception as e:                                                   # noqa: BLE001
        return None, str(e).encode()


def brief(b, n=200):
    return b[:n].decode("utf-8", "replace").replace("\n", " ")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="reports/web/wall_3cam_wide.jpg")
    a = ap.parse_args()

    print("══ ① 推之前 ══")
    st, b = call("GET", "/api/packages")
    print("  /api/packages  HTTP %s  %s" % (st, brief(b)))
    st, b = call("GET", "/api/latest")
    print("  /api/latest    HTTP %s  %dB  %s" % (st, len(b), brief(b, 120)))
    st, snap0 = call("GET", "/api/snapshot/latest")
    m0 = hashlib.md5(snap0).hexdigest()
    print("  /api/snapshot/latest  HTTP %s  %dB  md5=%s" % (st, len(snap0), m0[:12]))

    data = open(a.file, "rb").read()
    print("\n══ ② POST 拼图 (%s, %.1fKB, image/jpeg) ══" % (a.file, len(data) / 1024))
    st, b = call("POST", "/api/relay/upload", data=data, ctype="image/jpeg")
    print("  HTTP %s → %s" % (st, brief(b)))

    print("\n══ ③ 推之后 ══")
    st, b = call("GET", "/api/packages")
    print("  /api/packages  HTTP %s  %s" % (st, brief(b)))
    st, b = call("GET", "/api/latest")
    is_img = b[:2] == b"\xff\xd8"
    print("  /api/latest    HTTP %s  %dB  %s%s" % (st, len(b),
          "★是 JPEG!" if is_img else "", "" if is_img else brief(b, 120)))
    st, snap1 = call("GET", "/api/snapshot/latest")
    m1 = hashlib.md5(snap1).hexdigest()
    print("  /api/snapshot/latest  HTTP %s  %dB  md5=%s  %s" % (
        st, len(snap1), m1[:12],
        "★变了 ⇒ 这条口能喂快照" if m1 != m0 else "没变 ⇒ 这张快照不由这个口喂"))
    if is_img:
        open("/tmp/ecs_latest_after.jpg", "wb").write(b)
        print("  (已存 /tmp/ecs_latest_after.jpg 供核对)")

    print("\n══ ④ 结论 ══")
    if m1 != m0:
        print("  这条通道可用: 推图会更新 /api/snapshot/latest ⇒ web 的页面直接用那个地址即可")
    elif is_img:
        print("  /api/latest 收到了图 ⇒ 让 web 的页面改读 /api/latest（或他们把该图写成快照文件）")
    else:
        print("  这个口只收'包'不收图, 也不喂快照 ⇒ 需要 web 侧加一个收 JPEG 的口"
              "(或告诉我快照文件在 ECS 上的路径)")


if __name__ == "__main__":
    main()
