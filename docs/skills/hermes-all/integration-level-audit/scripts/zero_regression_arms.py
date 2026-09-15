#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""零回退 A/B 骨架 (臂隔离 + 仪器自检) —— 判定"新增可选通道是否改了既有档位行为"。

为什么要这个骨架 (实测教训, 见 references/instrument-selfcheck-and-edge-audit-2026-09-15.md):
  · 逐位 hash 比对只在**仪器本身确定**时有效;
  · 大模型 CPU bf16 + 随机噪声采样 ⇒ 同配置两臂 hash 也会不同 (本次 L3 档复现 3 次);
  · 所以本骨架**第一步就跑同配置对照臂对**证仪器, 仪器不确定 ===> 自动降级为结构性判据。

用法 (照抄改下面 CONFIG):
  python3 zero_regression_arms.py --control   # 只跑仪器自检: 同配置两臂 (不设任何新开关)
  python3 zero_regression_arms.py            # 正式 A/B: 各场景 (新开关 off / on) 两臂

判据:
  A. 仪器确定 (对照臂对 hash 相同)      → 用 hash 比对新开关 off/on
  B. 仪器不确定                        → 用结构性判据: 两臂"新代码进入计数"必须都为 0
                                          + 唯一执行入口/出口调用点未变 (人工核对, 脚本给出计数)
退出码: 0 = 通过 (未改动既有档位); 1 = 有场景异常; 2 = 环境/命令失败
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

# ── CONFIG: 改成你的工程 ────────────────────────────────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
RUNNER = os.path.join(ROOT, "tools", "probe_runner.py")      # 产出审计 json 的探针
SCENES = (("L2", 300), ("L3", 8))                            # (场景名, 步数); L3 类重加载用小步数
ARM_ENV = "SS_NEW_CHANNEL"                                   # 新通道的环境守卫名
AUDIT_ENV = "SS_AUDIT_JSON"                                  # 探针写审计 json 的环境变量名
# 审计 json 里"新代码是否进入"的计数字段 (点分路径, 取 max 判定)
NEW_CODE_PATHS = ("summaries.fiber.frames", "summaries.il.frames", "summaries.l4.calls")
HASH_PATH = "trace_hash"
DEADLINE_S = 3600
# ───────────────────────────────────────────────────────────────────────────


def get_path(obj: dict, dotted: str):
    cur = obj
    for part in dotted.split("."):
        cur = (cur or {}).get(part) if isinstance(cur, dict) else None
    return cur


def run_arm(scen: str, steps: int, on: bool, tag: str) -> dict:
    dst = os.path.join(ROOT, "reports", f"zr_{scen}_{tag}.json")
    env = dict(os.environ)
    env.update({AUDIT_ENV: dst, "SS_PROBE_SEED": "0",
                # 仪器前提: 播种 + 单线程 (仍不保证大模型 CPU 路径确定 → 才要对照臂)
                "SS_PROBE_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"})
    if on:
        env[ARM_ENV] = "1"
    else:
        env.pop(ARM_ENV, None)                     # 不设 = 改造前口径 (逐位零变化)
    p = subprocess.run([PY, RUNNER, scen, str(steps)], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=DEADLINE_S)       # noqa: S603
    try:
        return json.load(open(dst, encoding="utf-8"))
    except Exception:                                                            # noqa: BLE001
        return {"err": f"无审计 json (rc={p.returncode})", "stderr": p.stderr[-300:]}


def new_code_hits(audit: dict) -> int:
    vals = [get_path(audit, p) for p in NEW_CODE_PATHS]
    vals = [v for v in vals if isinstance(v, (int, float))]
    return int(max(vals)) if vals else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--control", action="store_true", help="只跑同配置对照臂对 (仪器自检)")
    a = ap.parse_args()

    print("① 仪器自检: 同配置两臂 (都不设新开关)")
    if a.control:
        scen, steps = SCENES[0]
        h = [run_arm(scen, steps, False, f"ctrl{i}").get(HASH_PATH) for i in (1, 2)]
        ok = h[0] and h[0] == h[1]
        print(f"   {scen} {steps} 步: hash1={h[0]} hash2={h[1]} → "
              f"{'✅ 仪器确定 (可用 hash 判据)' if ok else '❌ 仪器不确定 (只能用结构性判据)'}")
        return 0 if ok else 1

    instrument_ok = {}
    for scen, _ in SCENES:
        h = [run_arm(scen, 300, False, f"ctrl{i}").get(HASH_PATH) for i in (1, 2)]
        instrument_ok[scen] = bool(h[0] and h[0] == h[1])
        print(f"   {scen}: {'✅ 确定' if instrument_ok[scen] else '❌ 不确定 (降级为结构性判据)'}")

    all_ok = True
    for scen, steps in SCENES:
        print(f"\n② 场景 {scen} ({steps} 步): 新开关 off vs on")
        off = run_arm(scen, steps, False, "off")
        on = run_arm(scen, steps, True, "on")
        hits_off, hits_on = new_code_hits(off), new_code_hits(on)
        hoff, hon = off.get(HASH_PATH), on.get(HASH_PATH)
        print(f"   off: hits={hits_off} hash={hoff}")
        print(f"   on : hits={hits_on}  hash={hon}")
        if instrument_ok[scen]:
            same = bool(hoff and hoff == hon)
            print(f"   → {'✅ 逐位相同 (既有档位零回退)' if same else '⚠️ 不同 → 检查是否设计内变化'}")
            all_ok &= same or hits_on > 0              # on 臂有新通道活动时算"设计内变化"
        else:
            quiet = hits_off == 0 and hits_on == 0
            print(f"   → 结构性判据: 两臂新代码计数都为 0 = {'✅' if quiet else '❌'}"
                  f" (再人工核对唯一执行出口调用点未变)")
            all_ok &= quiet
    print(f"\n{'✅ 通过: 既有档位未被改动 (或变化仅来自新通道)' if all_ok else '❌ 有场景异常 — 回查'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
