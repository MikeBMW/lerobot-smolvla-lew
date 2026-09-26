#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""s2_excite_collect.py — S2 数据自激发: 慢速走激励轨迹 + 同步采 live tap (真机 (q,TCP) 有变动的配对)

为什么: 实测 live tap 窗口内 std=[0,0,0] ⇒ 臂静止 ⇒ 无激励就测不出 RealityGap。
本脚本: 我自主把臂走 N 个**小步激励**(speed=8 慢速) → 每步静止后读 (q, TCP) 真值 + tap 当前行
        → 产出**有变化**的真机数据集 (供 RealityGap 与口径映射用)
安全: 三查(power=on·automatic·关节静止) · 每轴 ≤3° · speed=8 · 结束回起始构型 · 全程真值
用法: ./gui-venv311/bin/python tools/s2_excite_collect.py --n 12
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

import numpy as np

R = "/home/ubuntu/zmax_rel"
sys.path.insert(0, os.path.join(R, "tools"))
from selfcal_kinematic import JN, ROSX, ORIN, move_joint, sdk, status, wait_idle         # noqa: E402

LIVE = "/home/ubuntu/zmax_ss_remote/state_20260925.jsonl"
OUTD = os.path.join(R, "data/selfcal")


def tap_last():
    """只读 live tap 最后一行 (不占产线)"""
    try:
        sz = os.path.getsize(LIVE)
        with open(LIVE, "rb") as f:
            f.seek(max(0, sz - 4096))
            txt = f.read().decode("utf-8", errors="ignore")
        for ln in reversed(txt.split("\n")):
            if ln.strip().startswith("{"):
                try:
                    return json.loads(ln)
                except Exception:                                                # noqa: BLE001
                    continue
    except Exception:                                                            # noqa: BLE001
        pass
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--amp", type=float, default=3.0, help="每轴激励幅度(deg)")
    a = ap.parse_args()
    os.makedirs(OUTD, exist_ok=True)
    s0 = status()
    power, mode = str(s0.get("powerState") or ""), str(s0.get("operateMode") or "")
    vel = s0.get("jointVel") or []
    print("═══ 三查 ═══ power=%s mode=%s 速度=%s" % (power, mode, [round(v, 4) for v in vel]))
    if "on" not in power.lower() or "automatic" not in mode.lower() or any(abs(v) > 1e-3 for v in vel):
        print("❌ 闸门不过 → 停（不下发任何动作）"); return 1
    print("✅ 闸门通过 · speed=8 慢速")
    q0 = np.array(s0.get("jointPos", [])[:6], dtype=float)
    tcp0 = (s0.get("endInRef") or [])[:3]
    print("起始 q(deg)=%s · TCP=%s\n" % (np.round(np.degrees(q0), 2).tolist(), [round(v, 4) for v in tcp0]))

    rng = np.random.default_rng(11)
    recs = []
    for i in range(a.n):
        tgt = q0 if i == 0 else q0 + np.radians(rng.uniform(-a.amp, a.amp, 6))
        if i:
            move_joint(tgt.tolist(), speed=8.0)
            if not wait_idle():
                print("  [%2d] 未静止, 跳过" % i); continue
            time.sleep(1.2)                       # 让 tap 落一帧新数据
        st = status()
        q = np.array(st.get("jointPos", [])[:6], dtype=float)
        tcp = np.array((st.get("endInRef") or [])[:3], dtype=float)
        t = tap_last() or {}
        tcp_tap = np.array(t.get("tcp", [])[:3], dtype=float) if t.get("tcp") else np.zeros(3)
        recs.append({"i": i, "q": q.tolist(), "tcp_m": tcp.tolist(), "tcp_tap": tcp_tap.tolist(),
                     "t_tap": t.get("t"), "stamp_tap": t.get("tcp_quat") is not None,
                     "gripper_tap": t.get("gripper"), "prod_stage": t.get("prod_stage")})
        print("  [%2d/%d] q(deg)=%s → TCP=(%.4f,%.4f,%.4f) · tap tcp 一致=%s"
              % (i, a.n, np.round(np.degrees(q), 2).tolist(), tcp[0], tcp[1], tcp[2],
                 bool(np.allclose(tcp, tcp_tap, atol=1e-3)) if tcp_tap.any() else "n/a"))
    print("\n回起始构型 (speed=8)...")
    move_joint(q0.tolist(), speed=8.0); wait_idle()

    tcp_all = np.array([r["tcp_m"] for r in recs])
    print("\n═══ 激励数据统计 ═══")
    print("  n=%d · TCP std = %s mm" % (len(recs), np.round(tcp_all.std(0) * 1000, 3).tolist()))
    print("  TCP 范围 = %s" % np.round((tcp_all.max(0) - tcp_all.min(0)) * 1000, 2).tolist(), "mm")
    has_g = sum(1 for r in recs if r["gripper_tap"] is not None)
    print("  tap 夹爪有效 = %d/%d · prod_stage 非空 = %d/%d"
          % (has_g, len(recs), sum(1 for r in recs if r["prod_stage"]), len(recs)))
    dst = os.path.join(OUTD, "excite_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    json.dump({"ts": time.strftime("%F %T"), "n": len(recs), "amp_deg": a.amp, "speed": 8.0,
               "tcp_std_mm": (tcp_all.std(0) * 1000).tolist(), "q0": q0.tolist(), "recs": recs},
              open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("  产物: %s" % dst)
    print("\n判读: %s" % ("✅ 已取得**有变动**的真机配对 → RealityGap/口径映射可测"
                          if tcp_all.std(0).max() * 1000 > 1.0 else
                          "⚠️ TCP 变化仍很小 (%.2fmm) → 加大激励幅度" % (tcp_all.std(0).max() * 1000)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
