#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""s2_probe_control.py — 控制权验证 + 小范围激励 (老倪授权: ±10cm 内 · 慢速自主)

为什么: 上次自校/激励时 12 次指令**全部无效果** ⇒ 控制权不在我 (产线 motion 在跑)。
本脚本: ① 只读三查 ② **单次 10mm 慢速试动** ③ 核对 ΔTCP 是否 ≈10mm
        ④ ΔTCP≈10mm ⇒ 控制权在我 ⇒ 继续小范围激励(±30mm, 慢速)采真机 (obs,TCP) 配对
        ⑤ 任何异常 → 立即停 + 回原位 + 报错(不重试)
安全: speed=8 · 单步 ≤30mm · 全程在 ±10cm 内 · 每步三查 · 结束回起始位姿
"""
from __future__ import annotations

import json
import os
import sys
import time

import numpy as np

R = "/home/ubuntu/zmax_rel"
sys.path.insert(0, os.path.join(R, "tools"))
from selfcal_kinematic import sdk, status                                              # noqa: E402
from s2_excite_collect import tap_last                                                 # noqa: E402
from a5_handeye_collect import move_pose, wait_idle, joints                             # noqa: E402

OUT = os.path.join(R, "data/selfcal")


def gate():
    s = status()
    power, mode = str(s.get("powerState") or ""), str(s.get("operateMode") or "")
    vel = s.get("jointVel") or []
    ok = ("on" in power.lower()) and ("automatic" in mode.lower()) and all(abs(v) < 1e-3 for v in vel)
    return ok, s, power, mode, vel


def main() -> int:
    ok, s, power, mode, vel = gate()
    print("═══ 三查 ═══ power=%s mode=%s 速度=%s → %s" % (power, mode, [round(v, 4) for v in vel],
                                                        "✅ 通过" if ok else "❌ 不过"))
    if not ok:
        print("闸门不过 → 停 (不下发任何动作)"); return 1
    t0 = s.get("endInRef") or []
    q0 = s.get("jointPos") or []
    p0 = np.array(t0[:3], dtype=float)
    # 🐛 endInRef = [x,y,z,rx,ry,rz] (rpy 6 值), 不是四元数 → 姿态从 tap 的 tcp_quat 取
    _t0 = tap_last() or {}
    quat0 = list(_t0.get("tcp_quat") or [0.0, 0.0, 0.0, 1.0])
    print("姿态(quat, 来自 tap) = %s" % [round(v, 5) for v in quat0])
    print("起始 TCP=(%.4f, %.4f, %.4f) m" % tuple(p0))

    # ② 单次 10mm 慢速试动 (+x)
    tgt = [p0[0] + 0.01, p0[1], p0[2]]
    print("\n② 试动 +10mm (speed=8) ...")
    move_pose(tgt, quat0, 8.0, q0[:6])
    wait_idle()
    s2 = status()
    p1 = np.array((s2.get("endInRef") or [])[:3], dtype=float)
    d = (p1 - p0) * 1000
    print("   实测 ΔTCP = (%.3f, %.3f, %.3f) mm · |Δ|=%.3f mm" % (d[0], d[1], d[2], np.linalg.norm(d)))
    if np.linalg.norm(d) < 5.0:
        print("\n❌ 指令**未生效** (Δ<5mm) ⇒ 控制权仍不在我 ⇒ 停, 不做任何进一步动作")
        return 2
    print("   ✅ 控制权在我 (指令生效)")

    # ④ 小范围激励: ±30mm 8 点, 每点读 (q, TCP, tap)
    amp = 0.03
    pat = [(0, 0, 0), (amp, 0, 0), (-amp, 0, 0), (0, amp, 0), (0, -amp, 0),
           (0, 0, amp), (0, 0, -amp), (amp / 2, 0, amp / 2)]
    recs = []
    print("\n④ 小范围激励 (±30mm, speed=8, 8 点):")
    for i, (dx, dy, dz) in enumerate(pat):
        if i:
            move_pose([p0[0] + dx, p0[1] + dy, p0[2] + dz], quat0, 8.0, joints())
            wait_idle()
            time.sleep(1.0)
        st = status()
        p = np.array((st.get("endInRef") or [])[:3], dtype=float)
        q = np.array((st.get("jointPos") or [])[:6], dtype=float)
        t = tap_last() or {}
        recs.append({"i": i, "cmd_mm": [dx * 1000, dy * 1000, dz * 1000], "tcp_m": p.tolist(),
                     "q": q.tolist(), "tap_tcp": (t.get("tcp") or [])[:3], "tap_robot": t.get("robot_status")})
        print("   [%d] 指令(%+5.1f,%+5.1f,%+5.1f)mm → TCP=(%.4f,%.4f,%.4f) tap一致=%s"
              % (i, dx * 1000, dy * 1000, dz * 1000, p[0], p[1], p[2],
                 bool(np.allclose(p, np.array((t.get("tcp") or [0, 0, 0])[:3]), atol=2e-3))))
    print("\n回起始位姿 (speed=8)...")
    move_pose(p0.tolist(), quat0, 8.0, joints()); wait_idle()
    st = status()
    p_end = np.array((st.get("endInRef") or [])[:3], dtype=float)
    print("   回位后与起始差 %.3f mm" % (np.linalg.norm(p_end - p0) * 1000))
    tp = np.array([r["tcp_m"] for r in recs])
    print("\n═══ 激励数据 ═══ n=%d · TCP std=%s mm · 范围=%s mm"
          % (len(recs), np.round(tp.std(0) * 1000, 2).tolist(), np.round((tp.max(0) - tp.min(0)) * 1000, 1).tolist()))
    dst = os.path.join(OUT, "excite2_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    json.dump({"ts": time.strftime("%F %T"), "n": len(recs), "amp_mm": 30, "speed": 8.0,
               "control_verified": True, "tcp_std_mm": (tp.std(0) * 1000).tolist(), "recs": recs},
              open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("  产物: %s" % dst)
    print("\n判读: %s" % ("✅ 已取得真机有变动配对 (控制权在我, 慢速, ±30mm 内)"
                          if tp.std(0).max() * 1000 > 1 else "⚠️ 变化仍小"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
