#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔋 GPU 负载守护 —— 训练期间负载不得低于 50%

老倪 2026-09-25: "gpu训练负载不能小于一半"

做三件事:
  ① **采样**: 每 N 秒记录 GPU 利用率/显存/功耗 → 写 JSONL 供取证
  ② **判定**: 有训练在跑时若 util < 50% 连续 K 次 → 记违规 + 打印告警
  ③ **归因**: 同时记录「显存占用 / 进程数 / 是否在 step」→ 便于定位为何偏低
     （小数据量、层间切换空档、batch 太小、数据加载瓶颈）

用法:
  python3 tools/gpu_load_guard.py                 # 常驻采样（默认 5s）
  python3 tools/gpu_load_guard.py --once          # 采样一次
  python3 tools/gpu_load_guard.py --report        # 打印历史统计（min/avg/低于50%占比）
"""
import argparse
import json
import os
import subprocess
import sys
import time

OUT = "/home/ubuntu/stable-wm-cache/reports/gpu_load_samples.jsonl"
THRESHOLD = 50.0          # ★ 下限：50%
CONSEC = 3                # 连续 N 次低于阈值 → 记违规


def sh(c, t=6):
    try:
        return subprocess.run(c, shell=True, capture_output=True, text=True, timeout=t).stdout.strip()
    except Exception:                                                           # noqa: BLE001
        return ""


def sample():
    o = sh("nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw "
           "--format=csv,noheader,nounits")
    util = mem = tot = temp = pw = None
    if o and "," in o:
        p = [x.strip() for x in o.split(",")]
        try:
            util, mem, tot = int(p[0]), int(p[1]), int(p[2])
            temp = float(p[3]); pw = float(p[4])
        except Exception:                                                       # noqa: BLE001
            pass
    procs = sh("nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader")
    nproc = len([l for l in procs.splitlines() if l.strip()])
    train = bool(sh("pgrep -f 'lerobot_train|joint_train_all|yolo_annot_train|train_.*\\.py' | head -1"))
    return {"ts": time.time(), "t": time.strftime("%H:%M:%S"), "util": util, "mem_mb": mem,
            "mem_total_mb": tot, "temp_c": temp, "power_w": pw, "nproc": nproc,
            "training": train, "below": (util is not None and util < THRESHOLD)}


def report():
    if not os.path.isfile(OUT):
        print("  无采样数据")
        return
    us, below, tr_below = [], 0, 0
    with open(OUT, encoding="utf-8") as f:
        for ln in f:
            try:
                d = json.loads(ln)
            except Exception:                                                   # noqa: BLE001
                continue
            u = d.get("util")
            if u is None:
                continue
            us.append(u)
            if u < THRESHOLD:
                below += 1
                if d.get("training"):
                    tr_below += 1
    if not us:
        print("  无有效采样")
        return
    print("  采样 %d 次 | min %s%% | avg %.1f%% | max %s%% | 低于%s%%占比 %.1f%%"
          % (len(us), min(us), sum(us) / len(us), max(us), int(THRESHOLD), 100.0 * below / len(us)))
    print("  ⚠️ 训练期间低于阈值次数: %d" % tr_below)
    print("  判定: %s" % ("✅ 达标（训练期间负载始终 ≥50%）" if tr_below == 0 else
                       "❌ 未达标（训练期间有 %d 次 < 50%%）" % tr_below))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--interval", type=float, default=5.0)
    a = ap.parse_args()
    if a.report:
        report()
        return 0
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    if a.once:
        s = sample()
        print("  util=%s%% mem=%s/%sMB temp=%s proc=%s training=%s %s"
              % (s["util"], s["mem_mb"], s["mem_total_mb"], s["temp_c"], s["nproc"], s["training"],
                 "⚠️ 低于50%" if s["below"] else "✅"))
        return 0
    low = 0
    print("🔋 GPU 负载守护启动（阈值 %d%% · 每 %.0fs 采样 · 连续 %d 次告警）" % (THRESHOLD, a.interval, CONSEC))
    while True:
        s = sample()
        try:
            with open(OUT, "a", encoding="utf-8") as f:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")
        except Exception:                                                       # noqa: BLE001
            pass
        if s["below"]:
            low += 1
            flag = " ⚠️ 训练中却低于 %d%%!" % int(THRESHOLD) if s["training"] else ""
            if low >= CONSEC:
                print("[%s] 🔴 util=%s%% 连续 %d 次低于 %d%%%s (显存 %sMB · 进程 %d)"
                      % (s["t"], s["util"], low, int(THRESHOLD), flag, s["mem_mb"], s["nproc"]), flush=True)
            elif s["training"]:
                print("[%s] 🟡 util=%s%%%s" % (s["t"], s["util"], flag), flush=True)
        else:
            if low >= CONSEC:
                print("[%s] 🟢 恢复: util=%s%%" % (s["t"], s["util"]), flush=True)
            low = 0
        time.sleep(a.interval)


if __name__ == "__main__":
    raise SystemExit(main())
