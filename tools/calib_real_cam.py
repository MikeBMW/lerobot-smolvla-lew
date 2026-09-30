#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""calib_real_cam.py — 真机相机标定 (内参 + 相机↔机器人外参) → models/real_cam_calib.json

为什么必须标: 仿真的 K/T 来自 mujoco 模型 (白送); 真机要自己量 ——
  · 内参 K: 棋盘格标定 (cv2.calibrateCamera)
  · 外参 T_base_cam: 相机装在工作台上 → 用机器人夹爪带着标定板走 N 个位姿, cv2.calibrateHandEye
    (eye-to-hand 用 calibrateHandEye 的 eye-to-hand 约定: R_base2gripper 取逆)
  · plane_z: 工装台面/托盘面在 base 系的高度 (标定板放在该面上量一次即可)
没有标定文件时, real_yolo_perceive 会明确标 gap 并在**相机系**给点 (不编造 base 系坐标)。

三种用法:
  ① 内参:  --intrinsics <棋盘格图片目录>            (12+ 张不同角度)
  ② 外参:  --handeye <目录, 每张图配一个同名 .json>  (.json 里 {"tcp":[x,y,z,qx,qy,qz,qw]})
  ③ 检查:  --show                                   (打印当前标定文件内容与就绪状态)
"""
import argparse
import glob
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CALIB = os.path.join(ROOT, "models/real_cam_calib.json")


def _load(path):
    if os.path.isfile(path):
        return json.load(open(path, encoding="utf-8"))
    return {}


def cmd_intrinsics(args):
    import cv2
    pat = (int(args.pattern[0]), int(args.pattern[1]))
    objp = np.zeros((pat[0] * pat[1], 3), np.float32)
    objp[:, :2] = np.mgrid[0:pat[0], 0:pat[1]].T.reshape(-1, 2) * float(args.square)
    obj, img_pts, size = [], [], None
    for p in sorted(glob.glob(os.path.join(args.intrinsics, "*"))):
        img = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        ok, corners = cv2.findChessboardCorners(img, pat, None)
        if not ok:
            print(f"  ⏭ 未找到棋盘: {os.path.basename(p)}")
            continue
        corners = cv2.cornerSubPix(img, corners, (11, 11), (-1, -1),
                                   (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001))
        obj.append(objp)
        img_pts.append(corners)
        size = img.shape[::-1]
        print(f"  ✅ {os.path.basename(p)}")
    if len(obj) < 6:
        print(f"❌ 有效图 {len(obj)} < 6, 标不出来 (至少 6 张不同角度)")
        return 2
    rms, K, dist, _, _ = cv2.calibrateCamera(obj, img_pts, size, None, None)
    print(f"\n内参: fx={K[0,0]:.3f} fy={K[1,1]:.3f} cx={K[0,2]:.3f} cy={K[1,2]:.3f} · RMS={rms:.4f}px · {size}")
    d = _load(CALIB)
    d.update({"K": [float(v) for v in K.ravel()], "dist": [float(v) for v in np.asarray(dist).ravel()],
              "image_size": [int(size[0]), int(size[1])], "intrinsics_rms_px": float(rms),
              "source": "chessboard-cv2"})
    d["ready"] = True
    os.makedirs(os.path.dirname(CALIB), exist_ok=True)
    json.dump(d, open(CALIB, "w"), indent=1, ensure_ascii=False)
    print("写入:", CALIB)
    return 0


def _quat_to_R(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def cmd_handeye(args):
    import cv2
    pat = (int(args.pattern[0]), int(args.pattern[1]))
    objp = np.zeros((pat[0] * pat[1], 3), np.float32)
    objp[:, :2] = np.mgrid[0:pat[0], 0:pat[1]].T.reshape(-1, 2) * float(args.square)
    d = _load(CALIB)
    if not d.get("K"):
        print("❌ 先做内参 (--intrinsics), 外参解算需要 K")
        return 2
    K = np.asarray(d["K"], float).reshape(3, 3)
    dist = np.asarray(d.get("dist") or [0, 0, 0, 0, 0], float)
    R_g2b, t_g2b, R_t2c, t_t2c = [], [], [], []
    for p in sorted(glob.glob(os.path.join(args.handeye, "*"))):
        jp = os.path.splitext(p)[0] + ".json"
        if not os.path.isfile(jp):
            continue
        img = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
        ok, corners = cv2.findChessboardCorners(img, pat, None)
        if not ok:
            continue
        corners = cv2.cornerSubPix(img, corners, (11, 11), (-1, -1),
                                   (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001))
        rvec, tvec = cv2.solvePnP(objp, corners, K, dist)[1:3]
        tcp = json.load(open(jp, encoding="utf-8"))["tcp"]        # base 系夹爪位姿
        R_g2b.append(_quat_to_R(tcp[3:7]))
        t_g2b.append(np.asarray(tcp[:3], float))
        R_t2c.append(cv2.Rodrigues(rvec)[0])
        t_t2c.append(tvec.ravel())
    if len(R_g2b) < 4:
        print(f"❌ 有效配对 {len(R_g2b)} < 4 (每张图要配同名 .json 提供 tcp 位姿)")
        return 2
    # eye-to-hand: 相机固定在工位上, 标定板随夹爪动 → calibrateHandEye 用 (R_g2b^T, ...) 约定
    R_c2b, t_c2b = cv2.calibrateHandEye([r.T for r in R_g2b], t_g2b, R_t2c, t_t2c,
                                        method=cv2.CALIB_HAND_EYE_TSAI)
    T = np.eye(4)
    T[:3, :3] = R_c2b
    T[:3, 3] = np.asarray(t_c2b).ravel()
    d.update({"T_base_cam": [float(v) for v in T.ravel()], "handeye_pairs": len(R_g2b),
              "source_ext": "calibrateHandEye(TSAI, eye-to-hand)"})
    json.dump(d, open(CALIB, "w"), indent=1, ensure_ascii=False)
    print(f"外参 T_base_cam 写入: {CALIB} (配对 {len(R_g2b)} 组)")
    print(np.round(T, 5))
    example = {"plane_z": {"光模块": 0.02, "hole": 0.02, "hand": 0.15}}
    print("\n⚠️ 还需人工量一次工装面高度写进 plane_z (无深度时的回退平面), 例: "
          + json.dumps(example, ensure_ascii=False))
    return 0


def cmd_show(args):
    d = _load(CALIB)
    print(f"标定文件: {CALIB}")
    print(json.dumps(d, indent=1, ensure_ascii=False) if d else "❌ 不存在 → 真机只能给 2D 框 (会显式标 gap)")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--intrinsics", help="棋盘格图片目录")
    ap.add_argument("--handeye", help="手眼标定目录 (图片 + 同名 tcp json)")
    ap.add_argument("--pattern", default="9x6", help="棋盘格内角点 列x行 (默认 9x6)")
    ap.add_argument("--square", default=0.025, help="方格边长 米 (默认 25mm)")
    ap.add_argument("--show", action="store_true")
    a = ap.parse_args()
    if a.show:
        return cmd_show(a)
    if a.intrinsics:
        return cmd_intrinsics(a)
    if a.handeye:
        return cmd_handeye(a)
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
