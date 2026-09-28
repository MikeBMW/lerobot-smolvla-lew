#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
l2_dispatch_watch.py — **只读**镜像 L2 执行器的下发链(给现场调试用, 不碰执行器)
────────────────────────────────────────────────────────────
为什么需要: 画布/L5 路径不经过 arm_control.arm_controller.move_pose, 真机下发是
  `l2_cmd.fifo → tools/l2_daemon.py → ros2 service call /move_pose` —— 在**另一个常驻进程**里,
  断点打不进(VSCode 调试会话 ≠ 那个进程)。这里用**追日志**的只读方式把每次下发镜像出来:
     ~/zmax_data/l2_daemon.log  ──tail -F──►  reports/l2_dispatch.jsonl
  顺带把「DRY-RUN(未下发)」与真发分清, 并把技能名/服务名/目标位姿摘出来。
红线: 只读日志, 不写 FIFO、不碰 daemon 进程、不改任何判据。daemon 有 maybe_reload 热加载,
     直接改 l2_daemon.py 有现场风险 ⇒ 要镜像就用本工具。

用法: ./gui-venv311/bin/python tools/l2_dispatch_watch.py           # 前台跟
      ./gui-venv311/bin/python tools/l2_dispatch_watch.py --seconds 5400
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time

REPO = os.environ.get("ZMAX_REPO") or "/home/ubuntu/zmax_rel"
LOG = os.path.expanduser("~/zmax_data/l2_daemon.log")
OUT = os.path.join(REPO, "reports", "l2_dispatch.jsonl")

RE_TS = re.compile(r"^\[(\d{2}:\d{2}:\d{2})\]")
RE_SRV = re.compile(r"ros2 service call\s+(/[A-Za-z0-9_/]+)\s+([A-Za-z0-9_/]+)")
RE_SKILL = re.compile(r"\b(L2|L3|L4)\.[A-Za-z0-9_]+\b")
RE_NUM = re.compile(r"(p[xyz]|speed|position|target_pos|d_mm|deg)\s*[:=]\s*(-?\d+\.?\d*)")


# 现行日志格式(2026-09-29 实测): 不再出现 "ros2 service call" 字样, 而是
#   [06:57:47] 已下发 L2.backward -> 50.0 · Δ=(-50.0,+0.0,+0.0)mm →后退(-X)
#   [06:57:47] 受理: 已下发 / 受理: DRY-RUN(未下发)
#   [06:57:45] 🛡 VL 安全闸: 放行|否决|**已关闭** / VL 安全闸(快层)
#   [06:57:59] 🎯 已把本次动作告知 VL ... (等针对该动作的裁决, 上限 300s)
# ⇒ 只认旧字样会全瞎(实测 0 条), 这里把新旧格式都收进来。
RE_DISPATCH = re.compile(r"已下发\s+(L[234]\.\w+)\s*(?:->|第)?\s*([-\d.]*)")
RE_ACCEPT = re.compile(r"受理:\s*(已下发|DRY-RUN[^)]*\)?)")
RE_GATE = re.compile(r"🛡\s*VL 安全闸(?:\(快层\))?:?\s*(放行|否决|\*\*已关闭\*\*|已关闭)")
RE_PENDING = re.compile(r"等针对该动作的裁决|复用\s*\d+s 前\*?\*?同一动作")
RE_DELTA = re.compile(r"Δ=\(([-+\d.]+),([-+\d.]+),([-+\d.]+)\)mm")


def parse(line: str) -> dict | None:
    m_disp, m_acc, m_gate, m_pend = (RE_DISPATCH.search(line), RE_ACCEPT.search(line),
                                     RE_GATE.search(line), RE_PENDING.search(line))
    if not (m_disp or m_acc or m_gate or m_pend or "ros2 service call" in line):
        return None
    if "ros2 service call" not in line and not (m_disp or m_acc or m_gate or m_pend):
        return None
    m = RE_TS.match(line)
    t = m.group(1) if m else time.strftime("%H:%M:%S")
    srv = RE_SRV.search(line)
    skill = RE_SKILL.search(line)
    dry = ("DRY-RUN" in line) or ("未下发" in line)
    nums = {k: float(v) for k, v in RE_NUM.findall(line)}
    m_d = RE_DELTA.search(line)
    kind = ("dispatch" if m_disp else ("accept" if m_acc else
                                      ("verdict" if m_gate else ("pending" if m_pend else "call"))))
    return {"wall": t, "kind": kind, "dry": bool(dry),
            "skill": (m_disp.group(1) if m_disp else (skill.group(0) if skill else "")),
            "verdict": (m_gate.group(1) if m_gate else ""),
            "delta_mm": ([float(m_d.group(i)) for i in (1, 2, 3)] if m_d else None),
            "service": (srv.group(1) if srv else "?"),
            "iface": (srv.group(2) if srv else "?"),
            "nums": nums,
            "line": line.strip()[:400]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=LOG)
    ap.add_argument("--seconds", type=float, default=5400.0)
    ap.add_argument("--from-start", action="store_true", help="从日志开头读(默认只看新行)")
    a = ap.parse_args()

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    if not os.path.isfile(a.log):
        print("❌ 找不到 daemon 日志: %s (daemon 没跑过?)" % a.log)
        return 2
    f = open(a.log, encoding="utf-8", errors="replace")
    if not a.from_start:
        f.seek(0, os.SEEK_END)
    fout = open(OUT, "a", encoding="utf-8")
    print("镜像中(只读): %s → %s" % (a.log, OUT), flush=True)

    t0, n = time.time(), 0
    while time.time() - t0 < a.seconds:
        where = f.tell()
        line = f.readline()
        if not line:
            time.sleep(0.4)
            try:                                  # 日志可能被轮转/重建
                if os.path.getsize(a.log) < where:
                    f.close()
                    f = open(a.log, encoding="utf-8", errors="replace")
            except OSError:
                pass
            continue
        rec = parse(line)
        if rec:
            rec["at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fout.flush()
            n += 1
            print("[%s] %-8s %-14s %s%s" % (
                rec["wall"], rec["kind"], (rec["skill"] or rec["verdict"] or rec["service"]),
                ("Δ=%s" % rec["delta_mm"]) if rec["delta_mm"] else "",
                " (DRY)" if rec["dry"] else ""), flush=True)
    fout.close()
    f.close()
    print("镜像结束: 共 %d 条下发" % n, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
