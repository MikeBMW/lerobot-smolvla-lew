#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""slot_occupy.py — 用标定好的手眼外参判定「一号位/二号位 哪个槽里有光模块」

链路(全部实测口径, 无猜测):
  ① 内参 K/畸变: models/real_cam_calib.json (来自 ROS camera_info)
  ② 手眼 X = T_cam2tool: models/handeye_state.json (2026-09-21 解, 全链路重投影中位 0.117px)
  ③ 当前工具位姿 G: /robot/tcp_pose (与 X 同源: endInRef 工具系)
  ④ 槽位示教点: data/skills/l2_atomic/taught_points.json (slot1/slot2)
  ⑤ 检出: ~/zmax_data/ss_bypass/yolo_detections.json (YOLO peg 框, 与 cam_rs.png 同帧)

判据: 把 slot1/slot2 的位置按 T_cam_base = G·X 投到图像, 与 peg 框中心比距离 <15px 认账;
      否则报"对账失败, 不猜"。
用法: gui-venv311/bin/python tools/slot_occupy.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

import cv2
import numpy as np

REPO = "/home/ubuntu/lerobot-smolvla-lew"
CALIB = os.path.join(REPO, "models", "real_cam_calib.json")
STATE = os.path.join(REPO, "models", "handeye_state.json")
PTS = os.path.join(REPO, "data/skills/l2_atomic/taught_points.json")
DET = os.path.expanduser("~/zmax_data/ss_bypass/yolo_detections.json")
TOL_PX = 15.0
NUM = re.compile(r"-?\d+\.?\d*(?:e-?\d+)?")


def tcp_pose():
    r = subprocess.run(["sudo", "docker", "exec", "ss-remote-tap", "bash", "-lc",
                        "source /opt/ros/humble/setup.bash; export ROS_DOMAIN_ID=0; "
                        "timeout 6 ros2 topic echo --once /robot/tcp_pose --field pose"],
                       capture_output=True, text=True, timeout=25)
    v = [float(x) for x in NUM.findall(r.stdout)]
    if len(v) < 7:
        raise SystemExit("位姿读不到: %s" % (r.stdout + r.stderr)[-160:])
    return v[:3], v[3:7]


def R_from_quat(q):
    x, y, z, w = q
    n = (x * x + y * y + z * z + w * w) ** 0.5 or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def main():
    cal = json.load(open(CALIB, encoding="utf-8"))
    k = cal["K"]
    Km = np.array([[k[0], 0, k[2]], [0, k[4], k[5]], [0, 0, 1]], float)
    dist = np.array(cal.get("dist") or [0, 0, 0, 0, 0], float)
    X = np.array(json.load(open(STATE, encoding="utf-8"))["T_cam2tool"], float)
    slots = json.load(open(PTS, encoding="utf-8"))
    slots = slots.get("points", slots)          # taught_points.json: {version,note,frame,points:{slot1:{pos,...}}}
    det = json.load(open(DET, encoding="utf-8"))

    pos, quat = tcp_pose()
    G = np.eye(4); G[:3, :3] = R_from_quat(quat); G[:3, 3] = pos
    T_cam_base = np.linalg.inv(G @ X)          # 基座→相机
    print("当前工具位姿(基座): [%.4f, %.4f, %.4f]" % tuple(pos))
    print("检出帧龄: %.2fs · 检出数: %d" % (det.get("frame_age_s", -1), det.get("n", 0)))

    proj = {}
    for nm in ("slot1", "slot2"):
        ent = slots.get(nm)
        p = (ent or {}).get("pos") if isinstance(ent, dict) else ent
        if not p:
            continue
        pc = T_cam_base @ np.array([p[0], p[1], p[2], 1.0])
        if pc[2] <= 0.05:
            print("  %s: 在相机后方/太近 (z=%.3f) → 不可判" % (nm, pc[2]))
            continue
        uv, _ = cv2.projectPoints(np.array([[0.0, 0.0, 0.0]]), np.zeros(3), pc[:3].reshape(3, 1), Km, dist)
        uv = uv.reshape(2)
        proj[nm] = uv
        print("  %s 投影: 像素(%.1f, %.1f) · 距相机 %.3fm" % (nm, uv[0], uv[1], pc[2]))

    dets = det.get("detections") or []
    if not dets:
        print("\n结论: 本帧没检出光模块 → 不能判定(先确认画面/相机)")
        return 0
    # 判据(2026-09-21 现场标定后的物理口径):
    #   槽位示教点 = **抓取位**(TCP 在模块被夹住那一刻) → 它投影到图像上落在模块**底部略上方**
    #   (实测: 框底 164.7px vs 槽位投影 153.6px = 11px ≈ 12mm = 夹爪咬合高度)。
    #   所以判定用两条: ①横向 |Δx| ≤ 12px(槽位之间横向差 ~40px, 区分度足够)
    #                  ②框底与投影纵向差在 [-5, +25]px(咬合高度带)
    #   任一不满足 → 不认账(宁缺勿假)。
    print()
    verdict = {}
    for d in dets:
        x1, y1, x2, y2 = d["xyxy"]
        cx, cy_bottom = (x1 + x2) / 2.0, y2
        print("  框 conf=%.2f 中心(%.0f,%.0f) 底心(%.0f,%.0f)" % (d["conf"], (x1 + x2) / 2, (y1 + y2) / 2, cx, cy_bottom))
        for nm, uv in proj.items():
            dx = abs(cx - uv[0])
            dy = cy_bottom - uv[1]
            hit = (dx <= 12.0) and (-5.0 <= dy <= 25.0)
            print("     vs %s 投影(%.1f,%.1f): Δx=%.1fpx · 框底-投影 y=%+.1fpx → %s"
                  % (nm, uv[0], uv[1], dx, dy, "✅ 对上" if hit else "✗"))
            if hit:
                verdict[nm] = verdict.get(nm, 0) + 1
    if not verdict:
        print("\n结论: ❌ 对账失败 → 不猜(画面里要对得上槽位与模块)")
    else:
        print("\n结论: ✅ %s 有光模块" % "、".join("%s(%d个)" % (k2, v) for k2, v in verdict.items()))
        for nm in ("slot1", "slot2"):
            if nm not in verdict:
                print("        %s 判定为空槽" % nm)
    return 0


if __name__ == "__main__":
    sys.exit(main())
