#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""watch_plan_outcome.py — 盯执行器日志里"这一轮计划"的结局, 出结果就打印摘要。

为什么(2026-10-01): 下发前要过 VL 慢层(最长 300s) + 三段运动, 人在现场等不到实时反馈。
这个只读小脚本只干一件事: 从日志某个时间戳之后开始跟, 直到出现"已下发/被拦/到位/受理"的终态, 汇总。
不写 FIFO、不发任何指令。用法: python3 watch_plan_outcome.py [--since "08:18:11"] [--max-s 600]
"""
import argparse
import os
import re
import time

LOG = os.path.expanduser("~/zmax_data/l2_daemon.log")
ap = argparse.ArgumentParser()
ap.add_argument("--since", default=None, help="只看该时刻(日志里的 HH:MM:SS)之后的行; 默认=脚本启动时刻前 30s")
ap.add_argument("--max-s", type=float, default=600)
a = ap.parse_args()
since = a.since or time.strftime("%H:%M:%S", time.localtime(time.time() - 30))
t0 = time.time()
seen, out = set(), []
print("👀 跟日志(只读) since=%s · 最长 %.0fs" % (since, a.max_s), flush=True)
while time.time() - t0 < a.max_s:
    try:
        with open(LOG, encoding="utf-8", errors="replace") as f:
            for ln in f:
                m = re.match(r"\[(\d\d:\d\d:\d\d)\]", ln)
                if not m or m.group(1) < since or ln in seen:
                    continue
                seen.add(ln)
                s = ln.strip()
                if any(k in s for k in ("已下发 阶段", "到位 ·", "下发被拦", "VL 安全闸", "拒发", "受理:", "🛑", "✅ 阶段", "中止")):
                    out.append(s)
                    print("  " + s[:190], flush=True)
                    if "受理:" in s or "到位 ·" in s and "阶段 3" in s:
                        pass
    except Exception as e:                                        # noqa: BLE001
        print("  读日志失败:", e)
    # 终态判定: 出现"受理:"汇总行 且(里面有 被拦 / 或 三个阶段都到位)
    txt = "\n".join(out)
    if "受理: 🛑" in txt or txt.count("到位 ·") >= 3:
        print("\n── 终态 ──", flush=True)
        print("  被拦" if "受理: 🛑" in txt else "  三段到位 ✅", flush=True)
        break
    time.sleep(2)
else:
    print("\n(到时限仍未出现终态 —— 看日志尾部)", flush=True)
print("\n摘要:")
for s in out[-10:]:
    print("  " + s[:160])
