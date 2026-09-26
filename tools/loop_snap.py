#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
循环动作 + 双相机同步抓拍
  动作: 上(+Z) → 后(-X) → 下(-Z) → 前(+X)  各 20mm · speed=19(≈1.9mm/s) · 10 圈 = 40 步
  抓拍: 每步稳定后，同一时刻取两路"最新帧"，记录各自采集时间 → 可核同步性
输出: /tmp/pairs/c{圈}_s{步}_{arm|lap}.jpg  +  /tmp/pairs/manifest.json
"""
import json
import os
import signal
import sys
import threading
import time
import urllib.request

import cv2
import numpy as np

BASE = "http://127.0.0.1:8791"
FIFO = os.path.expanduser("~/zmax_data/l2_cmd.fifo")
OUTDIR = "/tmp/pairs"
# argv[1] = 逗号分隔的技能序列(不带 L2. 前缀)；argv[2] = speed；argv[3] = 每步等待秒数
SEQ = (sys.argv[1].split(",") if len(sys.argv) > 1
       else ["lift", "backward", "lower", "forward"])
SPEED = int(sys.argv[2]) if len(sys.argv) > 2 else 19
STEP_WAIT = float(sys.argv[3]) if len(sys.argv) > 3 else 13.5
D_MM, CYCLES = 20, 10

STOP = {"v": False}
LATEST = {"arm": (None, 0.0), "lap": (None, 0.0)}
LOCK = threading.Lock()


def _sig(s, f):
    STOP["v"] = True


signal.signal(signal.SIGTERM, _sig)
signal.signal(signal.SIGINT, _sig)


URLS = {"arm": "/arm.mjpg", "lap": "/local.mjpg"}


def grab(name):
    url = BASE + URLS[name]
    while not STOP["v"]:
        try:
            r = urllib.request.urlopen(url, timeout=10)
            buf = b""
            while not STOP["v"]:
                ch = r.read(4096)
                if not ch:
                    break
                buf += ch
                a = buf.find(b"\xff\xd8")
                b = buf.find(b"\xff\xd9", a + 2)
                if a >= 0 and b > a:
                    jpg = buf[a:b + 2]
                    buf = buf[b + 2:]
                    arr = cv2.imdecode(np.frombuffer(jpg, "uint8"), cv2.IMREAD_COLOR)
                    if arr is not None:
                        with LOCK:
                            LATEST[name] = (arr, time.time())
        except Exception:
            time.sleep(0.2)


def send(skill):
    line = json.dumps({"skill": "L2." + skill, "d_mm": D_MM, "speed": SPEED})
    with open(FIFO, "w") as f:
        f.write(line + "\n")


def snap(tag):
    """同一时刻取两路最新帧。
    ⚠️ 手臂相机只有 1.83Hz(0.54s/帧) —— 直接取"最新帧"可能取到运动/收尾相位的画面
       (实测帧龄最大到 0.81s)，会让同位置的两次抓拍看起来差很多、被误判成"位置漂移"。
       所以先等手臂路来一个"新鲜帧"(帧龄 ≤ 0.25s，最多等 2s) 再取，两路才可比。
    """
    # 等手臂路出新鲜帧
    t_wait = time.time()
    while time.time() - t_wait < 2.0:
        with LOCK:
            a0, ta0 = LATEST["arm"]
        if a0 is not None and (time.time() - ta0) <= 0.25:
            break
        time.sleep(0.05)
    t = time.time()
    with LOCK:
        a, ta = LATEST["arm"]
        l, tl = LATEST["lap"]
    rec = {"tag": tag, "t": round(t, 3),
           "arm_age_at_snap": round(t - ta, 3), "lap_age_at_snap": round(t - tl, 3)}
    for nm, img, ts in (("arm", a, ta), ("lap", l, tl)):
        if img is None:
            rec[nm] = None
            continue
        p = os.path.join(OUTDIR, "%s_%s.jpg" % (tag, nm))
        cv2.imwrite(p, img, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
        rec[nm] = {"path": p, "capture_ts": round(ts, 3),
                   "age_s": round(t - ts, 3), "std": round(float(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).std()), 1)}
    return rec


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    for n in ("arm", "lap"):
        threading.Thread(target=grab, args=(n,), daemon=True).start()
    print("  等待两路就绪…")
    time.sleep(7)
    with LOCK:
        ok = LATEST["arm"][0] is not None, LATEST["lap"][0] is not None
    print("  手臂:%s 笔记本:%s" % ("在线" if ok[0] else "离线", "在线" if ok[1] else "离线"))

    man = []
    n = 0
    for c in range(1, CYCLES + 1):
        for s in SEQ:
            n += 1
            if STOP["v"]:
                break
            send(s)
            time.sleep(STEP_WAIT)      # 等运动完成 + 稳定
            tag = "c%02d_s%02d_%s" % (c, n, s)
            rec = snap(tag)
            man.append(rec)
            print("  %s  %s" % (tag, ("arm_std=%.1f age=%.2fs | lap_std=%.1f age=%.2fs" % (
                rec["arm"]["std"], rec["arm"]["age_s"], rec["lap"]["std"], rec["lap"]["age_s"]))
                if rec["arm"] and rec["lap"] else "缺帧"))
    json.dump(man, open(os.path.join(OUTDIR, "manifest.json"), "w"), ensure_ascii=False, indent=1)
    print("  ✅ %d 次抓拍 → %s" % (len(man), OUTDIR))
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
