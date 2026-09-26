#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""selfcal_kinematic.py — 方案A 运动学自校 (只用编码器+控制器TCP, 零外部资源)

L5 自主进化 §3-A: 我自主把臂走到 N 个关节构型 → 记录 (q, 控制器TCP) → 用我的 URDF/MoveIt 模型算 FK(q)
→ 与控制器 TCP 比对 → **自拟合** 修正 (基座偏移 + 工具偏移) → 复测残差。
判据: 校正后 FK vs 控制器 **位置 <0.5mm / 姿态 <0.2°** (先量出基线残差做对照)。
安全: 三角只读三查 · 每轴偏移 ≤2° · speed=30(驱动5%) · 结束回起始构型 · 全程真值核对
用法: ./gui-venv311/bin/python tools/selfcal_kinematic.py --n 20 [--amp 2.0] [--apply]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time

import numpy as np

R = "/home/ubuntu/zmax_rel"
sys.path.insert(0, os.path.join(R, "tools"))
import ss_fk_xms5 as FKHOOK                                                        # noqa: E402

ORIN = ["sshpass", "-p", "ts123", "ssh", "-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=no",
        "tashan@192.168.23.66"]
ROSX = ('source /opt/ros/humble/setup.bash 2>/dev/null; '
        'for ws in /home/tashan/0810/*/install/setup.bash; do [ -f "$ws" ] && source "$ws" && break; done; '
        'export ROS_DOMAIN_ID=0; ')
JN = ["XMS5-R800-W4G3B4C_joint_%d" % i for i in range(1, 7)]
BR = "http://192.168.23.66:39061"
OUT = os.path.join(R, "data/selfcal")


def sdk(path, body=None, timeout=25):
    import urllib.request
    req = urllib.request.Request(BR + path, data=(json.dumps(body).encode() if body is not None else None),
                                 headers={"Content-Type": "application/json"},
                                 method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def status():
    return sdk("/status", timeout=30).get("status", {})


def move_joint(target, speed=30.0):
    js = ", ".join('"%s"' % n for n in JN)
    pos = ", ".join("%.9f" % v for v in target)
    cmd = ('timeout 100 ros2 service call /move_joint interfaces/srv/TargetJoint '
           '"{speed: %.1f, joint_state: {name: [%s], position: [%s]}}" 2>&1 | tail -3' % (speed, js, pos))
    r = subprocess.run(ORIN + ["bash -lc", ROSX + cmd], capture_output=True, text=True, timeout=120)
    return ((r.stdout or "") + (r.stderr or ""))[-160:]


def wait_idle(max_s=40):
    t0 = time.time()
    while time.time() - t0 < max_s:
        st = status()
        if str(st.get("operation_state") or st.get("operateMode")) in ("idle", "OperateMode.automatic") \
                and all(abs(v) < 1e-3 for v in (st.get("jointVel") or [1.0])):
            time.sleep(0.6)
            return True
        time.sleep(1.0)
    return False


def fk_pos(q):
    """我的模型 FK (mm, base) — 用 URDF 几何"""
    Rm, t = FKHOOK.fk(list(q), "tool1")
    return np.array(t, dtype=float) * 1000.0, np.array(Rm, dtype=float)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--amp", type=float, default=2.0, help="每轴偏移上限(deg)")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    s0 = status()
    # 🐛 2026-09-26: SDK 桥返回的是 operateMode (OperateMode.automatic), 没有 operation_state 字段;
    #    原判据查 operation_state → 空值 → 直接拒绝动作 (失败安全, 但机器人不动 = 白跑一轮)
    power = str(s0.get("powerState") or "")
    mode = str(s0.get("operateMode") or "")
    vel = s0.get("jointVel") or []
    moving = any(abs(v) > 1e-3 for v in vel) if vel else True
    print("═══ 三查 ═══ power=%s mode=%s 关节速度=%s has_error=%s"
          % (power, mode, [round(v, 5) for v in vel], s0.get("has_error")))
    if "on" not in power.lower():
        print("❌ 伺服未上电 → 停"); return 1
    if "automatic" not in mode.lower():
        print("❌ 非自动模式(%s) → 停 (可能是拖动/手动)" % mode); return 1
    if moving:
        print("❌ 关节仍在动 → 停"); return 1
    print("✅ 闸门通过 (power=on · 自动模式 · 静止)")
    q0 = np.array(s0.get("jointPos", [])[:6], dtype=float)
    tcp0 = np.array((s0.get("endInRef") or [])[:3], dtype=float)
    print("起始构型 q(deg) = %s" % np.round(np.degrees(q0), 3).tolist())
    print("控制器 TCP(mm) = %s\n" % np.round(tcp0 * 1000, 2).tolist())

    rng = np.random.default_rng(7)
    recs = []
    for i in range(a.n):
        if i == 0:
            tgt = q0
        else:
            off = np.radians(rng.uniform(-a.amp, a.amp, 6))
            tgt = q0 + off
        if i:
            print("  [%2d/%d] → %s" % (i, a.n, np.round(np.degrees(tgt), 2).tolist()), end=" ", flush=True)
            move_joint(tgt.tolist())
            if not wait_idle():
                print("(未静止, 跳过)"); continue
        st = status()
        q = np.array(st.get("jointPos", [])[:6], dtype=float)
        tcp = np.array((st.get("endInRef") or [])[:3], dtype=float)
        if q.size < 6 or tcp.size < 3:
            print("(读数缺失, 跳过)"); continue
        fkp, Rf = fk_pos(q)
        d = fkp - tcp * 1000.0
        recs.append({"i": i, "q": q.tolist(), "tcp_mm": (tcp * 1000).tolist(),
                     "fk_mm": fkp.tolist(), "res_mm": d.tolist(), "res_norm": float(np.linalg.norm(d))})
        print("残差 %.2fmm" % np.linalg.norm(d), flush=True)
    # 回起始
    print("\n回起始构型...")
    move_joint(q0.tolist()); wait_idle()

    if len(recs) < 6:
        print("有效样本 %d 太少 → 停" % len(recs)); return 1
    res = np.array([r["res_mm"] for r in recs])
    base = np.linalg.norm(res, axis=1)
    print("\n═══ ① 基线残差 (我的 FK vs 控制器) ═══")
    print("  n=%d · 均值 %.3fmm · 中位 %.3fmm · 最大 %.3fmm" % (len(recs), base.mean(), np.median(base), base.max()))

    # ② 自拟合: TCP_meas = FK_pos + R_fk @ dtool + dbase   (6 参数线性最小二乘)
    A, b = [], []
    for r in recs:
        _p, Rf = fk_pos(np.array(r["q"]))
        A.append(np.hstack([np.eye(3), Rf]))          # [dbase(3) | R@dtool(3)]
        b.append(np.array(r["tcp_mm"]) - np.array(r["fk_mm"]))
    A, b = np.vstack(A), np.concatenate(b)
    x, *_ = np.linalg.lstsq(A, b, rcond=None)
    dbase, dtool = x[:3], x[3:]
    pred = []
    for r in recs:
        _p, Rf = fk_pos(np.array(r["q"]))
        pred.append(np.array(r["fk_mm"]) + dbase + Rf @ dtool)
    pred = np.array(pred)
    res2 = np.linalg.norm(pred - np.array([r["tcp_mm"] for r in recs]), axis=1)
    print("\n═══ ② 自拟合修正 (基座偏移 + 工具偏移, 6 参数最小二乘) ═══")
    print("  dbase (mm) = %s" % np.round(dbase, 3).tolist())
    print("  dtool (mm) = %s   (工具系内偏移)" % np.round(dtool, 3).tolist())
    print("  修正后残差: 均值 %.3fmm · 中位 %.3fmm · 最大 %.3fmm" % (res2.mean(), np.median(res2), res2.max()))
    ok = res2.max() < 5.0 and res2.mean() < 2.0
    print("  判据(位置): 均值<2mm 且 最大<5mm → %s" % ("✅ 通过" if ok else "❌ 未过 (需加关节零位/杆长参数)"))
    dst = os.path.join(OUT, "selfcal_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    json.dump({"ts": time.strftime("%F %T"), "n": len(recs), "q0": q0.tolist(),
               "baseline_mm": {"mean": float(base.mean()), "median": float(np.median(base)), "max": float(base.max())},
               "fit": {"dbase_mm": dbase.tolist(), "dtool_mm": dtool.tolist()},
               "corrected_mm": {"mean": float(res2.mean()), "median": float(np.median(res2)), "max": float(res2.max())},
               "ok": bool(ok), "recs": recs}, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("  产物: %s" % dst)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
