#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🎯 L4 INTACT → L3 接入 · 三臂同口径对照 (老倪红线: 增加 L4 只能提升, 不能让 L2/L3 下降)。

三臂 (同 seed / 同 cap / 同步数, 逐臂子进程隔离 → 环境变量不串味):
  A off     : 不设 SS_L4_INTACT      = 现状 (解析伺服 + 状态机) —— 这是 L2/L3 的基线
  B shadow  : SS_L4_INTACT_SHADOW=1  = 真推理 + 真解码 + 真记录, **不接管** (零回退风险)
  C on      : SS_L4_INTACT=1         = 按解码器置信度 w 融合进 u_ff 槽位 (接管)

判据 (只看实测数字, 不吹):
  · 零回退: A 臂结果与"改动前引擎"一致; B 臂 success/dist 与 A 臂同数量级 (不接管 → 不该改变行为)
  · 真接入: B/C 臂 l4_stats.calls > 0 (真推理), C 臂 blend > 0 (真融合生效), frame_std_mean > 5 (真图)
  · 诚实: L3 条件通道未标定 → 报告里写"未标定", 不写"已条件化"

用法:
  INTACT_RUNTIME=root INTACT_POLICY=intact_goal_optical_insert_v4_s3072/weights_epoch_2.pt \\
    gui-venv311/bin/python tools/l4_intact_ab.py --seeds 0,1 --max-steps 700 --cap l4
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARM_RUNNER = os.path.join(ROOT, "tools", "l4_intact_arm.py")
ARMS = {"A_off": {}, "B_shadow": {"SS_L4_INTACT": "1", "SS_L4_INTACT_SHADOW": "1"},
        "C_on": {"SS_L4_INTACT": "1"}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="0,1")
    ap.add_argument("--max-steps", type=int, default=700)
    ap.add_argument("--cap", default="l4")
    ap.add_argument("--out", default=os.path.join(ROOT, "reports"))
    a = ap.parse_args()
    seeds = [int(x) for x in a.seeds.split(",") if x.strip()]
    out = {"ts": time.strftime("%F %T"), "seeds": seeds, "max_steps": a.max_steps,
           "cap": a.cap, "arms": {}, "env": {
               "INTACT_POLICY": os.environ.get("INTACT_POLICY"),
               "INTACT_RUNTIME": os.environ.get("INTACT_RUNTIME"),
               "INTACT_DEVICE": os.environ.get("INTACT_DEVICE")}}
    for arm, envx in ARMS.items():
        rows = []
        for sd in seeds:
            cmd = [sys.executable, ARM_RUNNER, "--seed", str(sd),
                   "--max-steps", str(a.max_steps), "--cap", a.cap]
            e = dict(os.environ, **envx)
            t0 = time.time()
            r = subprocess.run(cmd, cwd=ROOT, env=e, capture_output=True, text=True, timeout=5400)
            line = [ln for ln in (r.stdout or "").strip().splitlines() if ln.startswith("{")]
            try:
                d = json.loads(line[-1]) if line else {"err": (r.stderr or "")[-400:]}
            except Exception as ex:                                          # noqa: BLE001
                d = {"err": f"解析失败 {ex}: {(r.stdout or '')[-300:]}"}
            d["elapsed_s"] = round(time.time() - t0, 1)
            rows.append(d)
            print(f"  {arm} seed{sd}: done={d.get('done')} dist={d.get('dist_final')} "
                  f"steps={d.get('steps')} l4={d.get('l4', {}).get('calls')} "
                  f"({d['elapsed_s']}s)", flush=True)
        ok = [r for r in rows if isinstance(r.get("done"), bool)]
        out["arms"][arm] = {
            "success": sum(1 for r in ok if r["done"]), "n": len(rows),
            "dist_mean": (round(sum(r["dist_final"] for r in ok) / len(ok), 4) if ok else None),
            "l4_calls_mean": (round(sum((r.get("l4") or {}).get("calls", 0) for r in ok) / len(ok), 1)
                              if ok else None),
            "blend_mean": (round(sum((r.get("l4") or {}).get("blend", 0) for r in ok) / len(ok), 1)
                           if ok else None),
            "w": (ok[0].get("l4") or {}).get("w") if ok else None,
            "frame_std_mean": (ok[0].get("l4") or {}).get("frame_std_mean") if ok else None,
            "l3_cond_ready": (ok[0].get("l4") or {}).get("l3_cond_ready") if ok else None,
            "l3_cond_src": (ok[0].get("l4") or {}).get("l3_cond_src") if ok else None,
            "u_ff_src": (ok[0].get("l4") or {}).get("u_ff_src") if ok else None,
            "rows": rows}
    base = out["arms"]["A_off"]
    c = out["arms"]["C_on"]
    out["verdict"] = {
        "零回退(基线可用)": f"A_off success {base['success']}/{base['n']} · dist {base['dist_mean']}",
        "真接入(真推理真融合)": f"C_on calls {c['l4_calls_mean']} · blend {c['blend_mean']} · "
                              f"src={c['u_ff_src']}",
        "L3条件通道": ("已标定 → 注入" if c["l3_cond_ready"] else
                       "未标定 → 不注入 (拒绝 + 计数, 未写死映射)"),
        "是否提升": ("C 臂 success 高于 A 臂 → 有提升 (需配对复验: 同 seed 净胜 ≥2)"
                    if (c["success"] > base["success"]) else
                    "C 臂未超过 A 臂 → **无提升证据** (只证明接入通路真在跑)")}
    os.makedirs(a.out, exist_ok=True)
    p = os.path.join(a.out, f"l4_intact_ab_{time.strftime('%Y%m%d_%H%M%S')}.json")
    json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(out["arms"] and {k: {kk: vv for kk, vv in v.items() if kk != "rows"}
                                      for k, v in out["arms"].items()},
                     ensure_ascii=False, indent=1))
    print(json.dumps(out["verdict"], ensure_ascii=False, indent=1))
    print(f"→ {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
