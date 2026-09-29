#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
moveit_plan_req.py — 给容器里的 MoveIt plan-only 喂「真机当前状态 + 目标」请求 (宿主机侧, 只读)
────────────────────────────────────────────────────────────────────────────
老倪 2026-09-29: 「起 plan-only 的 move_group 容器，把 /plan_kinematic_path 返回的关节轨迹
                 也镜像成 DDS 一条（ss_plan），能在独立窗口里逐帧对。」

链路:
  真机只读 tap  ~/zmax_ss_remote/state_*.jsonl  (jpos 6 关节 + tcp, 50Hz 真值)
        │  本脚本 (每 --interval 秒取最新一行)
        ▼
  ~/zmax_moveit_plan/plan_req.json   → 容器内 moveit_plan_live.py 逐轮规划
        ▼
  ~/zmax_moveit_plan/live_plan.jsonl → zmax-dds-ss 守护 → DDS topic zmax/ss_plan

安全: 只读真机 tap, 不连机械臂、不下发; 目标点来自示教点文件(data/skills/l2_atomic/taught_points.json)。

用法:
  python3 tools/moveit_plan_req.py --to slot7 --once          # 写一次请求
  python3 tools/moveit_plan_req.py --to slot7 --watch         # 常驻, 每秒刷新真机状态
  python3 tools/moveit_plan_req.py --goal-xyz 0.647 0.206 0.108 --goal-quat 0.738 0.020 0.674 0.0 --once
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time

HOME = os.path.expanduser("~")
SS_REMOTE = os.environ.get("SS_REMOTE_DIR", os.path.join(HOME, "zmax_ss_remote"))
PLAN_DIR = os.environ.get("SS_PLAN_DIR", os.path.join(HOME, "zmax_moveit_plan"))
REQ = os.path.join(PLAN_DIR, "plan_req.json")
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
TAUGHT = os.path.join(_REPO, "data", "skills", "l2_atomic", "taught_points.json")


def newest(pat):
    fs = glob.glob(pat)
    return max(fs, key=os.path.getmtime) if fs else None


def real_state():
    """真机最新一帧: jpos(6) / tcp(3) / tcp_quat(4) / t"""
    p = newest(os.path.join(SS_REMOTE, "state_*.jsonl"))
    if not p:
        return None
    try:
        with open(p, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 200_000))
            lines = f.read().decode("utf-8", "replace").splitlines()
        for ln in reversed(lines):
            ln = ln.strip()
            if not ln:
                continue
            try:
                d = json.loads(ln)
            except Exception:
                continue
            jp = d.get("jpos")
            if isinstance(jp, list) and len(jp) == 6:
                return {"jpos": [float(x) for x in jp],
                        "tcp": [float(x) for x in (d.get("tcp") or [])][:3],
                        "tcp_quat": [float(x) for x in (d.get("tcp_quat") or [])][:4],
                        "t": d.get("t"), "src_file": p}
    except Exception as e:                                                   # noqa: BLE001
        print("读真机 tap 失败: %s" % str(e)[:120])
    return None


def taught(name):
    try:
        d = json.load(open(TAUGHT, encoding="utf-8"))
        pt = (d.get("points") or {}).get(name)
        if not pt:
            return None
        q = [float(x) for x in pt["quat"]]
        if len(q) == 3:     # ⚠️ 示教点里 quat 存了 3 个数 = 第 4 位 w≈0 被省略 (实测 slot7 |q|≈0.9997)
            q = q + [0.0]   # ⇒ 补 w=0.0 (与 moveit_plan_only 旧跑法一致)
        return [float(x) for x in pt["pos"]], q
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", default="slot7", help="示教点名(默认 slot7)")
    ap.add_argument("--goal-xyz", nargs=3, type=float, default=None, help="直接给目标位置(m)")
    ap.add_argument("--goal-quat", nargs=4, type=float, default=None, help="目标姿态 xyzw")
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--watch", action="store_true", help="常驻, 每 interval 秒刷新真机状态")
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()

    if a.goal_xyz and a.goal_quat:
        goal, gq = [float(x) for x in a.goal_xyz], [float(x) for x in a.goal_quat]
        gname = "cli"
    else:
        t = taught(a.to)
        if not t:
            print("✗ 示教点不存在: %s (见 %s)" % (a.to, TAUGHT))
            return 2
        goal, gq = t
        gname = a.to
    os.makedirs(PLAN_DIR, exist_ok=True)
    print("🎯 目标 = 示教点 %s · xyz=%s quat=%s" % (gname, [round(v, 5) for v in goal],
                                                    [round(v, 5) for v in gq]))
    n = 0
    while True:
        st = real_state()
        if st:
            rec = {"ts": time.time(), "goal_name": gname, "goal_xyz": goal, "goal_quat": gq,
                   "jpos": st["jpos"], "tcp": st["tcp"], "tcp_quat": st["tcp_quat"],
                   "real_t": st.get("t"), "src": "real(tap readonly)"}
            tmp = REQ + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(rec, f, ensure_ascii=False)
            os.replace(tmp, REQ)
            n += 1
            if n == 1 or n % 10 == 0:
                print("· 已写 %s (#%d) 真机关节=%s tcp=%s" % (REQ, n,
                                                            [round(v, 3) for v in st["jpos"]],
                                                            [round(v, 3) for v in st["tcp"]]))
        else:
            print("… 真机 tap 无数据 (等 ~/zmax_ss_remote/state_*.jsonl)")
        if a.once:
            return 0 if st else 3
        time.sleep(max(0.2, a.interval))


if __name__ == "__main__":
    sys.exit(main())
