#!/usr/bin/env python3
"""穿透前的安全闸门验收: 只读放行 / 一切控制类必须挡死。

用法: python3 tools/verify_tunnel_gate.py [--port 8891] [--token zmax-live]
"""
import argparse
import http.client
import json

CASES = [
    # (说明, 方法, 路径, 期望)
    ("叠加页(带口令)",        "GET",  "/overlay?k={k}",                 "200"),
    ("叠加页(不带口令)",      "GET",  "/overlay",                       "403"),
    ("叠加页(带 cookie)",     "GET",  "/overlay",                       "200", "zmaxk={k}"),
    ("场景契约",              "GET",  "/scene.json?k={k}",              "200"),
    ("运行统计",              "GET",  "/stats?k={k}",                   "200"),
    ("臂快照图",              "GET",  "/snapshot/arm.jpg?k={k}",        "200"),
    ("叠加快照图",            "GET",  "/snapshot/overlay_arm.jpg?k={k}", "200"),
    ("★ 真机动:授权闸",       "POST", "/ctl/arm?k={k}",                 "403"),
    ("★ 真机动:点动",         "POST", "/ctl/move?k={k}",                "403"),
    ("★ 触发拍照/大模型 /gen", "GET", "/gen?kind=vlm&k={k}",            "403"),
    ("★ 现场控制台 /station",  "GET",  "/station?k={k}",                "403"),
    ("★ 触发拍帧 /tap",       "GET",  "/tap?k={k}",                     "403"),
    ("★ ECS 中转 /api/relay", "POST", "/api/relay/upload?k={k}",        "403"),
    ("随手路径",              "GET",  "/etc/passwd?k={k}",              "403"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8891)
    ap.add_argument("--token", default="zmax-live")
    a = ap.parse_args()

    fails = []
    print("%-26s %-5s %-34s %-6s %-6s %s" % ("说明", "方法", "路径", "期望", "实测", "判定"))
    print("-" * 96)
    for case in CASES:
        desc, method, path, want = case[0], case[1], case[2], case[3]
        cookie = case[4].format(k=a.token) if len(case) > 4 else ""
        p = path.format(k=a.token)
        try:
            c = http.client.HTTPConnection("127.0.0.1", a.port, timeout=20)
            hdrs = {"Cookie": cookie} if cookie else {}
            c.request(method, p, headers=hdrs)
            r = c.getresponse()
            got, ct = str(r.status), (r.getheader("Content-Type") or "")
            body = r.read(64)
            c.close()
        except Exception as e:                                                # noqa: BLE001
            got, ct, body = "ERR", "", str(e).encode()
        ok = "✓" if got == want else "✗"
        if got != want:
            fails.append("%s %s 期望 %s 实测 %s" % (method, p, want, got))
        print("%-26s %-5s %-34s %-6s %-6s %s%s" % (
            desc, method, p[:34], want, got, ok,
            "  (%s)" % ct.split(";")[0] if got == "200" else ""))

    print("\n══ 结论 ══")
    if fails:
        print("  ✗ %d 条不符合:" % len(fails))
        for f in fails:
            print("    - %s" % f)
    else:
        print("  ✓ 全部符合: 只读放行, 控制/触发类全部挡死(带口令也挡)")


if __name__ == "__main__":
    main()
