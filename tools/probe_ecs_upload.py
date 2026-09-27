#!/usr/bin/env python3
"""探 ECS 上传口的语义（先只做无副作用探测，不盲发数据）。

问题: web 说通道可以是 `POST https://datadrive.world/api/relay/upload`,
但没说清字段格式 / 是否会覆盖他们单槽里的数据。先问出来:
  · OPTIONS 看允许的方法
  · GET     看它是不是也有读接口
  · 只发一个**几十字节的哨兵**试格式, 并立刻回读 /api/snapshot/latest 判断
    "是不是这个口喂那张图"(读回来若变成哨兵图 ⇒ 通道就是它)。

用法: python3 tools/probe_ecs_upload.py            # 只探测, 不发数据
      python3 tools/probe_ecs_upload.py --send     # 追加: 发一张哨兵图并回读验证
"""
import argparse
import hashlib
import io
import json
import sys
import urllib.error
import urllib.request

BASE = "https://datadrive.world"
UPLOAD = BASE + "/api/relay/upload"
SNAP = BASE + "/api/snapshot/latest"


def call(method, url, data=None, ctype=None, timeout=15):
    req = urllib.request.Request(url, data=data, method=method)
    if ctype:
        req.add_header("Content-Type", ctype)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            return r.status, dict(r.headers), body
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read()
    except Exception as e:                                                   # noqa: BLE001
        return None, {}, str(e).encode()


def show(tag, st, hdr, body):
    ct = hdr.get("Content-Type", "?")
    print("  %-28s HTTP %-5s %-28s %dB" % (tag, st, ct, len(body)))
    txt = body[:220].decode("utf-8", "replace").replace("\n", " ")
    if txt.strip():
        print("       %s" % txt)
    return body


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="真的发一张哨兵图并回读验证")
    a = ap.parse_args()

    print("══ ① 基线: 现在公网那张的指纹 ══")
    st, hdr, before = call("GET", SNAP)
    print("  /api/snapshot/latest  HTTP %s  %dB  md5=%s" % (st, len(before),
                                                             hashlib.md5(before).hexdigest()[:12]))

    print("══ ② OPTIONS /api/relay/upload（问它允许什么方法, 无副作用）══")
    st, hdr, body = call("OPTIONS", UPLOAD)
    show("OPTIONS", st, hdr, body)
    for k in ("allow", "Allow", "access-control-allow-methods"):
        if hdr.get(k):
            print("       允许方法: %s" % hdr[k])

    print("══ ③ GET /api/relay/upload（看有没有读接口 / 报错信息）══")
    st, hdr, body = call("GET", UPLOAD)
    show("GET", st, hdr, body)

    print("══ ④ POST 空体（看它要什么字段, 通常回 400 + 提示, 无副作用）══")
    st, hdr, body = call("POST", UPLOAD, data=b"", ctype="application/json")
    show("POST 空体", st, hdr, body)

    print("══ ⑤ POST 一个最小 JSON（探字段名）══")
    probe = json.dumps({"probe": 1, "from": "4060", "t": 0}).encode()
    st, hdr, body = call("POST", UPLOAD, data=probe, ctype="application/json")
    show("POST 最小 JSON", st, hdr, body)

    if not a.send:
        print("\n（未发数据。要真发一张哨兵图并回读验证: 加 --send）")
        return

    print("══ ⑥ 发一张 8x8 哨兵图（纯色, 一眼能认出是不是它喂了 /api/snapshot/latest）══")
    try:
        from PIL import Image
    except ImportError:
        print("   ✗ 需要 PIL"); sys.exit(1)
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (255, 0, 255)).save(buf, "JPEG", quality=90)
    jpg = buf.getvalue()
    for tag, data, ctype in [("原图直发", jpg, "image/jpeg"),
                             ("JSON+base64", json.dumps({"image": __import__("base64").b64encode(jpg).decode()}).encode(),
                              "application/json")]:
        st, hdr, body = call("POST", UPLOAD, data=data, ctype=ctype)
        show(tag, st, hdr, body)
        st2, _, after = call("GET", SNAP)
        same = hashlib.md5(after).hexdigest() == hashlib.md5(before).hexdigest()
        print("       回读 /api/snapshot/latest: %dB  与基线%s" % (len(after), "相同(没被这次POST改)" if same else "★不同(可能就是它)"))
        if not same:
            print("       ★★ 这个口就是喂图的通道（格式: %s）" % ctype)
            break


if __name__ == "__main__":
    main()
