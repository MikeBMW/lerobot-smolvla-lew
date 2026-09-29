#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
laptop_cam_solve.py — 笔记本相机外参求解(共用件)
════════════════════════════════════════════════════════════
给 `tools/laptop_cam_ar_calib.py`(自动绿锚) 与 `tools/tcp_ar_server.py`(页面人工标定) 共用,
避免两处各写一套参数化(口径不一致必然漂移)。

模型: 针孔, fx=fy=f, 主点=图像中心(笔记本 UVC 无出厂内参, 这是最省的参数化: 7 参 f+rvec+t)
输入: pts3d (base 系 m, N×3), uv (像素, N×2)
输出: 参数 + 重投影 RMS + 逐点误差 + 相机系 z(<=0 视为不可用)

⚠️ 踩过的坑(2026-09-29 自检抓出来的): 只用"多起点 + LM"会收敛到**退化解**
   (自检里 f 从真值 520 解成 84.6、z 变成 1.4e4 m、RMS 2.4e8 px, 还通过了 z>0 的检查) ——
   因为纯局部优化 + 软惩罚(kink)在 7 维空间里很容易跑飞。
   ⇒ 定式: **先用 DLT 线性解出投影矩阵 P, 再 RQ 分解抽出 (f,R,t) 作初值**, 最后才非线性收细;
     并且**必须做内部自检**(见 selftest()), 不能只看"没报错"。
"""
from __future__ import annotations

import cv2
import numpy as np


def _norm2d(uv):
    c = uv.mean(0)
    d = np.linalg.norm(uv - c, axis=1).mean()
    s = np.sqrt(2.0) / max(d, 1e-9)
    T = np.array([[s, 0, -s * c[0]], [0, s, -s * c[1]], [0, 0, 1.0]])
    return T, np.column_stack([(uv - c) * s, np.ones(len(uv))])


def _norm3d(P):
    c = P.mean(0)
    d = np.linalg.norm(P - c, axis=1).mean()
    s = np.sqrt(3.0) / max(d, 1e-9)
    T = np.eye(4)
    T[0, 0] = T[1, 1] = T[2, 2] = s
    T[:3, 3] = -s * c
    return T, (P - c) * s


def dlt(P, uv):
    """线性 DLT(带 Hartley 归一化) → 3x4 投影矩阵(真实坐标)。点数需 ≥6。"""
    if len(P) < 6:
        return None
    T3, Pn = _norm3d(P)
    T2, un = _norm2d(uv)
    A = []
    for (X, Y, Z), (u, v) in zip(Pn, un[:, :2]):
        A.append([X, Y, Z, 1, 0, 0, 0, 0, -u * X, -u * Y, -u * Z, -u])
        A.append([0, 0, 0, 0, X, Y, Z, 1, -v * X, -v * Y, -v * Z, -v])
    _, _, Vt = np.linalg.svd(np.asarray(A, float))
    Pn_mat = Vt[-1].reshape(3, 4)
    P_mat = np.linalg.inv(T2) @ Pn_mat @ T3
    return P_mat


def decompose(P_mat, img_w, img_h):
    """P → (f, R, t), 主点固定在图像中心。"""
    M = P_mat[:, :3]
    out = cv2.RQDecomp3x3(M)                       # 该版本返回 (retval, K, R)
    K, R = (out[1], out[2]) if len(out) == 3 else (out[0], out[1])
    s = np.linalg.det(K)
    if abs(s) > 1e-12:
        K /= s ** (1.0 / 3.0)
    if K[0, 0] < 0:
        K[:, 0] *= -1
        R[0, :] *= -1
    if K[1, 1] < 0:
        K[:, 1] *= -1
        R[1, :] *= -1
    if np.linalg.det(R) < 0:
        R *= -1
        K *= -1
    f = float((K[0, 0] + K[1, 1]) / 2.0)
    t = np.linalg.inv(K) @ P_mat[:, 3]
    return f, R, t


def solve(pts3d, uv, img_w=640, img_h=480, extra_starts=6, seed=0):
    """多起点(DLT 初值 + 扰动)非线性收细。返回 None 或 dict。"""
    from scipy.optimize import least_squares
    P = np.asarray(pts3d, float).reshape(-1, 3)
    O = np.asarray(uv, float).reshape(-1, 2)
    n = len(P)
    if n < 4 or n != len(O):
        return None
    cxp, cyp = img_w / 2.0, img_h / 2.0

    def reproj(p, pts):
        f = p[0]
        R = cv2.Rodrigues(np.asarray(p[1:4], float))[0]
        t = np.asarray(p[4:7], float)
        pc = (R @ pts.T).T + t
        z = pc[:, 2]
        zz = np.where(np.abs(z) < 1e-6, 1e-6, z)
        return np.stack([f * pc[:, 0] / zz + cxp, f * pc[:, 1] / zz + cyp], 1), z

    def resid(p, pts, obs):
        uvp, _ = reproj(p, pts)
        return (uvp - obs).ravel()

    starts = []
    Pm = dlt(P, O) if n >= 6 else None
    if Pm is not None:
        try:
            f0, R0, t0 = decompose(Pm, img_w, img_h)
            if 50.0 < f0 < 20000.0 and np.isfinite(f0):
                starts.append(np.concatenate([[f0], cv2.Rodrigues(R0)[0].ravel(), t0]))
        except Exception:                                                          # noqa: BLE001
            pass
    rng = np.random.default_rng(seed)
    base = starts[0] if starts else np.concatenate([[600.0], [np.pi, 0.0, 0.0], [0.0, 1.0, 0.0]])
    for _ in range(extra_starts):                       # 在初值附近扰动 + 若干粗猜
        if starts:
            q = base.copy()
            q[0] *= float(rng.uniform(0.6, 1.6))
            q[1:4] += rng.normal(0, 0.25, 3)
            q[4:7] += rng.normal(0, 0.15, 3)
        else:
            q = np.concatenate([[float(rng.uniform(250, 1500))], rng.normal(0, np.pi, 3),
                                rng.normal(0, 1.2, 3)])
        starts.append(q)

    best = None
    for p0 in starts:
        try:
            r = least_squares(resid, p0, args=(P, O), method="trf", x_scale="jac",
                              max_nfev=8000, ftol=1e-12, xtol=1e-12)
        except Exception:                                                          # noqa: BLE001
            continue
        uvp, z = reproj(r.x, P)
        if not np.isfinite(uvp).all() or (z <= 0.02).any():
            continue                                     # 有点在相机后/贴脸 ⇒ 物理上不可用
        err = np.linalg.norm(uvp - O, axis=1)
        rms = float(np.sqrt((err ** 2).mean()))
        if best is None or rms < best["rms_px"]:
            best = {"rms_px": rms, "params": r.x.copy(), "err_px": err.tolist(),
                    "reproj": uvp.tolist(), "z_m": z.tolist()}
    if best is None:
        return None
    f, R, t = best["params"][0], cv2.Rodrigues(best["params"][1:4])[0], best["params"][4:7]
    best.update({"f": float(f), "R": np.asarray(R, float).tolist(),
                 "t": [float(v) for v in t], "cx": cxp, "cy": cyp,
                 "image_size": [int(img_w), int(img_h)], "n_starts": len(starts),
                 "dlt_used": bool(Pm is not None)})
    return best


def project(pts3d, f, R, t, cx, cy):
    """base 3D → 像素。返回 (uv, z_cam); z<=0 的点不该被画。"""
    P = np.asarray(pts3d, float).reshape(-1, 3)
    R = np.asarray(R, float)
    t = np.asarray(t, float)
    pc = (R @ P.T).T + t
    z = pc[:, 2]
    zz = np.where(np.abs(z) < 1e-6, 1e-6, z)
    return np.stack([f * pc[:, 0] / zz + cx, f * pc[:, 1] / zz + cy], 1), z


def tcp_motion_hits(calib, samples):
    """独立验收: 把 TCP 真值投到笔记本画面, 看是否落在"运动中的机械臂"掩膜里。
    samples: [{"mask": np.uint8 HxW, "tcp": [x,y,z]}]
    """
    f, R, t = calib["f"], np.asarray(calib["R_base_to_cam"] if "R_base_to_cam" in calib else calib["R"], float), \
        np.asarray(calib["t_base_to_cam"] if "t_base_to_cam" in calib else calib["t"], float)
    cx, cy = calib["cx"], calib["cy"]
    hits, detail = 0, []
    for s in samples:
        m = s["mask"]
        uv, z = project([s["tcp"]], f, R, t, cx, cy)
        if z[0] <= 0.05:
            detail.append({"inside": False, "reason": "在相机后", "nearest_moving_px": None})
            continue
        u, v = float(uv[0][0]), float(uv[0][1])
        ui, vi = int(round(u)), int(round(v))
        inside = bool(0 <= ui < m.shape[1] and 0 <= vi < m.shape[0] and m[vi, ui] > 0)
        ys, xs = np.nonzero(m)
        near = float(np.min(np.hypot(xs - u, ys - v))) if xs.size else None
        hits += int(inside)
        detail.append({"inside": inside, "uv": [u, v], "nearest_moving_px": near})
    return hits, len(samples), detail


def selftest(verbose=True) -> bool:
    """管线自检: 造一个**物理上合理**的相机(在工位侧上方看着台面) → 投影已知 3D 点 → 反解, 看能否复原。
    (这是**管线自检**, 不是真机标定证据; 真机必须另有'TCP 落在运动手臂掩膜'的独立验收。)"""
    pts3d = np.array([[0.55, 0.05, 0.30], [0.72, 0.28, 0.18], [0.62, -0.10, 0.35],
                      [0.80, 0.15, 0.12], [0.66, 0.34, 0.25], [0.58, 0.22, 0.10],
                      [0.75, -0.02, 0.33], [0.70, 0.10, 0.20]], float)
    C = np.array([0.30, -0.75, 0.55])                        # 相机位置(侧上方, 与现场笔记本位置同量级)
    tgt = np.array([0.70, 0.20, 0.18])
    zc = tgt - C                                             # 相机 +z 轴朝向被看的目标(点在相机前 ⇒ z>0)
    zc = zc / np.linalg.norm(zc)
    xc = np.cross([0.0, 0.0, 1.0], zc)
    xc = xc / np.linalg.norm(xc)
    yc = np.cross(zc, xc)
    R_true = np.stack([xc, yc, zc])                          # 行 = 相机三轴(base 系)
    t_true = -R_true @ C
    uv, ztrue = project(pts3d, 520.0, R_true, t_true, 320.0, 240.0)
    if (ztrue <= 0.05).any():
        if verbose:
            print("自检: ✗ 造的自检相机把点放到相机后面了(z=%s)" % np.round(ztrue, 3).tolist())
        return False
    uv = uv + np.random.default_rng(1).normal(0, 0.6, uv.shape)
    r = solve(pts3d, uv)
    if not r:
        if verbose:
            print("自检: ✗ solve 返回 None")
        return False
    ok = bool(abs(r["f"] - 520.0) / 520.0 < 0.05 and r["rms_px"] < 1.5
              and np.all(np.array(r["z_m"]) > 0.05))
    if verbose:
        print("自检: f 真值520 → 解 %.1f (%.2f%%) · RMS %.2fpx · t 误差 %.1fmm · 相机系 z∈[%.2f,%.2f] ⇒ %s" % (
            r["f"], abs(r["f"] - 520.0) / 520.0 * 100, r["rms_px"],
            float(np.linalg.norm(np.array(r["t"]) - t_true) * 1000),
            min(r["z_m"]), max(r["z_m"]), "✅ 通过" if ok else "⚠️ 未达标"))
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if selftest() else 1)
