#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""agent_all_stop.py — 我(Hermes)这边"能发指令/能吃资源"的进程一键全停。

用途(现场安全): 老倪说「要碰撞了注意」这类话时, 立刻 ①杀掉 L2 执行器(它是我唯一能下发运动指令的组件,
杀掉 ⇒ 我这边不可能有任何指令进来) ②杀掉我起的 GPU/CPU 重活(3DGS 训练等) 把资源让给安全层
(vl_safety_fast 本地 CV 快层 + 示教器) ③打印剩下的东西, 让"停到哪"可核。

⚠️ 不要用 `pkill -f tools/gs_train.py` —— 那会匹配到**执行这条命令的 shell 自己**(命令行里含同一串),
把自己 SIGTERM 掉、后面的步骤根本没跑。一律按 /proc/<pid>/cmdline 的 argv 精确匹配再 kill PID。

用法: python3 tools/agent_all_stop.py [--keep-capture]
      --keep-capture  保留 gs_capture 采集器(纯只读, 会把现场继续录下来当证据)
"""
from __future__ import annotations
import argparse, os, signal, sys, time

TARGETS = {
    "l2_daemon.py": "L2 执行器(唯一能下发运动指令的组件)",
    "gs_train.py": "3DGS 训练(吃 GPU, 挤占安全层)",
    "monitor_move.py": "只读监控(无害, 一并收掉)",
    "watch_retreat.py": "只读观察(无害, 一并收掉)",
}
ME = os.getpid()
PARENTS = set()
_p = os.getppid()
while _p and _p != 1:
    PARENTS.add(_p)
    try:
        with open("/proc/%d/stat" % _p) as f:
            _p = int(f.read().rsplit(") ", 1)[-1].split()[1])
    except Exception:
        break


def scan(argv_marker: str):
    hits = []
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        pid = int(d)
        if pid == ME or pid in PARENTS:
            continue
        try:
            with open("/proc/%d/cmdline" % pid, "rb") as f:
                argv = [x.decode("utf-8", "replace") for x in f.read().split(b"\0") if x]
        except Exception:
            continue
        if any(a.endswith(argv_marker) or a.endswith("tools/" + argv_marker) for a in argv[1:]):
            hits.append((pid, " ".join(argv)[:96]))
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep-capture", action="store_true")
    a = ap.parse_args()
    if a.keep_capture:
        TARGETS.pop("gs_capture.py", None)
    print("🛑 我这边全停 (pid=%d, 跳过自己和父进程链)" % ME)
    for marker, desc in TARGETS.items():
        hits = scan(marker)
        if not hits:
            print("  · %-18s 无在跑" % marker)
        for pid, cl in hits:
            try:
                os.kill(pid, signal.SIGTERM)
                print("  ✓ 已杀 %-18s pid=%-8d %s" % (marker, pid, cl))
            except Exception as e:
                print("  ✗ 杀失败 %-18s pid=%d: %s" % (marker, pid, e))
    time.sleep(2)
    leftovers = []
    for marker in list(TARGETS) + ["gs_capture.py"]:
        for pid, cl in scan(marker):
            leftovers.append((marker, pid, cl))
    print("  复查: %s" % ("干净, 以上目标都不在跑了" if not leftovers else "⚠️ 仍在跑: %s" % leftovers))
    return 0


if __name__ == "__main__":
    sys.exit(main())
