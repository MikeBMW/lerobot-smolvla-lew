#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""real_autolabel.py — 用「机器人实际动作」自动标注光模块 (kinematic auto-labeling)

老倪 2026-09-17:「设计一下, 如何通过机器人的实际动作, 抓取光模块, 自动标注。」

═══ 原理 (为什么根本不需要人拖框) ═══
机器人自己就是标定物与真值源, 分三步:

  S0 探针运动 (probe)     机器人夹着光模块在相机视野内走 9~12 个位姿 (覆盖画面四角/中心/不同深度)。
                          每个位姿记 3D 真值 = /robot/tcp_pose (=base_link 真值, ~50Hz 已落盘) 与一帧图像。
                          模块的**像素位置**不用人工框: 画面里只有夹爪+模块在动 → 相邻帧差分取运动连通域中心即可
                          (见 motion_center)。孔口/工装静止不参与差分, 天然被排除。

  S1 自标定 (kinematic eye-hand calibration)
                          拿 N 对 (3D 真值 → 像素点) 解 3x4 投影矩阵 P (DLT + Hartley 归一化, ≥6 对)。
                          ⚠️ 这等价于一次手眼标定, 但**不用棋盘格** —— 机器人带着模块当标定物。
                          P = K·[R|t] 已含内参与手眼外参的乘积, 做 2D 标注完全够; 需要 3D 反投影时才拆 K。
                          产出 models/real_cam_proj.json {P, n_pairs, rms_px, K_est(fx,fy,cx,cy)}。
                          与仿真口径对照: 仿真用 MuJoCo cam_mat0/cam_pos/cam_fovy 投影 (gen_yolo_data.project_3d_to_2d),
                          真机就是这一步的现场自标定版 —— 两边都是"真值 3D → 像素框", 同口径。

  S2 批量自动标注 (label) 之后任何"抓取→搬运→插入"过程都自动出标注:
                          光模块中心 (TCP + R·offset) + 模块物理尺寸 → 8 角点 → 投影 → AABB → YOLO 框 (class peg);
                          示教了 goal 点就同样投影出 hole 框。
                          **只在"抓取确认成立"的时段标** (抬升随动判据, 与 L4 抬升试探同口径) → 不给"没夹住"的帧发标签。
                          落盘复用 yolo_annot_dataset.save_sample → sessions/auto_<ts>/, annotator="auto:kinematic",
                          与人工样本同结构 → 直接进 dataset/truth.jsonl + 训练。

═══ 诚实边界 (不达标就不进默认档) ═══
· 框尺寸靠**配置的模块物理尺寸**, 不猜: 用 --size 给实测值 (默认 40x16x12mm 仅为占位, 输出里标 pending)。
· offset (模块中心相对 TCP) 未知时先按 0 解 P; 残差 rms_px 明显偏大 → 把 offset 一起最小二乘 (insight: 二者可辨识,
  因为探针运动里姿态在变)。仍未收敛就如实报, 不硬凑。
· 自动标注**绝不用来当 val/测试集** —— 评估必须在人工标注的留出集上做 (否则自证循环)。
· 自动标注与仿真权重能否复用, 由"人工留出集上的指标"裁决, 不由本轮自检裁决。

用法:
  python3 tools/real_autolabel.py --selftest                     # 数学核自检 (合成真值 → 反解 → 断言)
  python3 tools/real_autolabel.py --fit pairs.json --out models/real_cam_proj.json
  python3 tools/real_autolabel.py --label --proj models/real_cam_proj.json --size 0.040,0.016,0.012
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import time

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
PROJ_DEFAULT = os.path.join(_REPO, "models", "real_cam_proj.json")


# ───────────────────────── 投影核 (DLT) ─────────────────────────
def _norm2d(pts):
    """Hartley 归一化 (2D 齐次点 Nx3): 质心→0, 平均距离→sqrt(2)"""
    c = pts[:, :2].mean(axis=0)
    d = np.linalg.norm(pts[:, :2] - c, axis=1).mean()
    s = math.sqrt(2.0) / (d if d > 1e-12 else 1.0)
    T = np.array([[s, 0, -s * c[0]], [0, s, -s * c[1]], [0, 0, 1.0]])
    return pts @ T.T, T


def _norm3d(X):
    c = X[:, :3].mean(axis=0)
    d = np.linalg.norm(X[:, :3] - c, axis=1).mean()
    s = math.sqrt(3.0) / (d if d > 1e-12 else 1.0)
    T = np.eye(4)
    T[0, 0] = T[1, 1] = T[2, 2] = s
    T[:3, 3] = -s * c
    return X @ T.T, T


def fit_proj(pairs):
    """(3D, 2D) 对应 → 3x4 投影矩阵 P。pairs=[((X,Y,Z),(u,v)), ...], 最少 6 对。

    返回 (P(3x4), rms_px)。用 Hartley 归一化 + SVD 取最小奇异向量 (标准 DLT)。
    """
    pairs = [(np.asarray(x, float).reshape(3), np.asarray(uv, float).reshape(2)) for x, uv in pairs]
    if len(pairs) < 6:
        raise ValueError(f"至少需要 6 对点才能解 P, 现在只有 {len(pairs)} 对")
    X = np.hstack([np.stack([p[0] for p in pairs]), np.ones((len(pairs), 1))])       # Nx4
    U = np.hstack([np.stack([p[1] for p in pairs]), np.ones((len(pairs), 1))])       # Nx3
    Xn, T3 = _norm3d(X)
    Un, T2 = _norm2d(U)
    A = []
    for i in range(len(pairs)):
        x, y, z, w = Xn[i]
        u, v = Un[i, 0], Un[i, 1]
        A.append([0, 0, 0, 0, -w * x, -w * y, -w * z, -w * w, v * x, v * y, v * z, v * w])
        A.append([w * x, w * y, w * z, w * w, 0, 0, 0, 0, -u * x, -u * y, -u * z, -u * w])
    _, _, Vt = np.linalg.svd(np.array(A, float))
    Pn = Vt[-1].reshape(3, 4)
    P = np.linalg.inv(T2) @ Pn @ T3
    P = P / (np.linalg.norm(P[:3, :3]) if np.linalg.norm(P[:3, :3]) > 1e-12 else 1.0)
    err = []
    for x, uv in pairs:
        p = project(P, x)
        err.append(float(np.linalg.norm(p - uv)))
    return P, float(np.sqrt(np.mean(np.square(err))))


def project(P, xyz):
    """3D (base_link, 米) → 像素 (u,v)"""
    x = np.append(np.asarray(xyz, float).reshape(3), 1.0)
    h = np.asarray(P, float).reshape(3, 4) @ x
    if abs(h[2]) < 1e-12:
        raise ValueError("点落在相机平面 (w≈0)")
    return np.array([h[0] / h[2], h[1] / h[2]])


def pixel_to_plane(P, uv, z0):
    """像素 + 已知平面 → base 系 3D 点 (只用 P, 不需要单独的内参 K, 也不需要深度传感器)。

    ⚠️ 与 project() 是反方向: project 是 3D→像素 (探针标定的 P 直接可用);
       这个函数是 像素→3D, **必须给一个已知平面** (比如台面高度 z0, 或示教过的工装面)。

    原理 (只用 3x4 投影矩阵就能反算, 因为 P 一个矩阵就够定这条视线):
      · 相机中心 C: P·[C;1] = 0 (取 P 的最小奇异向量)
      · 视线方向 d: 满足 P·X ∝ [u,v,1] 的两个平面交线 = 2x3 齐次方程的解
      · 与 z=z0 求交 → 唯一 3D 点
    验证(2026-09-18 静静): 平面上 12 个随机点 → 投影 → 反算, 误差 0.0000mm。

    用途: L2「📐 2D→3D 解算」节点对**在已知平面上的目标** (孔位/料盘/台面零件) 出 3D,
          不需要在 Orin 上装 RealSense 驱动; 通用任意深度的 3D 仍需米制深度。
    """
    P = np.asarray(P, float).reshape(3, 4)
    u, v = float(uv[0]), float(uv[1])
    C = np.linalg.svd(P)[2][-1]
    if abs(C[3]) < 1e-12:
        return None
    C = C / C[3]
    M = np.vstack([P[0] - u * P[2], P[1] - v * P[2]])[:, :3]
    d = np.linalg.svd(M)[2][-1]
    d = d / (np.linalg.norm(d) or 1.0)
    if abs(d[2]) < 1e-12:
        return None                                   # 视线与平面平行
    t = (float(z0) - C[2]) / d[2]
    return (C[:3] + t * d).tolist()


def _rq(A):
    """RQ 分解: A = K·R (K 上三角, R 正交) — Hartley & Zisserman 标准做法 (别用裸 QR, 会解错)"""
    P = np.array([[0.0, 0.0, 1.0], [0.0, 1.0, 0.0], [1.0, 0.0, 0.0]])
    Q, Rm = np.linalg.qr((P @ A).T)
    return P @ Rm.T @ P, P @ Q.T


def decompose_K(P):
    """从 P 左上 3x3 (=K·R 部分) RQ 分解出内参 (真实性判据: fx>0 且量级合理, 如 300~2000)"""
    M = np.asarray(P, float).reshape(3, 4)[:, :3]
    K, R = _rq(M)
    if abs(K[2, 2]) < 1e-12:
        raise ValueError("RQ 分解失败 (K[2,2]≈0)")
    K = K / K[2, 2]
    S = np.diag(np.sign(np.diag(K)))
    K, R = K @ S, S @ R
    if K[0, 0] < 0:
        K[:, 0] *= -1
        R[0, :] *= -1
    if K[1, 1] < 0:
        K[:, 1] *= -1
        R[1, :] *= -1
    return {"fx": float(K[0, 0]), "fy": float(K[1, 1]),
            "cx": float(K[0, 2]), "cy": float(K[1, 2])}


def quat_to_R(q):
    x, y, z, w = [float(v) for v in q]
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def module_corners(center, quat_xyzw, size_m):
    """光模块 8 角点 (base_link): center + R·(±sx/2, ±sy/2, ±sz/2)"""
    R = quat_to_R(quat_xyzw) if quat_xyzw else np.eye(3)
    hx, hy, hz = [s / 2.0 for s in size_m]
    return [tuple(np.asarray(center, float) + R @ np.array([sx * hx, sy * hy, sz * hz]))
            for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]


def box_from_3d(P, center, quat, size_m, img_wh):
    """模块 (中心+姿态+尺寸) → 图像 axis-aligned 框 (x1,y1,x2,y2)。
    越界裁剪到画面内; 若裁剪后框退化或整体落在画面外 → 返回 None (调用方跳过该帧, 不产生假标签)。"""
    pts = [project(P, c) for c in module_corners(center, quat, size_m)]
    W, H = img_wh
    x1 = max(0.0, min(p[0] for p in pts))
    y1 = max(0.0, min(p[1] for p in pts))
    x2 = min(float(W), max(p[0] for p in pts))
    y2 = min(float(H), max(p[1] for p in pts))
    if (x2 - x1) < 2.0 or (y2 - y1) < 2.0:
        return None
    return x1, y1, x2, y2


# ───────────────────────── S0: 运动域中心 (无需人工框) ─────────────────────────
def motion_center(prev_rgb, cur_rgb, min_area=60):
    """相邻帧差分的最大运动连通域中心 (像素) —— 画面里只有夹爪+模块在动, 静止背景(孔口/工装)天然排除。

    返回 ((u, v), area) 或 (None, 0)。无 cv2 或全静止 → None。
    """
    try:
        import cv2
    except ImportError:
        return None, 0
    if prev_rgb is None or cur_rgb is None:
        return None, 0
    a = cv2.cvtColor(prev_rgb, cv2.COLOR_RGB2GRAY)
    b = cv2.cvtColor(cur_rgb, cv2.COLOR_RGB2GRAY)
    d = cv2.absdiff(a, b)
    _, th = cv2.threshold(d, 18, 255, cv2.THRESH_BINARY)
    th = cv2.morphologyEx(th, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, lab, stats, cent = cv2.connectedComponentsWithStats(th, 8)
    best, best_a = None, 0
    for i in range(1, n):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area >= min_area and area > best_a:
            best, best_a = tuple(cent[i]), area
    return best, best_a


def motion_centroid_all(prev_rgb, cur_rgb, thr=18, min_area=25, roi=None):
    """**全部**运动连通域的面积加权质心 (像素) + 诊断明细。

    为什么必须有这个 (2026-09-18 静静实测定论):
      纯平移时 A△B = (A\\B) ∪ (B\\A) 且 B\\A 是 A\\B 的平移, 两块面积相等、彼此分离
      → `motion_center()` 的"取最大连通域"会**随机挑中左瓣或右瓣**, 质心偏出两帧中点约
        位移量的一半 (实测 15~30px) → 直接进 DLT 就是系统性坏点。
      而 **全部运动像素的面积加权质心在数学上恒等于两帧位置的中点** (与重叠程度无关,
      推导: 对称差关于中点对称 ⇒ 质心落在中点)。
      所以配对必须用"全域质心", 不是"最大域中心"。

    roi=(x1,y1,x2,y2): 只在**该矩形内**统计运动 (用于把"模块+夹爪"的合成运动收口到模块,
      见 probe_pairs_from_session 的 roi_map)。ROI 外一律清零。

    返回 (uv, total_area, comps) —— uv=(u,v) 或 None; comps=[{area, center}, ...]
    """
    try:
        import cv2
    except ImportError:
        return None, 0, []
    if prev_rgb is None or cur_rgb is None:
        return None, 0, []
    a = cv2.cvtColor(prev_rgb, cv2.COLOR_RGB2GRAY)
    b = cv2.cvtColor(cur_rgb, cv2.COLOR_RGB2GRAY)
    d = cv2.absdiff(a, b)
    _, th = cv2.threshold(d, thr, 255, cv2.THRESH_BINARY)
    th = cv2.morphologyEx(th, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    if roi is not None:
        h, w = th.shape[:2]
        x1 = max(0, int(min(roi[0], roi[2])))
        y1 = max(0, int(min(roi[1], roi[3])))
        x2 = min(w, int(max(roi[0], roi[2])))
        y2 = min(h, int(max(roi[1], roi[3])))
        mask = np.zeros_like(th)
        if x2 > x1 and y2 > y1:
            mask[y1:y2, x1:x2] = 255
        th = cv2.bitwise_and(th, mask)
    n, lab, stats, cent = cv2.connectedComponentsWithStats(th, 8)
    comps, tot_a, su, sv = [], 0, 0.0, 0.0
    for i in range(1, n):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area < min_area:
            continue
        comps.append({"area": area, "center": [round(float(cent[i][0]), 2), round(float(cent[i][1]), 2)]})
        tot_a += area
        su += float(cent[i][0]) * area
        sv += float(cent[i][1]) * area
    if tot_a <= 0:
        return None, 0, []
    return (su / tot_a, sv / tot_a), tot_a, comps


# ───────────────────────── 抓取门 (没有夹爪发布者也能判: 图像随动) ─────────────────────────
GRASP_STAGE_WORDS = ("夹持", "抓取", "抬起", "插入", "拔出", "转移", "放下")


def grasp_from_truth(t):
    """从真值侧车判抓取: True=夹住 / False=没夹 / None=判不了 (交给随动判据)。"""
    g = t.get("gripper")
    if isinstance(g, dict):
        for k in ("closed", "is_closed", "grasp"):
            if k in g:
                return bool(g[k])
    st = str(t.get("stage") or t.get("prod_stage") or "")
    if st:
        return any(w in st for w in GRASP_STAGE_WORDS)
    return None


def follow_ok(P, tcp_a, tcp_b, uv_a, uv_b, tol=0.45, min_px=4.0):
    """「抬升随动」判据 (与 L4 抬升试探同口径): 抓取成立时模块在画面里的位移 ≈ TCP 投影位移。

    机器人夹住模块时二者一致 (比值≈1); 没夹住时模块不动而 TCP 在动 (比值≈0)。
    返回 (ok|None, 说明)。
    """
    ea, eb = project(P, tcp_a), project(P, tcp_b)
    exp = np.asarray(eb, float) - np.asarray(ea, float)
    act = np.asarray(uv_b, float) - np.asarray(uv_a, float)
    ne, na = float(np.linalg.norm(exp)), float(np.linalg.norm(act))
    if ne < min_px:
        return None, f"TCP 投影位移太小 ({ne:.1f}px) → 判不了随动"
    ratio = na / ne
    return (abs(ratio - 1.0) <= tol), f"随动比 {ratio:.2f} (期望 1±{tol})"


def motion_near(P, prev_img, cur_img, prev_tcp, tcp, *, quat=None, module_offset_m=None,
                radius_px=40.0, min_area=25, tol_px=None, roi=None):
    """**只在"模块应该在的像素位置"附近找运动** —— 抓取门的核心判据 (比"全图最大域"强得多)。

    为什么必须收口到预测位置 (2026-09-18 演练实测):
      全图最大运动域可能是**夹爪**或别的动东西; 只看它跟 TCP 的比值, 任何跟着 TCP 动的东西
      (夹爪本体)都会"通过"随动判据 → 门形同虚设。收口到模块预测像素附近,
      "模块停着没被夹住"这一类就会被拦下 (预测位置附近无运动)。

    quat/module_offset_m: 预测点 = project(P, TCP中点 + R(q)·模块偏移) —— **必须带偏移**
      (演练实测: 模块相对 TCP 侧偏 40mm 时, 不带偏移的预测偏 ~32px, 门会把好帧也拒掉)。
    roi=(x1,y1,x2,y2): 再叠一层模块区域限制 (见 motion_centroid_all) —— 演练实测: 夹爪可见时
      只靠 radius 不够 (夹爪就在 TCP 上方, 落在半径内), 叠加模块 ROI 后盲区才真正消掉。

    返回 (uv_near|None, area_near, pred_px, n_near, info)
    """
    mid = [(a + b) / 2.0 for a, b in zip(prev_tcp, tcp)]
    try:
        pred = project(P, module_center(mid, quat, module_offset_m))
    except Exception as e:                                                # noqa: BLE001
        return None, 0, None, 0, {"why": f"预测像素不可算: {e}"}
    _uv, _area, comps = motion_centroid_all(prev_img, cur_img, min_area=min_area, roi=roi)
    if not comps:
        return None, 0, pred, 0, {"why": "画面无运动 (差分全灭) → 模块不可能在随动"}
    near = [c for c in comps if math.hypot(c["center"][0] - pred[0], c["center"][1] - pred[1]) <= radius_px]
    if not near:
        return None, 0, pred, 0, {"why": f"预测位置 {pred.round(1).tolist()} ±{radius_px:.0f}px 内无运动 → 未夹住/模块不在视野",
                                  "n_comp": len(comps), "pred": pred.round(1).tolist()}
    a_tot = float(sum(c["area"] for c in near))
    cu = sum(c["center"][0] * c["area"] for c in near) / a_tot
    cv = sum(c["center"][1] * c["area"] for c in near) / a_tot
    d = float(math.hypot(cu - pred[0], cv - pred[1]))
    ea, eb = project(P, prev_tcp), project(P, tcp)
    exp_px = float(np.linalg.norm(np.asarray(eb, float) - np.asarray(ea, float)))
    tol = tol_px if tol_px is not None else max(10.0, 0.75 * exp_px)
    info = {"pred": pred.round(1).tolist(), "n_comp_near": len(near), "n_comp_all": len(comps),
            "area_near": int(a_tot), "d_pred_px": round(d, 2), "exp_px": round(exp_px, 2),
            "tol_px": round(tol, 2), "near_centroid": [round(cu, 2), round(cv, 2)],
            "ok": bool(d <= tol)}
    return (cu, cv), int(a_tot), pred, len(near), info


def probe_design_check(pairs):
    """探针位姿的**可辨识性预检** (2026-09-18 演练实测教训)。

    近共面 (机器人只在正对相机的平面上平移) 会让 DLT 出现**两个**接近零的奇异值, 解出的 P
    在平面外完全不可用 (模块 8 角点一投影就飞出画面)。所以探针必须**有真实深度变化**。

    返回 dict: span_xyz(米) · planarity=σ3/σ1 · dlt_sv_ratio · verdict/why
    """
    X = np.stack([np.asarray(p[0], float) for p in pairs])                 # Nx3
    span = (X.max(axis=0) - X.min(axis=0)).tolist()
    Xc = X - X.mean(axis=0)
    sv = np.linalg.svd(Xc, compute_uv=False)
    planarity = float(sv[2] / sv[0]) if sv[0] > 1e-12 else 0.0
    # DLT 条件数必须在**归一化后**算 (2026-09-18 教训: 用原始坐标算比值恒≈1, 没有判别力)
    Xh = np.hstack([X, np.ones((len(pairs), 1))])
    Uh = np.hstack([np.stack([np.asarray(p[1], float) for p in pairs]), np.ones((len(pairs), 1))])
    Xn, _T3 = _norm3d(Xh)
    Un, _T2 = _norm2d(Uh)
    A = []
    for i in range(len(pairs)):
        x, y, z, w = Xn[i]
        u, v = Un[i, 0], Un[i, 1]
        A.append([0, 0, 0, 0, -w * x, -w * y, -w * z, -w * w, v * x, v * y, v * z, v * w])
        A.append([w * x, w * y, w * z, w * w, 0, 0, 0, 0, -u * x, -u * y, -u * z, -u * w])
    sA = np.linalg.svd(np.asarray(A, float), compute_uv=False)
    ratio = float(sA[-2] / sA[-1]) if sA[-1] > 1e-12 else float("inf")
    # 判据只认**平面性** (2026-09-18: DLT 奇异值比同时受噪声影响, 判别力不足 —— 实测噪声 1px 时
    # 非共面配置也只有 ~11, 而真正的退化 (平面) 表现为 σ3/σ1≈0 且解出的 K 无效)。
    ok = planarity >= 0.15
    why = ("位姿散布合格 (非共面, DLT 可辨识)" if ok else
           f"位姿退化: 平面性 σ3/σ1={planarity:.3f} (需 ≥0.15, DLT 参考奇异值比={ratio:.1f}) "
           f"→ 探针要有真实深度变化, 不能只在正对相机的平面上平移")
    return {"n_pairs": len(pairs), "span_xyz_m": [round(float(s), 4) for s in span],
            "planarity": round(planarity, 4), "dlt_sv_ratio": round(ratio, 1), "ok": bool(ok), "why": why}


def fit_proj_offset(pairs, quats, *, iters=10, off0=None, ret_hist=False):
    """**联合解 (P, 工具系像素点偏移)** —— 抗"夹爪污染"的关键 (2026-09-18 演练实测教训)。

    为什么必须联合解:
      画面上真正在动的是"模块+夹爪"的合成体。若夹爪与模块互相遮挡, 差分质心对应的 3D 点
      不是 TCP, 而是**刚性地固定在夹爪坐标系里的某一点** X(t) = TCP + R(q)·off。
      用 TCP 当 3D 点去解 P → 残差被姿态变化放大 (演练实测 rms 1.0px → 7.3px, 最差 18.4px);
      把 off 一起解 → 残差回到亚像素 (因为观测本来就是一个刚性点的投影)。

    ⚠️ 解出的 off 是**合成点**在工具系的偏移 (混合了模块与夹爪), 只用于解释/诊断标定质量;
       **出框**要用实测的模块偏移 (label_session 的 module_offset_m), 不能用这个 off。

    返回 (P, off(3,), rms_px, hist)
    """
    pairs = [(np.asarray(x, float).reshape(3), np.asarray(uv, float).reshape(2)) for x, uv in pairs]
    Q = [quat_to_R(q) if q else np.eye(3) for q in quats]
    if len(pairs) != len(Q):
        raise ValueError("pairs 与 quats 数量不一致")
    off = np.zeros(3) if off0 is None else np.asarray(off0, float).reshape(3)
    hist = []
    P, rms = fit_proj(pairs)
    for _ in range(int(iters)):
        X = [(x + Q[i] @ off) for i, (x, _uv) in enumerate(pairs)]
        P, rms = fit_proj(list(zip(X, [uv for _x, uv in pairs])))
        off, rms = _gn_off(P, pairs, Q, off)
        hist.append(round(float(rms), 4))
        if len(hist) > 2 and abs(hist[-2] - hist[-1]) < 1e-4:
            break
    return P, off, float(rms), (hist if ret_hist else None)


def _resid_off(P, pairs, Q, off):
    r = []
    for i, (x, uv) in enumerate(pairs):
        p = project(P, x + Q[i] @ off)
        r.extend([p[0] - uv[0], p[1] - uv[1]])
    return np.asarray(r, float)


def _gn_off(P, pairs, Q, off, *, iters=30, h=1e-5, lam=1e-8):
    """给定 P, 用 Gauss-Newton 解工具系偏移 off (3 参数)"""
    off = np.asarray(off, float).copy()
    rms = float(np.sqrt(np.mean(_resid_off(P, pairs, Q, off) ** 2)))
    for _ in range(iters):
        r0 = _resid_off(P, pairs, Q, off)
        J = np.zeros((r0.size, 3))
        for k in range(3):
            d = np.zeros(3)
            d[k] = h
            J[:, k] = (_resid_off(P, pairs, Q, off + d) - _resid_off(P, pairs, Q, off - d)) / (2 * h)
        A = J.T @ J + lam * np.eye(3)
        try:
            step = np.linalg.solve(A, -J.T @ r0)
        except np.linalg.LinAlgError:
            break
        off = off + step
        new = float(np.sqrt(np.mean(_resid_off(P, pairs, Q, off) ** 2)))
        if abs(rms - new) < 1e-5:
            rms = new
            break
        rms = new
    return off, rms


def quat_slerp(qa, qb, t=0.5):
    """四元数球面插值 (xyzw) —— 配对要用**中点姿态**, 不能用某一帧的姿态。

    为什么: 模块中心 = TCP + R(q)·off, off≈90mm 的长杆时, 两帧间转 16° 会让模块中心额外
    移动 ~25mm (~20px)。用后一帧姿态配"两帧 TCP 中点"就引入 0.5·R(Δq)·off ≈ 10px 的系统偏差
    (演练实测: 留出盲测误差 1.1px → 6.1px)。和"位置取中点"是同一类错误, 必须同样处理。
    """
    if not qa or not qb:
        return qb or qa
    a = np.asarray([float(v) for v in qa], float)
    b = np.asarray([float(v) for v in qb], float)
    a = a / (np.linalg.norm(a) or 1.0)
    b = b / (np.linalg.norm(b) or 1.0)
    d = float(np.dot(a, b))
    if d < 0.0:                                    # 取短弧
        b, d = -b, -d
    if d > 0.9995:
        return (a + t * (b - a)).tolist()
    th = math.acos(max(-1.0, min(1.0, d)))
    s = math.sin(th)
    return ((math.sin((1 - t) * th) / s) * a + (math.sin(t * th) / s) * b).tolist()


def module_center(tcp, quat, offset_m):
    """模块几何中心 = TCP + R(工具姿态)·offset (offset 为实测的"模块中心相对 TCP")"""
    if not offset_m or not any(abs(float(v)) > 1e-12 for v in offset_m):
        return list(np.asarray(tcp, float))
    R = quat_to_R(quat) if quat else np.eye(3)
    return list(np.asarray(tcp, float) + R @ np.asarray(offset_m, float).reshape(3))


# ───────────────────────── 标定文件读写 ─────────────────────────
def save_proj(path, P, n_pairs, rms_px, extra=None):
    d = {"ready": True, "P": np.asarray(P, float).reshape(3, 4).tolist(),
         "n_pairs": int(n_pairs), "rms_px": round(float(rms_px), 4),
         "K_est": decompose_K(P), "method": "kinematic DLT (机器人带模块当标定物)",
         "updated_at": time.strftime("%F %T")}
    d["K_est_valid"] = bool(d["K_est"]["fx"] > 0 and d["K_est"]["fy"] > 0)
    # 诚实边界 (2026-09-18 演练实测): 探针只占相机前方一小块 (浅景深) 时内参不可辨识 ——
    # 反投影残差 1.2px 的拟合里 fx 只有 175 (真值 610)。2D 标注可用; 3D 反投影必须单独标 K。
    d["K_est_note"] = ("K_est 仅参考值: 浅景深探针下内参不可辨识 (实测 1.2px 残差时 fx 175 vs 真值 610); "
                       "3D 反投影请单独标定 K")
    if extra:
        d.update(extra)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(d, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return d


def load_proj(path=PROJ_DEFAULT):
    try:
        d = json.load(open(path, encoding="utf-8"))
        if d.get("ready"):
            return np.asarray(d["P"], float).reshape(3, 4), d
    except Exception:                                   # noqa: BLE001
        pass
    return None, {}


# ───────────────────────── S1 采集: 从落盘真值 + 图像生成标定点对 ─────────────────────────
def load_truth_map(truth_jsonl):
    """truth.jsonl → {stem: 行 dict} (容错: 坏行跳过并计数)"""
    truth, bad = {}, 0
    if truth_jsonl and os.path.isfile(truth_jsonl):
        for ln in open(truth_jsonl, encoding="utf-8"):
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
                truth[r["stem"]] = r
            except (ValueError, KeyError):
                bad += 1
    return truth, bad


def load_roi_map(session_dir_or_jsonl):
    """读模块区域 (ROI) 侧车: {stem: [x1,y1,x2,y2]}。

    文件格式 (一行一个): {"stem":"p003","box":[x1,y1,x2,y2],"src":"human|yolo"}
    用途: 探针/在线采集时把"模块+夹爪"的合成运动**收口到模块所在区域** (2026-09-18 演练实测:
      不收口时差分质心是合成点, 解出的 P 会把框整体带偏 —— IoU 0.0; 收口后回到 0.87)。
    ROI 只用来"选区域", **不产生标签** (标签仍来自几何真值), 所以不构成自证循环。
    """
    p = session_dir_or_jsonl
    if os.path.isdir(p):
        p = os.path.join(p, "roi.jsonl")
    roi, n_bad = {}, 0
    if p and os.path.isfile(p):
        for ln in open(p, encoding="utf-8"):
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
                roi[str(r["stem"])] = [float(v) for v in r["box"]]
            except (ValueError, KeyError, TypeError):
                n_bad += 1
    return roi, n_bad


def _roi_union(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def probe_pairs_from_session(session_frame_dir, truth_jsonl=None, out=None, center_mode="all",
                            module_offset_m=None, roi_map=None, roi_pad_px=6.0):
    """把一次"探针运动"的记录整理成 DLT 点对:
    图像 (frames/*.jpg) + 该时刻真值 (TCP/quat) + 模块像素 (=运动域质心)。

    三个必须一起给的输入 (少一个就偏, 2026-09-18 演练逐个实测过):
      ① center_mode="all": 面积加权全域质心 (数学上=两帧位置中点); "largest" 是旧实现, 有偏。
      ② module_offset_m  : **实测**的"模块中心相对 TCP"偏移 → 3D 点 = TCP中点 + R·offset。
                            不给就按 0 (模块中心=TCP), 有偏移时会整体偏。
      ③ roi_map          : 模块区域侧车 (load_roi_map) → 只在 ROI 内取运动, 排除夹爪污染。
                            ℹ️ ROI 必须**每帧独立**给 (每帧一个模块框): 取相邻两帧 ROI 的并集,
                            就自动覆盖了帧间位移, 不会把运动裁掉。roi_pad_px (默认 6px) 只用于
                            容忍定位误差 —— **不能放大** (演练实测: 30px pad 会把夹爪运动重新框进来,
                            标定留出误差 2.3px → 19.2px, IoU 0.76 → 0.0)。

    返回 (pairs, info); pairs 不够 6 对时拟合会明确报错, 不硬凑。
    """
    import cv2
    pairs, used, quats = [], [], []
    truth, n_bad = load_truth_map(truth_jsonl)
    roi_map = roi_map or {}
    frames = sorted(glob.glob(os.path.join(session_frame_dir, "*.jpg")))
    prev, prev_tcp, prev_roi, prev_quat = None, None, None, None
    for fp in frames:
        stem = os.path.splitext(os.path.basename(fp))[0]
        img = cv2.imread(fp)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB) if img is not None else None
        t = truth.get(stem, {}).get("truth", {})
        tcp, quat = t.get("tcp"), t.get("tcp_quat")
        roi = roi_map.get(stem)
        if roi and roi_pad_px:
            roi = [roi[0] - roi_pad_px, roi[1] - roi_pad_px, roi[2] + roi_pad_px, roi[3] + roi_pad_px]
        if img is not None and prev is not None and tcp and prev_tcp:
            if center_mode == "largest":
                uv, area = motion_center(prev, img)
                comps = []
            else:
                uv, area, comps = motion_centroid_all(prev, img, roi=(_roi_union(prev_roi, roi)
                                                                     if (prev_roi or roi) else None))
            if uv:
                # ⚠️ 差分出来的运动域是**两帧之间**的位置, 所以 3D 用两帧的**中点**:
                #   位置取 TCP 中点, 姿态取四元数 slerp 中点 —— 少一样都会引入半采样周期偏置
                #   (位置偏 → 半个采样周期的滞后; 姿态偏 → 0.5·R(Δq)·offset, 长杆上可达 10px)。
                mid = [round((a + b) / 2.0, 6) for a, b in zip(prev_tcp, tcp)]
                qmid = quat_slerp(prev_quat, quat, 0.5)
                X = module_center(mid, qmid, module_offset_m)                    # 实测偏移进配对
                pairs.append((X, uv))
                quats.append(qmid)                       # 联合解 off 需要每对的工具姿态
                used.append({"stem": stem, "tcp_mid": mid, "quat_mid": qmid,
                             "x_used": [round(v, 6) for v in X],
                             "uv": [round(v, 2) for v in uv], "area": area,
                             "n_comp": len(comps), "roi": roi, "comps": comps[:6]})
        prev, prev_tcp, prev_roi, prev_quat = img, tcp, roi, quat
    return pairs, {"n_frame": len(frames), "n_truth": len(truth), "n_bad_truth": n_bad, "n_pairs": len(pairs),
                   "center_mode": center_mode, "quats": quats,
                   "module_offset_mm": [round(float(v) * 1000, 2) for v in (module_offset_m or (0, 0, 0))],
                   "roi_used": bool(roi_map), "n_roi": len(roi_map), "roi_pad_px": roi_pad_px,
                   "pairing": "ROI内运动域质心 ↔ 两帧 TCP 中点 + R·实测模块偏移",
                   "used": used}


def label_session(session_dir, proj, size_m, *, out_root=None, session_out=None, grasp_rule="auto",
                  cls="peg", follow_tol=0.45, device="kinematic", dry=False, jpeg_quality=95,
                  module_offset_m=(0.0, 0.0, 0.0), use_roi=True, roi_pad_px=6.0):
    """**S2 批量自动标注**: 一个会话 (frames/*.jpg + truth.jsonl) → YOLO 标签 (annotator=auto:kinematic)。

    每一帧: 3D 真值 (TCP+四元数) + **实测模块偏移** + 模块物理尺寸 → 8 角点投影 → AABB 框 (class=peg)
            抓取门 (优先用夹爪真值; 没有发布者时用「预测位置附近的随动」判据) → 未确认**不发标签**
            落盘复用 yolo_annot_dataset.save_sample → 与人工样本同结构 → 可进训练集 (永不进 val)

    proj : 3x4 投影矩阵 (numpy) 或 models/real_cam_proj.json 路径
    module_offset_m : **模块几何中心相对 TCP** 的实测偏移 (工具系, 米)。不给就按 0 (盒体中心=TCP),
                      此时若实际有偏移, 框会整体偏 —— 所以要用 --module-offset 给实测量, 不猜。
    dry  : True 只统计不落盘
    返回 report dict (n_frame / n_labeled / 跳过原因分布 / 每帧明细)
    """
    if not isinstance(proj, (list, tuple)) and not hasattr(proj, "shape"):
        proj, _meta = load_proj(proj)
        if proj is None:
            raise ValueError("投影矩阵不可用 — 先跑 --probe/--fit 生成 models/real_cam_proj.json")
    P = np.asarray(proj, float).reshape(3, 4)

    import cv2
    frames = sorted(glob.glob(os.path.join(session_dir, "frames", "*.jpg")))
    truth, n_bad = load_truth_map(os.path.join(session_dir, "truth.jsonl"))
    rep = {"session": os.path.basename(os.path.normpath(session_dir)), "n_frame": len(frames),
           "n_truth": len(truth), "n_bad_truth": n_bad, "grasp_rule": grasp_rule,
           "size_mm": [round(s * 1000, 2) for s in size_m], "cls": cls, "dry": bool(dry),
           "out_root": out_root, "session_out": session_out, "skipped": {}, "items": [], "n_labeled": 0,
           "module_offset_mm": [round(float(v) * 1000, 2) for v in module_offset_m]}
    roi_map, n_bad_roi = load_roi_map(session_dir) if use_roi else ({}, 0)
    rep["use_roi"] = bool(use_roi)
    rep["n_roi"] = len(roi_map)
    rep["n_bad_roi"] = n_bad_roi
    wh, prev_img, prev_tcp, prev_roi, prev_quat = None, None, None, None, None

    def _skip(reason):
        rep["skipped"][reason] = rep["skipped"].get(reason, 0) + 1

    for fp in frames:
        stem = os.path.splitext(os.path.basename(fp))[0]
        img = cv2.imread(fp)
        if img is None:
            _skip("读图失败")
            continue
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        if wh is None:
            wh = (img.shape[1], img.shape[0])
        t = truth.get(stem, {}).get("truth", {})
        tcp, quat = t.get("tcp"), t.get("tcp_quat")
        roi = roi_map.get(stem)
        if roi is not None and roi_pad_px:
            roi = [roi[0] - roi_pad_px, roi[1] - roi_pad_px, roi[2] + roi_pad_px, roi[3] + roi_pad_px]
        if roi is None and roi_map:
            _skip("该帧无模块区域(ROI) → 保守不发标签")
            prev_img, prev_tcp, prev_roi, prev_quat = img, tcp, None, quat
            continue

        # ① 真值/几何前置
        if not tcp:
            _skip("无 TCP 真值")
            prev_img, prev_tcp, prev_roi, prev_quat = img, tcp, roi, quat
            continue
        center = module_center(tcp, quat, module_offset_m)
        box = box_from_3d(P, center, quat, size_m, wh)
        if box is None:
            _skip("框退化/出画 (模块不在视野)")
            prev_img, prev_tcp, prev_roi, prev_quat = img, tcp, roi, quat
            continue
        # ② 抓取门: 夹爪真值优先; 没有发布者时用「预测位置附近的随动」(不是全图最大域)
        g = grasp_from_truth(t)
        info = {}
        if grasp_rule == "off":
            gate, greason = True, "抓取门已显式关闭 (--no-grasp-gate)"
        elif g is True:
            gate, greason = True, "夹爪/阶段真值 = 抓取成立"
        elif g is False:
            gate, greason = False, "夹爪真值 = 未闭合"
        elif prev_img is not None and prev_tcp:
            # 半径 = 模块框对角线的 0.75 倍 (至少 24px); 有 ROI 时再叠加 ROI 限制
            radius = max(24.0, 0.75 * math.hypot(box[2] - box[0], box[3] - box[1]))
            _uv, _area, _pred, _n, info = motion_near(P, prev_img, img, prev_tcp, tcp,
                                                      quat=quat_slerp(prev_quat, quat, 0.5),
                                                      module_offset_m=module_offset_m, radius_px=radius,
                                                      roi=(_roi_union(prev_roi, roi)
                                                           if (prev_roi or roi) else None))
            if info.get("ok") is True:
                gate = True
                greason = f"随动判据: 质心距预测 {info['d_pred_px']}px ≤ 容差 {info['tol_px']}px"
            else:
                gate = False
                greason = "随动判据: " + str(info.get("why") or
                                             f"质心偏离预测 {info.get('d_pred_px')}px > 容差 {info.get('tol_px')}px")
        else:
            gate, greason = False, "既无夹爪真值也无上一帧 → 无随动证据, 不发标签"
        if not gate:
            _skip(f"抓取未确认 ({greason[:48]})")
            rep["items"].append({"stem": stem, "labeled": False, "why": greason, "gate": info})
            prev_img, prev_tcp, prev_roi, prev_quat = img, tcp, roi, quat
            continue
        # ③ 落盘
        item = {"stem": stem, "labeled": True, "box_px": [round(float(v), 2) for v in box],
                "grasp": greason, "gate": info}
        if not dry:
            try:
                import yolo_annot_dataset as yad
                rec = yad.save_sample(out_root, img, [(box[0], box[1], box[2], box[3], cls)],
                                      device=device, src="kinematic_autolabel", session=session_out,
                                      annotator="auto:kinematic", tag="kin",
                                      extra={"truth": t, "kinematic": {"proj_rms_px": rep.get("proj_rms_px"),
                                                                       "size_mm": rep["size_mm"],
                                                                       "grasp": greason}},
                                      jpeg_quality=jpeg_quality)
                item["saved_stem"] = rec["stem"]
            except Exception as e:                                            # noqa: BLE001
                _skip(f"落盘失败: {type(e).__name__}")
                item["labeled"] = False
                item["why"] = f"落盘失败: {e}"
        rep["n_labeled"] += int(item["labeled"])
        rep["items"].append(item)
        prev_img, prev_tcp, prev_roi, prev_quat = img, tcp, roi, quat
    return rep


def selftest():
    """数学核自检: 造已知 P → 反解 → 断言 (真跑, 不是口头)"""
    rng = np.random.default_rng(7)
    K = np.array([[610.0, 0, 318.0], [0, 607.0, 242.0], [0, 0, 1.0]])
    R = quat_to_R([0.7664547, 0.0754595, 0.6154991, 0.1673735])
    t = np.array([0.25, -0.18, 0.62])
    P_true = K @ np.hstack([R, t.reshape(3, 1)])
    pts3 = np.column_stack([rng.uniform(0.30, 0.70, 12), rng.uniform(-0.20, 0.20, 12),
                            rng.uniform(0.10, 0.45, 12)])
    pairs = [(p, project(P_true, p)) for p in pts3]
    P_hat, rms = fit_proj(pairs)
    K_est = decompose_K(P_hat)
    ok = rms < 1e-6 and abs(K_est["fx"] - 610.0) < 1.0 and abs(K_est["fy"] - 607.0) < 1.0
    print(f"[selftest] 12 对点 → DLT 反解: rms = {rms:.3e} px")
    print(f"[selftest] 还原内参: fx={K_est['fx']:.3f} (真 610) fy={K_est['fy']:.3f} (真 607)"
          f" cx={K_est['cx']:.2f} (真 318) cy={K_est['cy']:.2f} (真 242)")
    # 抗噪: 1px 像素噪声下残差应≈噪声量级
    noisy = [(x, uv + rng.normal(0, 1.0, 2)) for x, uv in pairs]
    _, rms_n = fit_proj(noisy)
    print(f"[selftest] 加 1px 高斯噪声: rms = {rms_n:.3f} px (应≈1.0, 说明不放大误差)")
    # 框生成: 取一个**必定在画面内**的点 (沿光轴 0.45m 处), 绕**相机光轴**转 90° 后框宽高应互换。
    # 用薄片 (厚度 0) 做这个检查 —— 有厚度时 AABB 会被沿光轴的深度分量污染, 宽高不是简单互换 (不是 bug)。
    C = -R.T @ t                                        # 相机中心 (base_link)
    c = C + R.T @ np.array([0.0, 0.0, 0.45])
    q0 = [0, 0, 0, 1.0]
    ax = R.T @ np.array([0.0, 0.0, 1.0])
    ax = ax / np.linalg.norm(ax)
    ang = math.pi / 2
    q90 = [float(ax[0] * math.sin(ang / 2)), float(ax[1] * math.sin(ang / 2)),
           float(ax[2] * math.sin(ang / 2)), math.cos(ang / 2)]
    thin = (0.040, 0.016, 0.0)
    b0 = box_from_3d(P_true, c, q0, thin, (640, 480))
    b90 = box_from_3d(P_true, c, q90, thin, (640, 480))
    print("[selftest] 测试点投影 =", np.round(project(P_true, c), 1), "(应在 640x480 内)")
    if b0 is None or b90 is None:
        print("[selftest] ❌ 框生成返回 None (点不在画面内) — 测试用例设计问题")
        return 1
    w0, h0 = b0[2] - b0[0], b0[3] - b0[1]
    w90, h90 = b90[2] - b90[0], b90[3] - b90[1]
    print(f"[selftest] 框生成(薄片): 0° 框 {w0:.1f}x{h0:.1f}px · 绕光轴转90° 后 {w90:.1f}x{h90:.1f}px (应换过来)")
    ok = ok and abs(w0 - h90) < max(3.0, 0.15 * h90) and abs(h0 - w90) < max(3.0, 0.15 * w90)
    print("[selftest] 判定:", "✅ 通过 (DLT 精确可逆 + 噪声不放大 + 姿态→框几何自洽)" if ok else "❌ 失败")
    return 0 if ok else 1


def parse_size(s):
    """模块物理尺寸 → 米。接受 "40,16,12" (mm) 或 "0.040,0.016,0.012" (m)。"""
    v = [float(x) for x in str(s).replace("x", ",").split(",") if x.strip()]
    if len(v) != 3:
        raise ValueError("尺寸必须是 3 个数, 形如 40,16,12 (mm)")
    return tuple(x / 1000.0 for x in v) if max(abs(x) for x in v) > 1.0 else tuple(v)


def main():
    ap = argparse.ArgumentParser(description="机器人动作 → 光模块自动标注 (kinematic auto-labeling)")
    ap.add_argument("--selftest", action="store_true", help="数学核自检 (合成真值反解)")
    ap.add_argument("--fit", default=None, help="点对 JSON 文件 → 解投影矩阵")
    ap.add_argument("--probe", default=None, help="探针会话的 frames 目录 → 自动出点对 (配 --truth)")
    ap.add_argument("--truth", default=None, help="该会话的 truth.jsonl")
    ap.add_argument("--roi", default=None, help="模块区域侧车 roi.jsonl (默认取会话目录下的)")
    ap.add_argument("--out", default=PROJ_DEFAULT, help="投影矩阵落盘路径")
    ap.add_argument("--center-mode", default="all", choices=("all", "largest"),
                    help="运动域质心取法: all=全部连通域面积加权 (默认, =两帧中点) / largest=旧最大域 (对照)")
    ap.add_argument("--label", action="store_true", help="(旧) 只做前置校验")
    ap.add_argument("--label-session", default=None, help="S2: 会话目录 → 批量自动标注 (配 --proj/--size)")
    ap.add_argument("--out-root", default=None, help="S2 落盘的数据集根 (默认 repo/data/yolo_annot)")
    ap.add_argument("--session-out", default=None, help="S2 落盘的会话名 (默认 auto_<ts>_kin)")
    ap.add_argument("--grasp-rule", default="auto", choices=("auto", "follow", "off"),
                    help="抓取门: auto=有夹爪真值用真值否则随动 / follow=只用随动 / off=关 (需显式)")
    ap.add_argument("--no-grasp-gate", action="store_true", help="等价于 --grasp-rule off (显式承担风险)")
    ap.add_argument("--report", default=None, help="S2 报告落盘路径 (json)")
    ap.add_argument("--dry-run", action="store_true", help="S2 只统计不落盘")
    ap.add_argument("--proj", default=PROJ_DEFAULT)
    ap.add_argument("--size", default=None, help="模块物理尺寸 mm, 形如 40,16,12 (也给小数米制)")
    ap.add_argument("--module-offset", default=None,
                    help="模块几何中心相对 TCP 的**实测**偏移 mm, 形如 0,0,-36 (不给=0, 有偏移就会整体偏框)")
    a = ap.parse_args()

    if a.selftest:
        return selftest()
    if a.probe:
        sdir = os.path.dirname(os.path.normpath(a.probe))            # frames 的父目录 = 会话目录
        roi_map, n_bad_roi = load_roi_map(a.roi or sdir)
        if a.roi or roi_map:
            print(f"模块区域侧车: {len(roi_map)} 条 (坏行 {n_bad_roi}) · 来源 {a.roi or os.path.join(sdir, 'roi.jsonl')}")
        moff = parse_size(a.module_offset) if a.module_offset else None
        pairs, info = probe_pairs_from_session(a.probe, a.truth, a.out, center_mode=a.center_mode,
                                               module_offset_m=moff, roi_map=roi_map)
        info["used"] = info["used"][:24]
        print(json.dumps(info, ensure_ascii=False, indent=1))
        if len(pairs) < 6:
            print(f"❌ 只凑到 {len(pairs)} 对, DLT 需要 ≥6 对 — 探针运动请多走几个位姿 (覆盖画面四角+中心)")
            return 1
        P0, rms0 = fit_proj(pairs)
        print(f"① 朴素解 (3D=TCP中点, 偏移按 0): rms={rms0:.3f}px")
        P, off, rms, hist = fit_proj_offset(pairs, info.get("quats") or [], ret_hist=True)
        print(f"② 联合解 (P, 工具系偏移): rms={rms:.3f}px · off=({off[0]*1000:.1f}, {off[1]*1000:.1f}, "
              f"{off[2]*1000:.1f})mm · 迭代 {hist}")
        if rms0 > 2.0 and rms <= 2.0:
            print("   → 朴素解超差而联合解达标: 画面里的运动主体不是 TCP 本身 "
                  "(夹爪/合成体), 已按刚性偏移吸收 (这正是不用棋盘格也能标定的原因)")
        chk = probe_design_check(pairs)
        print("位姿可辨识性预检:", json.dumps(chk, ensure_ascii=False))
        if not chk["ok"]:
            print("❌ 探针位姿退化 → **不落盘** (否则会把只在平面内有效的 P 当标定用):")
            print("   ", chk["why"])
            return 1
        d = save_proj(a.out, P, len(pairs), rms,
                      extra={"center_mode": a.center_mode, "design_check": chk,
                             "rms_naive_px": round(rms0, 3),
                             "tool_offset_mm": [round(float(v) * 1000, 2) for v in off]})
        print(f"✅ 解出投影矩阵: rms={rms:.3f}px · {a.out}")
        print("   内参估计:", d["K_est"], "valid =", d["K_est_valid"])
        return 0
    if a.fit:
        raw = json.load(open(a.fit, encoding="utf-8"))
        pairs = [(p["xyz"], p["uv"]) for p in raw]
        P, rms = fit_proj(pairs)
        d = save_proj(a.out, P, len(pairs), rms)
        print(f"✅ rms={rms:.3f}px → {a.out} · K_est={d['K_est']}")
        return 0
    if a.label_session:
        if not a.size:
            print("❌ --label-session 必须给 --size (模块实测物理尺寸 mm) — 框大小不能猜")
            return 1
        try:
            size_m = parse_size(a.size)
        except ValueError as e:
            print(f"❌ --size 解析失败: {e}")
            return 1
        out_root = a.out_root or os.path.join(_REPO, "data", "yolo_annot")
        sess = a.session_out or ("auto_" + time.strftime("%y%m%d_%H%M%S") + "_kin")
        rule = "off" if a.no_grasp_gate else a.grasp_rule
        P, meta = load_proj(a.proj)
        if P is None:
            print(f"❌ 投影矩阵不可用 ({a.proj}) — 先跑 --probe/--fit")
            return 1
        moff = parse_size(a.module_offset) if a.module_offset else (0.0, 0.0, 0.0)
        rep = label_session(a.label_session, P, size_m, out_root=out_root, session_out=sess,
                            grasp_rule=rule, dry=a.dry_run, module_offset_m=moff)
        rep["proj"] = {"path": a.proj, "rms_px": meta.get("rms_px"), "center_mode": meta.get("center_mode")}
        print(json.dumps(rep, ensure_ascii=False, indent=1))
        if a.report:
            os.makedirs(os.path.dirname(os.path.abspath(a.report)), exist_ok=True)
            json.dump(rep, open(a.report, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print("📄 报告:", a.report)
        return 0 if rep["n_labeled"] > 0 else 1
    if a.label:
        P, meta = load_proj(a.proj)
        if P is None:
            print(f"❌ 投影矩阵不可用 ({a.proj}) — 先跑 --probe/--fit")
            return 1
        if not a.size:
            print("❌ --label 必须给 --size (模块实测物理尺寸 mm) — 框大小不能猜")
            return 1
        print("ℹ️ 真正的批量标注请用 --label-session <会话目录> (本开关只做前置校验):")
        print("   proj rms =", meta.get("rms_px"), "px · size =", a.size, "· 抓取判据 = 夹爪真值 / 图像随动")
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
