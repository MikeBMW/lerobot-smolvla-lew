#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ss_plan_show.py — 命令行看 MoveIt plan-only 镜像的当前状态 (与数据空间同一份真源)
────────────────────────────────────────────────────────────────────────────
给现场/审计用: 不开 GUI 也能核对 ss_plan 这一条到底在发什么。

  ① DDS 侧: zmax/ss_plan 的 hz/count/匹配发布者/帧龄/裁决/lamp (读 live.json)
  ② 规划侧: 最新一条规划的摘要 + 起/终点 + 同源闸判据 (读 ~/zmax_moveit_plan/live_plan_latest.json)
  ③ 链路健康: 容器 / 请求器 / 规划器 三个进程与文件新鲜度

用法:
  python3 tools/ss_plan_show.py            # 全部
  python3 tools/ss_plan_show.py --json     # 机器可读
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time

HOME = os.path.expanduser("~")
LIVE = "/home/ubuntu/zmax_data/dataspace/live.json"
PLAN_DIR = os.environ.get("SS_PLAN_DIR", os.path.join(HOME, "zmax_moveit_plan"))
LATEST = os.path.join(PLAN_DIR, "live_plan_latest.json")
JSONL = os.path.join(PLAN_DIR, "live_plan.jsonl")


def _age(p):
    return round(time.time() - os.path.getmtime(p), 2) if os.path.isfile(p) else None


def dds_side():
    try:
        d = json.load(open(LIVE, encoding="utf-8"))
        t = (d.get("topics") or {}).get("ss_plan") or {}
        return {k: t.get(k) for k in ("topic", "type", "qos", "hz", "hz_design", "count",
                                      "matched_pubs", "age_s", "verdict", "lamp", "lamp_reason")}
    except Exception as e:                                                   # noqa: BLE001
        return {"error": str(e)[:100]}


def plan_side():
    try:
        d = json.load(open(LATEST, encoding="utf-8"))
        jp, tp = d.get("joints_path") or [], d.get("tcp_path") or []
        return {"ts": d.get("ts"), "file_age_s": _age(LATEST),
                "n_points": d.get("n_points"), "plan_code": d.get("plan_code"),
                "plan_time_s": d.get("plan_time_s"), "end_err_mm": d.get("end_err_mm"),
                "fk_start_pos_err_mm": d.get("fk_start_pos_err_mm"),
                "gate_same_source": d.get("gate_same_source"),
                "gate_reason": d.get("gate_reason"), "frame_age_s": d.get("frame_age_s"),
                "start_joints": d.get("start_joints"), "goal_xyz": d.get("goal_xyz"),
                "joints_path_n": len(jp), "tcp_path_n": len(tp),
                "tcp_first": tp[:3], "tcp_last": tp[-3:] if tp else [],
                "note": d.get("note")}
    except Exception as e:                                                   # noqa: BLE001
        return {"error": str(e)[:100]}


def chain():
    def sh(c):
        try:
            return subprocess.run(["bash", "-lc", c], capture_output=True, text=True,
                                  timeout=20).stdout.strip()
        except Exception:                                                    # noqa: BLE001
            return ""
    return {"容器": sh("sudo docker ps --filter name=zmax-moveit --format '{{.Status}}'") or "未运行",
            "容器内规划器": "在跑" if sh("sudo docker exec zmax-moveit pgrep -f 'moveit_plan_live[.]py'") else "没跑",
            "请求器unit": sh("systemctl is-active zmax-moveit-plan-req.service") or "?",
            "plan_req年龄s": _age(os.path.join(PLAN_DIR, "plan_req.json")),
            "live_plan.jsonl行数": sum(1 for _ in open(JSONL, encoding="utf-8")) if os.path.isfile(JSONL) else 0,
            "ss守护": sh("systemctl is-active zmax-dds-ss.service"),
            "探针": sh("systemctl is-active zmax-dataspaces-probe.service")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    out = {"dds": dds_side(), "plan": plan_side(), "chain": chain()}
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    d, p, c = out["dds"], out["plan"], out["chain"]
    print("🧭 zmax/ss_plan —— MoveIt plan-only 轨迹镜像")
    print("  [DDS]  hz=%s(设计%s) count=%s 发布者=%s 帧龄=%ss 裁决=%s lamp=%s %s"
          % (d.get("hz"), d.get("hz_design"), d.get("count"), d.get("matched_pubs"),
             d.get("age_s"), d.get("verdict"), d.get("lamp"), d.get("lamp_reason", "")))
    if "error" in p:
        print("  [规划] 读不到: %s" % p["error"])
    else:
        _n = p.get("n_points")
        print("  [规划] %s 前 %ss 落盘 · plan_code=%s · 路点 n=%s"
              "(joints_path %s 个数 · tcp_path %s 个数) · 时长=%ss"
              % (time.strftime("%H:%M:%S", time.localtime(p["ts"])) if p.get("ts") else "?",
                 p.get("file_age_s"), p.get("plan_code"), _n,
                 p.get("joints_path_n"), p.get("tcp_path_n"), p.get("plan_time_s")))
        print("         终点误差=%smm · FK起点差=%smm" % (p.get("end_err_mm"), p.get("fk_start_pos_err_mm")))
        print("         目标=%s" % ([round(v, 5) for v in (p.get("goal_xyz") or [])]))
        print("         TCP 首=%s 末=%s" % ([round(v, 4) for v in p["tcp_first"]],
                                           [round(v, 4) for v in p["tcp_last"]]))
        g = p.get("gate_same_source")
        print("         同源闸=%s %s" % (g, "✅ 可贴真机画面" if g == 1 else
                                        ("❌ 不同源 → 只当设计态轨迹, 不许冒充真机"
                                         if g == 0 else "未判")))
        print("         判据: %s" % (p.get("gate_reason") or "")[:150])
    print("  [链路] " + " · ".join("%s=%s" % (k, v) for k, v in c.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
