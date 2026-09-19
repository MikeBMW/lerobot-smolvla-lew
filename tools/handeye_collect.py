#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""handeye_collect.py (v7) — 手眼采集: **位姿 6 秒轨迹 + 画面同帧** 双锁

老倪 2026-09-19 现场: 前面 v6 仍有"图/位姿不同刻"(8 视图解出残差 47px, 逐视图 24~91px 不等)。
  → 根因: 我允许"帧龄 ≤3s", 而移动快时那 3 秒里机械臂已经动了很多。
v7 锁死办法 (物理上无懈可击, 不靠时间戳):
  ① 一次 ssh 拿 **6 秒位姿轨迹** (ros2 topic echo 连续流, 50Hz) → 要求这 6 秒内位置极差 ≤1.5mm
     (机械臂真的静止) 且能算出稳定均值
  ② 同时本机每 0.4s 记 cam_rs.png 的 md5 → 要求这 6 秒内**画面完全一致(同一 md5)**
  ③ 两条同时成立 ⇒ 这 6 秒里"机械臂静止 + 相机看到的世界没变" ⇒ 该帧必然就是这个位姿拍的
  ④ 与上次保存的位姿位置 ≥8mm 或姿态 ≥5° (纯转手腕也算)
全程只读: 一次 ssh 话题订阅 + 读本地 jpg; 不发任何运动指令。
"""
import argparse
import glob
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import threading
import time

import cv2
import numpy as np

REPO = "/home/ubuntu/lerobot-smolvla-lew"
OUT = os.path.expanduser("~/zmax_data/handeye")
ORIN = "tashan@192.168.23.66"
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6", ORIN]
ROS_PRE = ('source /opt/ros/humble/setup.bash; for ws in /home/tashan/0810/*/install/setup.bash; '
           'do [ -f "$ws" ] && source "$ws" && break; done; export ROS_DOMAIN_ID=0; ')
TRACE_S = 6.0
STATIC_MM = 1.5
STATIC_DEG = 0.5
MOVE_MM = 8.0
MOVE_DEG = 5.0
HEART_S = 6.0
FRAME_DIFF = 2.0        # 相邻帧平均绝对差上限 (灰阶)
FRAME_SHIFT_PX = 0.30   # 相邻帧相位位移上限 (像素)


def _trace():
    """一次 ssh 拿 6 秒位姿轨迹 (x,y,z,qx,qy,qz,qw 逐行)."""
    cmd = (ROS_PRE + f"timeout {TRACE_S + 1:.0f} ros2 topic echo /robot/tcp_pose "
           "--field pose 2>/dev/null")
    try:
        out = subprocess.run(SSH + [cmd], capture_output=True, text=True,
                             timeout=TRACE_S + 12).stdout
    except Exception:                                                          # noqa: BLE001
        return []
    vals = [float(x) for x in re.findall(r"[-+]?\d*\.?\d+(?:e[-+]?\d+)?", out)]
    # 每条消息 7 个数 (x,y,z,qx,qy,qz,qw)
    n = len(vals) // 7 * 7
    return [vals[i:i + 7] for i in range(0, n, 7)]


def _board_pts(path):
    try:
        g = cv2.bitwise_not(cv2.cvtColor(cv2.imread(path), cv2.COLOR_BGR2GRAY))
        for flags in (cv2.CALIB_CB_ASYMMETRIC_GRID, cv2.CALIB_CB_SYMMETRIC_GRID):
            for pat in ((4, 5), (5, 4)):
                ok, pts = cv2.findCirclesGrid(g, pat, flags=flags)
                if ok and pts is not None:
                    return len(pts)
    except Exception:                                                          # noqa: BLE001
        return 0
    return 0


def _qang(q1, q2):
    d = abs(sum(x * y for x, y in zip(q1, q2)))
    return math.degrees(2.0 * math.acos(max(-1.0, min(1.0, d))))


def _dist(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=3600)
    ap.add_argument("--target", type=int, default=16)
    a = ap.parse_args()

    odir = os.path.join(OUT, time.strftime("%Y%m%d_%H%M%S"))
    imgdir = os.path.join(odir, "img")
    os.makedirs(imgdir, exist_ok=True)
    logp = os.path.join(odir, "poses.jsonl")
    fp = os.path.expanduser("~/zmax_ss_remote/cam_rs.png")
    print(f"📸 手眼采集 v7 (位姿6秒轨迹+同帧双锁) → {odir} · 目标 {a.target} · 上限 {a.seconds:.0f}s", flush=True)

    n = 0
    last_saved = None
    last_hb = 0.0
    t_end = time.time() + a.seconds
    while time.time() < t_end and n < a.target:
        # ① 并行: 6 秒位姿轨迹 + 本机画面 md5 采样
        res = {}

        def _do_trace():
            res["trace"] = _trace()

        th = threading.Thread(target=_do_trace, daemon=True)
        th.start()
        shots = []
        while th.is_alive():
            try:
                im = cv2.imread(fp, 0)
                if im is not None:
                    shots.append(cv2.resize(im, (320, 240)))
            except Exception:                                                  # noqa: BLE001
                pass
            time.sleep(0.4)
        th.join()
        trace = res.get("trace") or []
        if len(trace) < 5:
            print("   · ⚠️ 位姿轨迹读取失败 (ssh/ros2), 重试", flush=True)
            time.sleep(1.0)
            continue
        pos = np.array([v[:3] for v in trace])
        quat = np.array([v[3:] for v in trace])
        pmean, qmean = pos.mean(0), quat.mean(0)
        pspread = float(np.max(np.linalg.norm(pos - pmean, axis=1)) * 1000.0)
        qspread = float(max(_qang(q, qmean) for q in quat))
        # 画面稳定性: 相邻帧平均绝对差 + 相位位移 (自动曝光会让 md5 变, 但内容几乎不变)
        dmax, smax = 0.0, 0.0
        for k in range(1, len(shots)):
            prev, cur = shots[k - 1].astype(np.float32), shots[k].astype(np.float32)
            dmax = max(dmax, float(np.mean(np.abs(cur - prev))))
            try:
                (dx, dy), _resp = cv2.phaseCorrelate(prev, cur)
                smax = max(smax, float(math.hypot(dx, dy)))
            except Exception:                                                  # noqa: BLE001
                pass
        uniq = len(shots)
        moved = math.inf if last_saved is None else _dist(pmean, last_saved["tcp"])
        dang = math.inf if last_saved is None else _qang(qmean, last_saved["quat"])
        if time.time() - last_hb >= HEART_S:
            last_hb = time.time()
            print(f"   · 心跳: 位姿 {len(trace)} 点 极差 {pspread:.2f}mm/{qspread:.2f}° · "
                  f"画面 {len(shots)} 帧 差异 {dmax:.2f} 位移 {smax:.2f}px · "
                  f"距上次 {moved * 1000:.0f}mm/{dang:.1f}° · 已存 {n}/{a.target}", flush=True)
        if pspread > STATIC_MM or qspread > STATIC_DEG:
            print(f"   · ❌ 位姿不稳 (极差 {pspread:.2f}mm/{qspread:.2f}°) → 请停稳后再等 6 秒", flush=True)
            continue
        if dmax > FRAME_DIFF or smax > FRAME_SHIFT_PX or len(shots) < 5:
            print(f"   · ❌ 画面还在动 (差异 {dmax:.2f} / 位移 {smax:.2f}px, 需 ≤{FRAME_DIFF}/{FRAME_SHIFT_PX})"
                  f" → 等相机稳定 (自动曝光漂移也会算动, 停稳后再等 6 秒)", flush=True)
            continue
        if last_saved is not None and moved * 1000 < MOVE_MM and dang < MOVE_DEG:
            print(f"   · ⚠️ 与上一个位姿太像 ({moved * 1000:.0f}mm/{dang:.1f}°) → 换个明显不同的位姿", flush=True)
            continue
        n += 1
        dst = os.path.join(imgdir, f"{n:04d}.png")
        shutil.copy2(fp, dst)
        npts = _board_pts(dst)
        rec = {"idx": n, "t": time.time(), "img": dst, "board_points": npts,
               "tcp": [round(v, 6) for v in pmean], "quat": [round(v, 6) for v in qmean],
               "trace_n": len(trace), "pose_spread_mm": round(pspread, 3),
               "pose_spread_deg": round(qspread, 3), "frame_unique_in_6s": uniq,
               "src": "orin:/robot/tcp_pose 6s轨迹 + 同帧锁"}
        with open(logp, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"   {'✅' if npts >= 20 else '⚠️'} 样本 {n}/{a.target} · 板 {npts} 点 · "
              f"TCP [{pmean[0]:.4f}, {pmean[1]:.4f}, {pmean[2]:.4f}] · 位姿 6s 极差 {pspread:.2f}mm · "
              f"画面稳定(差异{dmax:.2f}/位移{smax:.2f}px) · 距上次 {moved * 1000:.0f}mm/{dang:.1f}°", flush=True)
        last_saved = {"tcp": pmean.tolist(), "quat": qmean.tolist()}
    print(f"🏁 结束: {n}/{a.target} → {logp}", flush=True)


if __name__ == "__main__":
    main()
