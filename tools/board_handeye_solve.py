#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""board_handeye_solve.py — 用 CGB-020 (5×4 方格 · 20mm) 棋盘做 **eye-in-hand 手眼标定**

老倪 2026-09-19: 「相机是固定在协作臂上, 标定板在相机的下面 … 标定板的标准是 CGB-020 5*4 20mm Version B」

原理 (标准做法, 无需夹爪):
  每个位姿 i:
    ① 检出棋盘内角点 (4×3 = 12 个, 方格 20mm) → `solvePnP` → 板在**相机系**的位姿 T_target2cam
    ② 编码器给出**工具在基座系**的位姿 T_gripper2base (tcp + quat)
  多组位姿 → `cv2.calibrateHandEye` → **T_cam2gripper** (相机相对工具, 即手眼外参)
  再回算 板在基座系 (tray reference) → 给插拔任务当参考面/参考位姿

判据 (宁缺勿假):
  · 检出板的样本 ≥ 8 才允许解 (建议 ≥15)
  · 解完做**留出复核**: 用解出的外参把每帧棋盘角点反投影回图像, 中位重投影误差 ≤ 1.5px 才算通过
  · 通过才落盘 models/handeye_state.json (含 T_cam2gripper/板位姿/每帧误差/样本清单/时间戳)
用法: gui-venv311/bin/python tools/board_handeye_solve.py [--session <dir>] [--min-views 8] [--square-mm 20]
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys
import time

import cv2
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(REPO, "models", "handeye_state.json")
PATTERN = (4, 5)          # 🎯 CGB-020 5×4 = **20 个白点圆点阵列 (非对称)**, 20mm 间距
INVERT = True             # 板是**白点黑底** → findCirclesGrid 需要反色 (实测: 不反色 0 检出)

# 相机内参 (真机 K, 来自 /realsense/color/camera_info 出厂标定)
K_DEFAULT = {"fx": 394.06, "fy": 393.47, "cx": 318.44, "cy": 238.66, "w": 640, "h": 480}


def _K():
    """内参归一化: real_cam_calib.json 里 K 是**行主序 9 元素数组** (不是 dict)"""
    p = os.path.join(REPO, "models", "real_cam_calib.json")
    try:
        d = json.load(open(p, encoding="utf-8"))
        k = d.get("K") or d.get("k")
        if isinstance(k, dict):
            return k, str(p)
        if isinstance(k, (list, tuple)):
            v = list(k)
            if len(v) == 9:                       # [fx,0,cx, 0,fy,cy, 0,0,1]
                return {"fx": float(v[0]), "fy": float(v[4]), "cx": float(v[2]), "cy": float(v[5])}, str(p)
            if len(v) == 4:                       # [fx, fy, cx, cy]
                return {"fx": float(v[0]), "fy": float(v[1]), "cx": float(v[2]), "cy": float(v[3])}, str(p)
    except Exception:                                                          # noqa: BLE001
        pass
    return K_DEFAULT, "内置默认 (real_cam_calib.json 未读到)"


def _quat_to_R(q):
    x, y, z, w = [float(v) for v in q]
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def detect_board(gray, fast=True):
    """检测圆点阵列标定板 (白点黑底 → 反色; 非对称 4×5 = 20 点)

    返回 (像素坐标 Nx2, 描述) —— 兼容 (4,5)/(5,4) 两种编号, 由实际检出决定。
    依据 (2026-09-19 实测): 11/11 样本在**反色**图上以 CALIB_CB_ASYMMETRIC_GRID (4,5) 检出 20 点;
    经典棋盘检测器只在 4 张图上误检 12 个"角点"(圆点间隙) → 以圆点为准。
    """
    src = (255 - gray) if INVERT else gray
    for grid in (PATTERN, (PATTERN[1], PATTERN[0])):
        for pat, pn in ((cv2.CALIB_CB_ASYMMETRIC_GRID, "非对称"), (cv2.CALIB_CB_SYMMETRIC_GRID, "对称")):
            try:
                ok, cs = cv2.findCirclesGrid(src, grid, flags=pat)
            except Exception:                                                   # noqa: BLE001
                ok = False
            if ok:
                return cs.reshape(-1, 2), f"圆点{grid[0]}x{grid[1]}({pn}) {len(cs)}点"
    return None, None


def obj_points(grid, spacing):
    """按 OpenCV 非对称圆点阵约定生成物点 (x = (2j + i%2)*s, y = i*s)"""
    cols, rows = grid
    objp = np.zeros((rows * cols, 3), np.float32)
    k = 0
    for i in range(rows):
        for j in range(cols):
            objp[k] = [(2 * j + (i % 2)) * spacing, i * spacing, 0]
            k += 1
    if np.allclose(objp[:, 1], 0):
        objp[:, 0] = np.arange(cols) * spacing
    return objp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default=None)
    ap.add_argument("--min-views", type=int, default=8)
    ap.add_argument("--square-mm", type=float, default=20.0)
    a = ap.parse_args()
    sess = a.session or (sorted(glob.glob(os.path.expanduser("~/zmax_data/handeye/*/")))[-1]
                         if glob.glob(os.path.expanduser("~/zmax_data/handeye/*/")) else None)
    if not sess:
        raise SystemExit("没有采集会话 (先跑 tools/handeye_collect.py)")
    poses = os.path.join(sess, "poses.jsonl")
    if not os.path.exists(poses):
        raise SystemExit(f"会话里没有 poses.jsonl: {sess}")
    K, ksrc = _K()
    Km = np.array([[K["fx"], 0, K["cx"]], [0, K["fy"], K["cy"]], [0, 0, 1]], float)
    S = a.square_mm
    # 板坐标 (板系, z=0 平面): 4 列 × 3 行 内角点
    OBJ = {g: obj_points(g, S) for g in (PATTERN, (PATTERN[1], PATTERN[0]))}
    print(f"会话: {sess}\n内参: {ksrc} (fx={K['fx']} fy={K['fy']} cx={K['cx']} cy={K['cy']})\n"
          f"棋盘: 内角点 {PATTERN[0]}x{PATTERN[1]} · 方格 {S}mm")

    Rg, tg, Rt, tt, used, miss = [], [], [], [], [], []
    for line in open(poses, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        img = cv2.imread(r["img"])
        if img is None or not r.get("quat"):
            miss.append((r.get("idx"), "图/四元数缺"))
            continue
        cs, desc = detect_board(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
        if cs is None:
            miss.append((r.get("idx"), "圆点板未检出"))
            continue
        grid = (4, 5) if "4x5" in (desc or "") else (5, 4)
        objp = OBJ[grid]
        okp, rvec, tvec = cv2.solvePnP(objp, cs, Km, None, flags=cv2.SOLVEPNP_ITERATIVE)
        if not okp:
            miss.append((r.get("idx"), "solvePnP 失败"))
            continue
        Rt.append(cv2.Rodrigues(rvec)[0]); tt.append(tvec.reshape(3, 1))
        Rg.append(_quat_to_R(r["quat"])); tg.append(np.array(r["tcp"], float).reshape(3, 1))
        used.append(r["idx"])
    print(f"可用位姿: {len(used)} · 不可用: {len(miss)}" +
          (f" ({', '.join(f'#{i}:{w}' for i, w in miss[:6])})" if miss else ""))
    if len(used) < a.min_views:
        print(f"⛔ 不足 {a.min_views} 个可用位姿 → 不标定 (宁缺勿假)。请每个位姿都让标定板在画面里再拖几次。")
        return 2

    Rx, tx = cv2.calibrateHandEye(Rg, tg, Rt, tt, method=cv2.CALIB_HAND_EYE_TSAI)
    T_cam2tool = np.eye(4); T_cam2tool[:3, :3] = Rx; T_cam2tool[:3, 3] = tx.reshape(3)
    # 留出复核: 用解出的外参把板角点投回图像, 看重投影误差
    errs = []
    T_board_base_ref = None
    for i in range(len(used)):
        T_tool_base = np.eye(4); T_tool_base[:3, :3] = Rg[i]; T_tool_base[:3, 3] = tg[i].reshape(3)
        T_cam_base = T_tool_base @ T_cam2tool
        T_board_cam = np.eye(4); T_board_cam[:3, :3] = Rt[i]; T_board_cam[:3, 3] = tt[i].reshape(3)
        T_board_base = np.linalg.inv(T_cam_base) @ T_board_cam
        if T_board_base_ref is None:
            T_board_base_ref = T_board_base
        Rv, _ = cv2.Rodrigues(T_board_cam[:3, :3])
        proj, _ = cv2.projectPoints(objp, Rv, T_board_cam[:3, 3].reshape(3, 1), Km, None)
        img = cv2.imread(json.loads([l for l in open(poses, encoding="utf-8")
                                     if json.loads(l).get("idx") == used[i]][0])["img"])
        cs, _d = detect_board(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
        e = float(np.median(np.linalg.norm(proj.reshape(-1, 2) - cs, axis=1)))
        errs.append({"idx": used[i], "reproj_px": round(e, 3)})
    med = float(np.median([e["reproj_px"] for e in errs]))
    ok = med <= 1.5
    print(f"手眼外参 T_cam2tool: t = {np.round(T_cam2tool[:3, 3], 4).tolist()} m "
          f"| 平移模长 {np.linalg.norm(T_cam2tool[:3, 3]) * 1000:.1f}mm")
    print(f"留出复核: 重投影中位 {med:.3f}px (判据 ≤1.5px) → {'✅ 通过' if ok else '❌ 不通过, 不落盘'}")
    if T_board_base_ref is not None:
        print(f"板在基座系: t = {np.round(T_board_base_ref[:3, 3], 4).tolist()} m (tray reference)")
    if not ok:
        return 3
    out = {"ok": True, "ts": time.strftime("%F %T"), "session": sess,
           "board": {"spec": "CGB-020 5x4 20mm Version B", "inner_corners": list(PATTERN),
                     "square_mm": S},
           "K": K, "K_src": ksrc,
           "T_cam2tool": T_cam2tool.tolist(),
           "T_cam2tool_mm": [round(float(v) * 1000, 2) for v in T_cam2tool[:3, 3]],
           "T_board_base": (T_board_base_ref.tolist() if T_board_base_ref is not None else None),
           "views_used": used, "per_view": errs, "reproj_median_px": med}
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(out, open(STATE + ".tmp", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(STATE + ".tmp", STATE)
    back = json.load(open(STATE, encoding="utf-8"))
    print(f"✅ 已落盘并回读校验: {STATE} ({len(back['views_used'])} 视图 · 中位 {back['reproj_median_px']}px)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
