#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
录"同步"视频：左=手臂相机  右=笔记本相机  底部=动作状态条（与画面同源时钟）
用法: python record_sync.py <秒数> <输出mp4>
"""
import cv2
import json
import os
import signal
import sys
import threading
import time
import urllib.request

BASE = "http://127.0.0.1:8791"
STOP = {"v": False}
FRAMES = {"arm": (None, 0.0), "local": (None, 0.0)}
LOCK = threading.Lock()


def _on_sig(sig, frm):
    STOP["v"] = True


signal.signal(signal.SIGTERM, _on_sig)
signal.signal(signal.SIGINT, _on_sig)


def grab(name: str):
    """持续拉 MJPEG，解析出最新 JPEG 帧（服务端只推最新帧，天然低延迟）"""
    url = "%s/%s.mjpg" % (BASE, name)
    while not STOP["v"]:
        try:
            r = urllib.request.urlopen(url, timeout=10)
            buf = b""
            while not STOP["v"]:
                chunk = r.read(4096)
                if not chunk:
                    break
                buf += chunk
                a = buf.find(b"\xff\xd8")
                b = buf.find(b"\xff\xd9", a + 2)
                if a >= 0 and b > a:
                    jpg = buf[a:b + 2]
                    buf = buf[b + 2:]
                    arr = cv2.imdecode(__import__("numpy").frombuffer(jpg, "uint8"), cv2.IMREAD_COLOR)
                    if arr is not None:
                        with LOCK:
                            FRAMES[name] = (arr, time.time())
        except Exception:
            time.sleep(0.15)


def motion():
    try:
        with urllib.request.urlopen(BASE + "/motion", timeout=3) as r:
            return json.loads(r.read().decode())
    except Exception:
        return {}


def stats():
    try:
        with urllib.request.urlopen(BASE + "/stats", timeout=3) as r:
            return json.loads(r.read().decode())
    except Exception:
        return {}


def main():
    dur = float(sys.argv[1]) if len(sys.argv) > 1 else 150.0
    out = sys.argv[2] if len(sys.argv) > 2 else "/tmp/sync.mp4"
    out_raw = out.replace(".mp4", "_raw.mp4")

    for n in ("arm", "local"):
        threading.Thread(target=grab, args=(n,), daemon=True).start()
    time.sleep(6)   # 等两路都有帧

    W, H = 640, 480
    BAR = 74
    vw = cv2.VideoWriter(out_raw, cv2.VideoWriter_fourcc(*"mp4v"),
                         15.0, (W * 2, H + BAR))
    t0 = time.time()
    n = 0
    print("录制中 %.0fs → %s" % (dur, out_raw))
    while not STOP["v"] and time.time() - t0 < dur:
        with LOCK:
            a, ta = FRAMES["arm"]
            l, tl = FRAMES["local"]
        if a is None and l is None:
            time.sleep(0.05)
            continue
        now = time.time()
        L = cv2.resize(a, (W, H)) if a is not None else 0 * __import__("numpy").zeros((H, W, 3), "uint8")
        R = cv2.resize(l, (W, H)) if l is not None else 0 * __import__("numpy").zeros((H, W, 3), "uint8")
        cv2.rectangle(L, (0, 0), (W - 1, H - 1), (60, 60, 60), 1)
        cv2.rectangle(R, (0, 0), (W - 1, H - 1), (60, 60, 60), 1)

        m = motion()
        s = stats()
        bar = __import__("numpy").full((BAR, W * 2, 3), 18, "uint8")

        # 标题行
        cv2.putText(bar, "ARM (Orin eye-in-hand)  age %.2fs   %s" % (
            now - ta if ta else -1, "%.1ffps" % s.get("arm", {}).get("fps", 0)),
            (12, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (150, 220, 160), 1, cv2.LINE_AA)
        cv2.putText(bar, "LAPTOP (local drv)  age %.2fs   %s" % (
            now - tl if tl else -1, "%.1ffps" % s.get("local", {}).get("fps", 0)),
            (W + 12, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (150, 200, 240), 1, cv2.LINE_AA)

        # 动作行（核心：动作与画面同源时钟）
        if m.get("ok"):
            act = m.get("age_s", -1)
            live = 0 <= act < 20
            col = (120, 255, 120) if live else (150, 150, 150)
            cv2.circle(bar, (22, 50), 8, col, -1)
            cv2.putText(bar, "ACTION: %s   d=%smm   pos=%s    issued %.0fs ago%s" % (
                m.get("dir") or m.get("skill"), m.get("delta"), m.get("pos"), act,
                "  [RUNNING]" if live else ""),
                (40, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.58, col, 1, cv2.LINE_AA)
        else:
            cv2.putText(bar, "ACTION: (no data)", (40, 58),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.58, (150, 150, 150), 1, cv2.LINE_AA)

        cv2.putText(bar, time.strftime("%H:%M:%S"), (W * 2 - 130, 58),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1, cv2.LINE_AA)

        frame = __import__("numpy").vstack([__import__("numpy").hstack([L, R]), bar])
        vw.write(frame)
        n += 1
        time.sleep(max(0.0, 1 / 15.0 - (time.time() - now)))
    vw.release()
    print("  ✅ %d 帧 · %.1fs" % (n, n / 15.0))
    sys.stdout.flush()
    # 采集线程是 daemon 且卡在阻塞读里，正常退出会触发 C++ 线程析构崩溃 → 直接退
    os._exit(0)


if __name__ == "__main__":
    main()
