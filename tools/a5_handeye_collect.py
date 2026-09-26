#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""a5_handeye_collect.py — A5 · 2D→3D 标定采集 (相机工装固定 + 臂上目标随动)

老倪口径 (real-handeye-calibration): 手眼自监督的前提是 **(框, TCP) 成对变化** ——
  相机工装固定 + 模块被夹爪夹持 → 臂走 ≥10 个不同位姿 → 每帧取 (tcp_pose 真值, 图像观测) 配对。

本脚本:
  ① probe  : 先动 ±10mm 两步, 看图像里目标**是否跟着动** —— 不动 ⇒ 相机看到的是静止台面,
             采集无意义 ⇒ 直接停, 请现场把模块夹进夹爪 / 确认相机朝向 (省一轮白采)
  ② collect: 探针通过后走 12 个位姿 (±15mm 网格, 每位姿读 tcp_pose + 触发一次 AOI 取图),
             产出 data/handeye/pose_*.json + 图像, 供 A6 解算

安全: 只用 /move_pose (不切伺服下电) · speed=30 (驱动 rt_speed_ratio=0.05 ⇒ 慢) ·
      每步前只读核 operation_state=idle · 幅度 ≤15mm · 结束回起始位姿
用法: ./gui-venv311/bin/python tools/a5_handeye_collect.py --probe | --collect [--n 12]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

import numpy as np
import cv2

R = "/home/ubuntu/zmax_rel"
sys.path.insert(0, os.path.join(R, "tools"))
CAM = "http://192.168.23.23:10082"
ORIN = ["sshpass", "-p", "ts123", "ssh", "-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=no",
        "tashan@192.168.23.66"]
JN = ["XMS5-R800-W4G3B4C_joint_%d" % i for i in range(1, 7)]
OUT = os.path.join(R, "data/handeye")
ROSX = ('source /opt/ros/humble/setup.bash 2>/dev/null; '
        'for ws in /home/tashan/0810/*/install/setup.bash; do [ -f "$ws" ] && source "$ws" && break; done; '
        'export ROS_DOMAIN_ID=0; ')


def orin(cmd, timeout=60):
    r = subprocess.run(ORIN + ["bash -lc", ROSX + cmd], capture_output=True, text=True, timeout=timeout)
    return (r.stdout or "") + (r.stderr or "")


def _val(t, k):
    i = t.find('"%s"' % k)
    if i < 0:
        return None
    j = t.find('"', i + len(k) + 2)
    k2 = t.find('"', j + 1)
    return t[j + 1:k2] if k2 > j else None


def state():
    t = orin("timeout 10 ros2 topic echo --once /robot_status 2>/dev/null", 30)
    m = re.search(r'"has_error"\s*:\s*(true|false)', t)
    return {"power": _val(t, "power_state"), "operation": _val(t, "operation_state"),
            "has_error": (m.group(1) == "true") if m else None}


def joints():
    t = orin("timeout 10 ros2 topic echo --once /real_joint_states 2>/dev/null | grep -A 8 'position:' | head -8", 30)
    v = [float(x) for x in re.findall(r"^- ([-\d.eE]+)$", t, re.M)][:6]
    return v if len(v) == 6 else None


def tcp():
    """读 /robot/tcp_pose: 先解析 position 块 (x,y,z), 再解析 orientation 块 (x,y,z,w)"""
    t = orin("timeout 10 ros2 topic echo --once /robot/tcp_pose 2>/dev/null", 30)
    try:
        pi = t.find("position:")
        oi = t.find("orientation:")
        if pi < 0 or oi < 0:
            return None
        pblk = t[pi:oi]
        oblk = t[oi:]
        p = [float(v) for v in __import__("re").findall(r":\s*([-\d.eE]+)", pblk)[:3]]
        q = [float(v) for v in __import__("re").findall(r":\s*([-\d.eE]+)", oblk)[:4]]
        if len(p) != 3 or len(q) != 4:
            return None
        return {"p": p, "q": q}
    except Exception:                                                           # noqa: BLE001
        return None


def move_pose(p, q, speed=30.0, jpos=None, timeout=120):
    js = ", ".join('"%s"' % n for n in JN)
    jp = ", ".join("%.9f" % x for x in (jpos or [0.0] * 6))
    cmd = ('timeout 100 ros2 service call /move_pose interfaces/srv/TargetPose '
           '"{speed: %.1f, joint_state: {name: [%s], position: [%s]}, '
           'pose: {position: {x: %.9f, y: %.9f, z: %.9f}, '
           'orientation: {x: %.9f, y: %.9f, z: %.9f, w: %.9f}}}"' % (speed, js, jp, p[0], p[1], p[2], q[0], q[1], q[2], q[3]))
    out = orin(cmd, timeout)
    ok = "success=True" in out
    return ok, out.strip().splitlines()[-1][:150] if out.strip() else ""


def cam_observe(tag):
    """触发一次 AOI 拍照 + 取原图 + 用自裁 meta 实测几何当作 2D 观测"""
    try:
        req = urllib.request.Request(CAM + "/capture_detect", data=b"{}",
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=90) as r:
            r.read()
        time.sleep(4.5)
        with urllib.request.urlopen(CAM + "/picture?kind=origin", timeout=40) as r:
            img = cv2.imdecode(np.frombuffer(r.read(), np.uint8), cv2.IMREAD_COLOR)
        ip = os.path.join(OUT, "img_%s.png" % tag)
        cv2.imwrite(ip, img)                      # ★ 无论自裁成败都存图 (否则看不到现场到底拍了啥)
        import aoi_exposure_fix as FX
        clean, meta = FX.clean_judge_frame(img, out=960, return_natural=True)
        g_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        if clean is None:
            # 兜底观测 (鲁棒): 行/列边缘能量峰 → 结构化条带的位置与尺寸 (与自裁口径同源, 只是规则更松)
            gf = g_gray.astype(np.float32)
            re_ = np.abs(np.diff(gf, axis=1)).mean(axis=1)          # 每行边缘能量
            thr = np.percentile(re_, 92)
            rows = np.where(re_ >= thr)[0]
            if rows.size >= 5:
                y0, y1 = int(rows.min()), int(rows.max())
                band = gf[y0:y1 + 1]
                ce = np.abs(np.diff(band, axis=0)).mean(axis=0) if band.shape[0] > 2 else np.abs(np.diff(band, axis=1)).mean(axis=0)
                xs = np.where(ce >= np.percentile(ce, 90))[0]
                x0, x1 = (int(xs.min()), int(xs.max())) if xs.size else (0, img.shape[1] - 1)
                return {"obs": [(x0 + x1) / 2.0, (y0 + y1) / 2.0, x1 - x0, y1 - y0],
                        "note": "兜底(边缘能量带): box中心+宽高", "img": os.path.basename(ip),
                        "fallback": True, "mean": round(float(g_gray.mean()), 1),
                        "sat": round(float((g_gray >= 250).mean() * 100), 1)}
            return {"obs": None, "note": "自裁+兜底都未找到条带", "img": os.path.basename(ip),
                    "mean": round(float(g_gray.mean()), 1), "std": round(float(g_gray.std()), 1),
                    "sat": round(float((g_gray >= 250).mean() * 100), 1)}
        kr = meta.get("kept_rows") or [None, None]
        xs = (meta.get("x_trim") or {}).get("x_span") or [None, None]
        if None in (kr[0], xs[0]):
            return {"obs": None, "note": "几何缺失"}
        cx = (xs[0] + xs[1]) / 2.0
        cy = (kr[0] + kr[1]) / 2.0
        ip = os.path.join(OUT, "img_%s.png" % tag)
        cv2.imwrite(ip, img)
        return {"obs": [cx, cy, xs[1] - xs[0], kr[1] - kr[0]], "note": "box中心+宽高(origin坐标)",
                "img": os.path.basename(ip), "sat": meta.get("sat_after")}
    except Exception as e:                                                      # noqa: BLE001
        return {"obs": None, "note": "%s: %s" % (type(e).__name__, str(e)[:70])}


def wait_idle(sec=25):
    for _ in range(sec):
        s = state()
        if s["operation"] == "idle":
            return s
        time.sleep(1)
    return state()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--collect", action="store_true")
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--amp", type=float, default=15.0, help="点位幅度 mm (默认 ±15mm)")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)

    s0 = state()
    print("═══ 下发前三查 ═══")
    print("  power=%s · operation=%s · has_error=%s" % (s0["power"], s0["operation"], s0["has_error"]))
    if s0["operation"] != "idle":
        print("  ❌ operation_state 非 idle → 按红线不下发任何运动")
        return 1
    j0 = joints()
    t0 = tcp()
    print("  起始 J6=%.6f rad" % (j0[5] if j0 else float("nan")))
    print("  起始 TCP=(%.6f, %.6f, %.6f) q=(%.4f,%.4f,%.4f,%.4f)" % (t0["p"][0], t0["p"][1], t0["p"][2], *t0["q"]))

    if a.probe:
        print("\n═══ ① 探针: 位姿 A (原位) 取图 ═══")
        oA = cam_observe("probeA")
        print("  观测A:", oA.get("obs"), oA.get("note"))
        dx = a.amp / 1000.0
        tgt = [t0["p"][0] + dx, t0["p"][1], t0["p"][2]]
        print("\n═══ ② 位姿 B: x %+.1fmm ═══" % a.amp)
        ok, msg = move_pose(tgt, t0["q"], 30.0, j0)
        print("  回执:", ok, msg)
        wait_idle()
        t1 = tcp()
        if t1:
            d = [ (t1["p"][i] - t0["p"][i]) * 1000 for i in range(3)]
            print("  实测 ΔTCP = (%.3f, %.3f, %.3f) mm" % tuple(d))
        oB = cam_observe("probeB")
        print("  观测B:", oB.get("obs"), oB.get("note"))
        moved = None
        if oA.get("obs") and oB.get("obs"):
            moved = [round(oB["obs"][i] - oA["obs"][i], 2) for i in range(2)]
            print("\n★ 图像观测位移 Δ(u,v) = %s px  (位姿位移 %+.1f mm)" % (moved, a.amp))
            print("  判读: %s" % ("✅ 目标随臂动 → 相机看的是臂上目标, A5 采集有意义"
                                  if max(abs(moved[0]), abs(moved[1])) > 5 else
                                  "❌ 图像几乎不动 → 相机看的是**静止台面** ⇒ 采集无意义; 请现场把模块夹进夹爪或确认相机朝向"))
        else:
            print("\n⚠️ 观测缺失, 无法判读 (看上面的 note)")
        # 回原位
        print("\n═══ ③ 回起始位姿 ═══")
        ok2, msg2 = move_pose(t0["p"], t0["q"], 30.0, joints())
        print("  回位:", ok2, msg2)
        wait_idle()
        t2 = tcp()
        if t2:
            print("  回位后 TCP=(%.6f, %.6f, %.6f)  与起始差 %.3f mm" %
                  (t2["p"][0], t2["p"][1], t2["p"][2],
                   sum(((t2["p"][i] - t0["p"][i]) * 1000) ** 2 for i in range(3)) ** 0.5))
        json.dump({"ts": time.strftime("%F %T"), "type": "probe", "t0": t0, "j0": j0,
                   "t1": t1, "oA": oA, "oB": oB, "img_delta_px": moved},
                  open(os.path.join(OUT, "probe_%s.json" % time.strftime("%Y%m%d_%H%M%S")), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        return 0

    if a.collect:
        amp = a.amp / 1000.0
        pat = [(0, 0), (amp, 0), (-amp, 0), (0, amp), (0, -amp), (amp, amp),
               (-amp, -amp), (amp, -amp), (-amp, amp), (0, 0), (amp / 2, 0), (-amp / 2, 0)][:a.n]
        recs = []
        for i, (dxx, dyy) in enumerate(pat):
            tgt = [t0["p"][0] + dxx, t0["p"][1] + dyy, t0["p"][2]]
            ok, msg = move_pose(tgt, t0["q"], 30.0, joints())
            wait_idle()
            tt = tcp()
            o = cam_observe("p%02d" % i)
            recs.append({"i": i, "target_mm": [dxx * 1000, dyy * 1000], "move_ok": ok, "msg": msg,
                         "tcp": tt, "cam": o})
            print("  位姿%02d 目标(%+6.1f,%+6.1f)mm 移动=%s TCP=(%.6f,%.6f,%.6f) 观测=%s" %
                  (i, dxx * 1000, dyy * 1000, ok, tt["p"][0] if tt else float("nan"),
                   tt["p"][1] if tt else float("nan"), tt["p"][2] if tt else float("nan"),
                   o.get("obs") if o.get("obs") else o.get("note")))
        ok, msg = move_pose(t0["p"], t0["q"], 30.0, joints())
        print("  回起始位姿:", ok, msg)
        dst = os.path.join(OUT, "collect_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
        json.dump({"ts": time.strftime("%F %T"), "start_tcp": t0, "start_joints": j0, "amp_mm": a.amp, "recs": recs},
                  open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        good = [r for r in recs if r["tcp"] and r["cam"].get("obs")]
        print("\n采集完成: %d/%d 位姿有效 → %s" % (len(good), len(recs), dst))
        return 0
    print("请指定 --probe 或 --collect")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
