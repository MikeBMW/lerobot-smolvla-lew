#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
live_pause_marker.py — 人拖/控制台移动机器人时, **自动识别"停顿点"**并落盘 + 叠到画面上
────────────────────────────────────────────────────────────
老倪 2026-09-29: 「中间我会停顿几个点，你可以参考」——
  不靠他喊"到了", 直接从 50Hz 真机数据判: TCP 速度连续 ≥ --hold 秒低于阈值 ⇒ 记一个参考点。
  落盘 reports/moveit/pause_points.jsonl(含 wall 时间 / 关节角 / TCP / 时长), 并把 P1..Pn 小盒
  merge 进 cameras.arm 的 trace 层(和人看的画面一一对应)。

跑法(宿主机即可, 它只读容器内录制的 jsonl 与 docker cp):
    gui-venv311/bin/python tools/live_pause_marker.py --loop --every 1.0
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
import scene_overlay as SO                                                      # noqa: E402
import live_trace_publisher as LTP                                              # noqa: E402

CONTAINER = os.environ.get("TRACE_CONTAINER", "ss-remote-tap")
IN_HEAD = os.environ.get("MOTION_HEAD", "/tmp/live_head.json")   # 滚动小文件(整份 jsonl 太大, 不适合每秒拷)
LOCAL = os.path.join(_REPO, "reports", "moveit", "live_head.json")
OUT = os.path.join(_REPO, "reports", "moveit", "pause_points.jsonl")
MARK_MM = 6.0        # 参考点小盒边长(mm) —— 只是"这个位置"的标记


def tail_records(n=120):
    """取容器内"最近 n 条"滚动小文件(/tmp/live_head.json)。"""
    os.makedirs(os.path.dirname(LOCAL), exist_ok=True)
    r = subprocess.run(["sudo", "docker", "cp", "%s:%s" % (CONTAINER, IN_HEAD), LOCAL],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        return []
    try:
        d = json.load(open(LOCAL, encoding="utf-8"))
    except Exception:                                                          # noqa: BLE001
        return []
    return list(d.get("head") or [])[-n:]


def speed(rec_a, rec_b):
    if not rec_a or not rec_b:
        return 0.0
    dt = max(1e-6, rec_b["t"] - rec_a["t"])
    return math.dist(rec_a["tcp"][:3], rec_b["tcp"][:3]) / dt


def load_marks():
    if not os.path.isfile(OUT):
        return []
    out = []
    for ln in open(OUT, encoding="utf-8"):
        ln = ln.strip()
        if ln:
            try:
                out.append(json.loads(ln))
            except Exception:                                                  # noqa: BLE001
                pass
    return out


def boxes_for_marks(marks):
    """把参考点画成小立方体(标签 P1..Pn, ASCII —— Hershey 画不出中文)。"""
    els = []
    for i, m in enumerate(marks, 1):
        x, y, z = m["tcp"][:3]
        h = MARK_MM / 2000.0
        c = [[x - h, y - h, z - h], [x + h, y - h, z - h], [x + h, y + h, z - h], [x - h, y + h, z - h],
             [x - h, y - h, z + h], [x + h, y - h, z + h], [x + h, y + h, z + h], [x - h, y + h, z + h]]
        els.append({"origin": "trace", "label": "P%d" % i, "kind": "3d", "corners3d": c,
                    "conf": 1.0, "no_label": False})
    return els


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--every", type=float, default=1.0)
    ap.add_argument("--hold", type=float, default=2.5, help="静止多少秒算停顿")
    ap.add_argument("--v-thresh", type=float, default=0.002, help="速度阈值(m/s)")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--seconds", type=float, default=5400)
    a = ap.parse_args()

    t0 = time.time()
    still_since, last_mark_t = None, 0.0
    while True:
        recs = tail_records()
        marks = load_marks()
        if len(recs) >= 3:
            v = max(speed(recs[-3], recs[-2]), speed(recs[-2], recs[-1]))
            now_t = recs[-1]["t"]
            if v < a.v_thresh:
                still_since = still_since or now_t
                held = now_t - still_since
                moved = True
                if marks:
                    moved = math.dist(recs[-1]["tcp"][:3], marks[-1]["tcp"][:3]) > 0.020   # ≥20mm 才算"新位置"
                if held >= a.hold and moved and (now_t - last_mark_t) > max(a.hold, 3.0):
                    last_mark_t = now_t
                    m = {"i": len(marks) + 1, "wall": recs[-1]["wall"], "t": now_t,
                         "held_s": round(held, 2), "tcp": recs[-1]["tcp"],
                         "joints": recs[-1]["js"]}
                    with open(OUT, "a", encoding="utf-8") as f:
                        f.write(json.dumps(m, ensure_ascii=False) + "\n")
                    marks.append(m)
                    print("[%s] ★ 参考点 P%d (静止 %.1fs) TCP=(%.4f, %.4f, %.4f)" % (
                        recs[-1]["wall"], m["i"], held, m["tcp"][0], m["tcp"][1], m["tcp"][2]), flush=True)
            else:
                still_since = None
        # 轨迹 + 参考点一起 publish(同一层)
        d = LTP.fetch()
        if d and d.get("pts"):
            pts = LTP.decimate(d["pts"], 2.0, 1500)
            els = [{"origin": "trace", "label": "实测轨迹(%d点)" % len(pts), "kind": "path3d",
                    "pts3d": pts, "width": 4, "no_label": True, "conf": 1.0}] + boxes_for_marks(marks)
            spec = SO.load_spec()
            SO.merge_origin(spec, "arm", "trace", els)
            SO.save_spec(spec)
        if not a.loop or time.time() - t0 > a.seconds:
            break
        time.sleep(a.every)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
