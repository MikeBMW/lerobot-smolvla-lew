#!/usr/bin/env python3
"""把"当前公网流地址"发布出去 —— 解决"隧道地址会变"这件事。

背景(2026-09-27): 老倪反馈"三个视频都一样、是静态图片"。
查下来: 源是活的(5 帧 md5 全不同), 三条确实是三个不同相机;
真正原因是**公网通道太窄** —— 叠加页刷一轮要 287KB(143KB/s), 而隧道只有 21~66KB/s。
调低档位后实测能连续动(w=240 q=45 fps=2 ≈ 29KB/s)。

但隧道地址**重启就变**(已换过 5 次), 烧进 APP 的地址迟早失效。
⇒ 本脚本把当前可用地址 POST 到 ECS 中继(web 有 ECS 权限, 读得到),
   web 侧页面/运维就能自动跟上, 不用每次问我。

策略: 只在"地址变了"或"距上次>30 分钟"时推 —— 不刷屏(ECS 上一天几百个小文件没意义)。
用法: python3 tools/publish_live_url.py [--force]
"""
import argparse
import datetime
import glob
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request

LOG = "/var/log/zmax-tunnel.log"
STATE = "/home/ubuntu/.zmax_live_url_state.json"
ECS = "https://datadrive.world/api/relay/upload"
HEARTBEAT_S = 30 * 60
# 给 web 的推荐档位(实测能过 21~66KB/s 隧道): 低码率三相机拼图
STREAM_TPL = "%s/wall.mjpg?k=%s&w=240&q=45&fps=2"
SNAP_TPL = "%s/wall.jpg?k=%s&w=560&q=72"
TOKEN = "zmax-live"


def current_url():
    """从隧道日志里取最新公网地址(倒序找第一个能用的)。"""
    try:
        txt = open(LOG, "r", errors="ignore").read()
    except OSError:
        return None
    urls = re.findall(r"https://[a-z0-9]+\.lhr\.life", txt)
    for u in reversed(urls[-6:]):
        if probe(u):
            return u
    return urls[-1] if urls else None


def probe(u, timeout=25):
    try:
        req = urllib.request.Request(u + "/wall.jpg?k=%s&w=240&q=45" % TOKEN)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status == 200 and r.read(2) == b"\xff\xd8"
    except Exception:                                                         # noqa: BLE001
        return False


def push(payload, timeout=25):
    data = json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request(ECS, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()[:200].decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, (e.read() or b"")[:200].decode("utf-8", "replace")
    except Exception as e:                                                    # noqa: BLE001
        return None, str(e)[:120]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="不管状态, 强制推一次")
    a = ap.parse_args()

    url = current_url()
    if not url:
        print("[live-url] 取不到当前隧道地址"); return 1
    ok = probe(url)
    print("[live-url] 当前地址 %s  可用=%s" % (url, ok))
    if not ok:
        print("[live-url] 地址不可用, 不发布(等隧道重连后再跑)"); return 1

    prev = {}
    if os.path.exists(STATE):
        try:
            prev = json.load(open(STATE))
        except Exception:                                                     # noqa: BLE001
            prev = {}
    changed = prev.get("url") != url
    stale = (time.time() - float(prev.get("ts", 0))) > HEARTBEAT_S
    if not (a.force or changed or stale):
        print("[live-url] 地址未变且未到心跳(30min), 不推(避免刷屏 ECS)"); return 0

    payload = {
        "kind": "zmax_live_url",
        "url": url,
        "stream": STREAM_TPL % (url, TOKEN),
        "snapshot": SNAP_TPL % (url, TOKEN),
        "token": TOKEN,
        "readonly": True,
        "note": "只读通道: GET 白名单放行; POST 一律 403;/gen 与真机控制永不放行",
        "source": "4060 工位机 (146.x 私网, 主动出网)",
        "changed": changed,
        "at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    st, body = push(payload)
    print("[live-url] 推 ECS: HTTP %s  %s" % (st, body))
    open("/home/ubuntu/zmax_rel/reports/web/live_url.json", "w").write(
        json.dumps(payload, ensure_ascii=False, indent=1))
    if st == 200:
        json.dump({"url": url, "ts": time.time()}, open(STATE, "w"))
        print("[live-url] ✓ 已发布(web 可从 ECS 中继读到当前地址)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
