#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📤 ECS 中转发布器 —— 把大包分片推到 relay, 并生成备份端的下载+重组指令

老倪 2026-09-23: "等晚上开启ECS服务器" — 大包(391MB)走 ECS 中转给备份端(小芳)

约束 (来自 http-relay-service 技能实测):
  · nginx `client_max_body_size 200m` → 单次 >200MB 会被 **413 拒收**
  · relay 在 ECS 上**无人监管**, 重启后 nginx+relay 会双死 → 先自检再传
  · 上传必须**流式**, 不能整块读进内存 (小内存 VPS 会 OOM 静默死)
用法:
  python tools/ecs_publish.py <文件> [--name <远端名>] [--part-mb 180] [--check]
  --check : 只做 ECS 可达性 + relay 健康自检, 不上传
"""
import argparse
import math
import os
import sys
import time

BASE = os.environ.get("ZMAX_RELAY", "https://datadrive.world/api/relay")


def http_get(url, timeout=15):
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read()[:400].decode("utf-8", "replace")
    except Exception as e:
        return 0, "%s: %s" % (type(e).__name__, str(e)[:120])


def post_stream(url, path, timeout=1200):
    """流式 POST (不整块读内存)"""
    import urllib.request
    sz = os.path.getsize(path)
    req = urllib.request.Request(url, data=None, method="POST")
    req.add_header("Content-Type", "application/octet-stream")
    req.add_header("Content-Length", str(sz))
    with open(path, "rb") as f:
        # urllib 需要可读对象; 用 file object 直接作为 data (带 Content-Length)
        req.data = f
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read()[:300].decode("utf-8", "replace")
        except Exception as e:
            return 0, "%s: %s" % (type(e).__name__, str(e)[:160])


def check():
    print("=" * 78)
    print("🔍 ECS / relay 自检 (技能 §9: 重启后 nginx+relay 常双死)")
    print("=" * 78)
    ok = True
    s, body = http_get("https://datadrive.world/")
    print("  ① 首页        : HTTP %s" % s)
    ok &= (s == 200)
    s2, body2 = http_get(BASE + "/status")
    print("  ② relay/status: HTTP %s  %s" % (s2, body2[:80].replace("\n", " ")))
    ok &= (s2 == 200)
    if not ok:
        print("\n  ⚠️ 未就绪 → ECS 上按顺序恢复 (见 tools/ecs_bringup.sh):")
        print("     · nginx: 宝塔主机要用 **/www/server/nginx/sbin/nginx**, 不是 systemd 的")
        print("     · relay: 项目目录里 `bash start.sh`")
        print("     · 再验: curl 127.0.0.1:39053/status → curl https://datadrive.world/api/relay/status")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file", nargs="?", default="")
    ap.add_argument("--name", default="")
    ap.add_argument("--part-mb", type=int, default=180, help="单片上限MB (nginx 限 200m)")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    if a.check or not a.file:
        return 0 if check() else 2
    if not os.path.isfile(a.file):
        print("❌ 文件不存在: %s" % a.file)
        return 1
    if not check():
        print("\n❌ relay 未就绪, 先恢复再传")
        return 2

    src = a.file
    name = a.name or os.path.basename(src)
    sz = os.path.getsize(src)
    P = a.part_mb * 1024 * 1024
    n = max(1, math.ceil(sz / P))
    print("\n📦 %s  %.1fMB → 分 %d 片 (片上限 %dMB)" % (name, sz / 1048576.0, n, a.part_mb))

    import hashlib
    urls = []
    for i in range(n):
        part = "/tmp/%s.part%02d" % (name.replace("/", "_"), i)
        with open(src, "rb") as fi, open(part, "wb") as fo:
            fi.seek(i * P)
            left = min(P, sz - i * P)
            while left > 0:
                b = fi.read(min(1 << 20, left))
                if not b:
                    break
                fo.write(b)
                left -= len(b)
        psz = os.path.getsize(part)
        t0 = time.time()
        st, body = post_stream("%s/upload" % BASE, part)
        print("   [%d/%d] %s (%.1fMB) → HTTP %s  %.1fs  %s"
              % (i + 1, n, os.path.basename(part), psz / 1048576.0, st, time.time() - t0, body[:60]))
        if st != 200:
            print("   ❌ 该片失败 → 检查 relay 日志 / 401·413·502")
            return 3
        urls.append("%s/latest" % BASE)
        os.remove(part)

    h = hashlib.sha256()
    with open(src, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    print("\n" + "=" * 78)
    print("✅ 上传完成 %d 片 · sha256=%s" % (n, h.hexdigest()[:16]))
    print("=" * 78)
    print("📩 发给备份端(小芳)的下载+重组指令:")
    print("```bash")
    print("cd ~/zmax_pull && mkdir -p parts && cd parts")
    for i in range(n):
        print("curl -sO %s/latest -o part%02d   # 注意: /latest 是**弹出式**, 按顺序取" % (BASE, i))
    print("cat part?? > %s" % name)
    print("shasum -a 256 %s   # 应为 %s..." % (name, h.hexdigest()[:16]))
    print("```")
    print("⚠️ relay /latest 是弹出式(queue pop) → **必须按上传顺序取, 且别重复取**")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
