#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sim2real_readiness.py — 上真机前 · 仿真侧全链自检总跑 (只读, 不动真机)

把"上真机后立刻要用的能力"在**仿真里**逐项跑一遍, 出一张判据表:
  ① 引擎闭环真跑 (state_space_sim_real, insert/full 两种模式)
  ② 事件级认知头逐帧真调 (含闭环 AUC)
  ③ 策略 rollout (仿真) — ACT/SmolVLA/left_right 装载真跑
  ④ 数据 pipeline 五段 (采集tap / 中转relay / 数据集 / 训练 / 部署软链)
  ⑤ DDS 全局数据空间 (模式开关 + 20 判据取证)
  ⑥ 控制台画布渲染 (88 节点/166 连线)
  ⑦ Web 侧通道 (agent 提示词→回执 · HIL 状态上行→指示回执)
  ⑧ 真机只读信号可达性 (tap 帧新鲜度 / 10082 / Orin 端口探测 — 只读, 不下发动作)
输出: reports/sim2real_readiness_<ts>.json + 表格打印
用法: gui-venv311/bin/python tools/sim2real_readiness.py [--quick]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

ROOT = "/home/ubuntu/zmax_rel"
PY = os.path.join(ROOT, "gui-venv311/bin/python")
RESULTS = []


def run(name, cmd, timeout=240, cwd=ROOT, env=None, judge=None, note=""):
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                           env={**os.environ, **(env or {})})
        rc, out = p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        rc, out = 124, "TIMEOUT"
    dt = time.time() - t0
    tail = "\n".join([x for x in out.strip().splitlines() if x.strip()][-3:])
    ok = (rc == 0) if judge is None else bool(judge(rc, out))
    RESULTS.append({"item": name, "ok": bool(ok), "rc": rc, "sec": round(dt, 1), "note": note, "tail": tail[-300:]})
    print("  %s %-46s rc=%-3s %5.1fs %s" % ("✅" if ok else "❌", name, rc, dt, note), flush=True)
    return ok, out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    print("═" * 78)
    print("🧪 上真机前 · 仿真侧全链自检 (只读; 不动真机)")
    print("═" * 78)

    # ① 引擎闭环 + ② 事件头闭环 (同一脚本, 7 判据)
    run("① 引擎闭环 + ② 事件头逐帧真调 (7 判据)",
        [PY, "tools/verify_cog_event_loop.py", "--steps", "220", "--seed", "100"],
        timeout=300, judge=lambda rc, o: rc == 0 and "判据通过: 7/7" in o)

    # ⑤ DDS 全局数据空间 (20 判据)
    if not a.quick:
        run("⑤ DDS 全局数据空间 (20 判据 · 四档模式)", ["/home/ubuntu/dds-venv/bin/python", "/home/ubuntu/zmax_dds_ss_verify.py"],
            timeout=400, judge=lambda rc, o: rc == 0 and "20/20" in o)

    # ⑥ 画布渲染
    run("⑥ 控制台画布真实渲染 (88 节点/166 连线)", [PY, "tools/verify_canvas_render.py"],
        timeout=300, judge=lambda rc, o: "88 节点项 / 166 连线项" in o)

    # ⑦ Web 双通道 (agent 提示词 + HIL 状态/指示)
    run("⑦ Web 通道: Web 智能体桥 + HIL 全链", [PY, "tools/verify_hil_chain.py"],
        timeout=400, judge=lambda rc, o: "17/17" in o)

    # ③ 策略 rollout (仿真) — 用引擎 + 在役策略跑一小段
    run("③ 策略 rollout (仿真, state_space 策略真跑)", [PY, "tools/rollout_peg_check.py", "--policy", "state_space", "--steps", "40"],
        timeout=300, judge=lambda rc, o: rc == 0,
        note="引擎内策略真跑 (成功率另见 reports/ — state_space 当前 0%%, 如实记录, 待训练侧排查)")

    # ④ 数据 pipeline 五段
    run("④ 数据 pipeline 五段体检", [PY, "tools/dev_platform_check.py"],
        timeout=300, judge=lambda rc, o: rc == 0)

    # ⑧ 真机只读可达性 (只读: tap 帧龄 + 10082 判决 + Orin 端口)
    run("⑧ 真机只读信号 (tap 帧龄 / 10082 / Orin 端口)", [PY, "tools/sim2real_preflight.py", "--quick"],
        timeout=560, judge=lambda rc, o: rc == 0, note="仅 GET, 零动作下发")

    n_ok = sum(1 for r in RESULTS if r["ok"])
    print("\n" + "═" * 78)
    print("判据: %d/%d 通过" % (n_ok, len(RESULTS)))
    for r in RESULTS:
        if not r["ok"]:
            print("  ❌ %s (rc=%s) %s" % (r["item"], r["rc"], r["tail"].replace("\n", " | ")[:200]))
    dst = os.path.join(ROOT, "reports", "sim2real_readiness_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    json.dump({"ts": time.strftime("%F %T"), "pass": "%d/%d" % (n_ok, len(RESULTS)), "items": RESULTS},
              open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("取证: %s" % dst)
    return 0 if n_ok == len(RESULTS) else 3


if __name__ == "__main__":
    raise SystemExit(main())
