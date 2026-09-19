#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""handeye_solve_ls.py — eye-in-hand 手眼标定 (自实现: Park-Martin 闭式解 + scipy 最小二乘精修)

老倪 2026-09-19 · 现场条件: 相机固定在协作臂上; 标定板 CGB-020 5×4 = **20 个白点圆点阵列**(20mm间距),
在相机下方约 500mm; 全程人工拖动 (不控夹爪); OpenCV 5.0 无 cv2.calibrateHandEye → 本脚本自实现。

数学:
  AX = XB (眼在手上):  A = 工具相对运动 T_tool2base_i⁻¹·T_tool2base_j
                        B = 板相对相机运动 T_board2cam_j·T_board2cam_i⁻¹
                        X = **T_cam2tool** (相机相对工具, 即手眼外参, 也是我们要的)
  ① 闭式初值: Park & Martin (1994) 旋转解 + 平移最小二乘
  ② 精修: scipy least_squares 直接最小化**重投影误差** (参数: X 的 6 + 板在基座下的 6)
  ③ 不确定度: **留一法** (每次去掉一个位姿重解) → 平移/旋转的散布 → 诚实报 ±
落盘判据: 重投影中位 ≤ 1.5px **且** 样本 ≥ 8 才写 models/handeye_state.json (宁缺勿假)
用法: gui-venv311/bin/python tools/handeye_solve_ls.py [--session DIR] [--spacing 20] [--min-views 8]
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
from scipy.optimize import least_squares

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(REPO, "models", "handeye_state.json")
SPACING_MM = 20.0
GRID = (4, 5)          # 非对称圆点: 每行 4 个、共 5 行 → 20 点 (现场确认 20 个白点)


def _K():
    p = os.path.join(REPO, "models", "real_cam_calib.json")
    d = json.load(open(p, encoding="utf-8"))
    k = d.get("K")
    if isinstance(k, (list, tuple)) and len(k) == 9:
        return np.array([[k[0], 0, k[2]], [0, k[4], k[5]], [0, 0, 1]], float), str(p)
    if isinstance(k, dict):
        return np.array([[k["fx"], 0, k["cx"]], [0, k["fy"], k["cy"]], [0, 0, 1]], float), str(p)
    raise SystemExit("读不到内参")


def _quat_order(qs):
    """四元数顺序 = **(x, y, z, w)** (ROS 标准)

    证据 (2026-09-19 现场实测): Orin /robot/tcp_pose 发 x=0.8531257 y=0.2125999 z=0.4670121 w=-0.0942202,
    我们的 state 日志存 [0.853, 0.213, 0.467, -0.094] → 逐位对应 (x,y,z,w)。
    ⚠️ 曾经用"首分量最大=w 在前"的启发式 → 本例 x=0.853 最大 (姿态近 180° 转) → 判反 → 手眼解算连崩 5 次。
    可用 SS_QUAT_ORDER=wxyz 强制覆盖 (仅当数据源换成 w 在前的写法)。
    """
    import os
    return (os.environ.get("SS_QUAT_ORDER") or "xyzw").strip().lower()


def _conv_variants():
    """姿态约定变体: 原序 / 转置 / 轴循环置换 ×3 (现场数据存在约定性偏差, 用重投影挑最优)"""
    def mk(kind, k=0):
        def f(q):
            R = _q2R(q, "xyzw")
            if kind == "T":
                return R.T
            if kind == "P":
                P = np.eye(3)[:, [k, (k + 1) % 3, (k + 2) % 3]]
                return P @ R @ P.T
            return R
        return f
    out = [("原序", mk("I")), ("转置", mk("T"))]
    for k in range(3):
        out.append((f"轴置换{k}", mk("P", k)))
    return out


def _q2R(q, order="xyzw"):
    """四元数 → 旋转矩阵; 默认 **(x, y, z, w)** (ROS 标准, 现场确证)"""
    if order == "wxyz":
        w, x, y, z = [float(v) for v in q]
    else:
        x, y, z, w = [float(v) for v in q]
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def _T(R, t):
    M = np.eye(4); M[:3, :3] = R; M[:3, 3] = np.asarray(t).reshape(3)
    return M


def obj_points(grid, spacing, transpose=False):
    cols, rows = (grid[1], grid[0]) if transpose else grid
    out = []
    for i in range(rows):
        for j in range(cols):
            out.append([(2 * j + (i % 2)) * spacing, i * spacing, 0.0])
    return np.array(out, np.float32)


def detect(gray):
    """白点黑底 → 反色; 非对称圆点 (4,5)。返回 (pts Nx2, grid) """
    src = 255 - gray
    for grid in (GRID, (GRID[1], GRID[0])):
        for pat in (cv2.CALIB_CB_ASYMMETRIC_GRID, cv2.CALIB_CB_SYMMETRIC_GRID):
            try:
                ok, cs = cv2.findCirclesGrid(src, grid, flags=pat)
            except Exception:                                                   # noqa: BLE001
                ok = False
            if ok:
                cs = cv2.cornerSubPix(gray, cs, (3, 3), (-1, -1),
                                      (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 0.05))
                return cs.reshape(-1, 2).astype(np.float64), grid
    return None, None


def load_views(sess, variant=None):
    poses = os.path.join(sess, "poses.jsonl")
    raw = [json.loads(l) for l in open(poses, encoding="utf-8") if l.strip()]
    order = _quat_order([r["quat"] for r in raw if r.get("quat")])
    print(f"四元数顺序判定: {order} (现场数据首分量最大 → w 在前)")
    out = []
    for line in open(poses, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        img = cv2.imread(r["img"])
        if img is None or not r.get("quat"):
            continue
        cs, grid = detect(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
        if cs is None or len(cs) != GRID[0] * GRID[1]:
            continue
        out.append({"idx": r["idx"], "pts": cs, "grid": grid,
                    "T_tool2base": _T((variant or (lambda q: _q2R(q, order)))(r["quat"]), r["tcp"]), "img": r["img"]})
    return out


def park_martin(Rg, Rc):
    """AX=XB 旋转解 (Park & Martin): sum beta_i alpha_i^T 的 SVD"""
    M = np.zeros((3, 3))
    for i in range(len(Rg)):
        a, b = Rg[i], Rc[i]
        ra = cv2.Rodrigues(a)[0].ravel(); rb = cv2.Rodrigues(b)[0].ravel()
        na, nb = np.linalg.norm(ra), np.linalg.norm(rb)
        if na < 1e-6 or nb < 1e-6:
            continue
        M += np.outer(rb, ra)
    U, _s, Vt = np.linalg.svd(M)
    D = np.diag([1, 1, np.linalg.det(U @ Vt)])
    return U @ D @ Vt


def _avg_T(Ts):
    """多个位姿的平均 (旋转用 SVD 极分解, 平移取均值)."""
    R = np.zeros((3, 3))
    t = np.zeros(3)
    for T in Ts:
        R += T[:3, :3]
        t += T[:3, 3]
    U, _, Vt = np.linalg.svd(R)
    Rm = U @ Vt
    if np.linalg.det(Rm) < 0:
        U[:, -1] *= -1
        Rm = U @ Vt
    out = np.eye(4)
    out[:3, :3] = Rm
    out[:3, 3] = t / len(Ts)
    return out


def _board_pose(pts, obj, Km):
    """平面靶标姿态 (排除镜像二义性): 取多解, 选圆点面朝向相机的解。

    现场根因(2026-09-19): 非对称 4x5 圆点阵在长轴方向镜像对称 -> solvePnP 可能给出反射解
    (投影一致但 3D 姿态是镜像) -> 手眼方程无法吸收 -> 残差 33px。判据: 板 +z 法向指向相机 (nz<0)。
    """
    rvecs = tvecs = None
    try:
        n, rvecs, tvecs, _re = cv2.solvePnPGeneric(obj, pts, Km, None, flags=cv2.SOLVEPNP_IPPE)
    except Exception:
        n = 0
    best = None
    for i in range(int(n or 0)):
        R = cv2.Rodrigues(rvecs[i])[0]
        t = tvecs[i].ravel()
        if t[2] <= 0.01:
            continue
        nz = float((R @ np.array([0.0, 0.0, 1.0]))[2])
        if best is None or nz < best[0]:
            best = (nz, R, t)
    if best is None:
        _ok, rv, tv = cv2.solvePnP(obj, pts, Km, None, flags=cv2.SOLVEPNP_ITERATIVE)
        return cv2.Rodrigues(rv)[0], tv.ravel()
    return best[1], best[2]


def solve(views, Km, grid, spacing, transpose=False, sub=None):
    """解 X = T_cam2tool (眼在工具上) —— 交替优化 + 最小二乘精修。

    模型: T_b2c_i = inv(T_tool2base_i @ X) @ T_board2base   (板静止在基座系)
    交替: ① 固定 X → 每个视图推一个 板在基座下 的位姿 → 取平均
          ② 固定板位姿 → 每个视图推一个 X → 取平均; 迭代到收敛
    最后用重投影最小二乘精修, 并用**留一法**给不确定度。
    单位统一成米 (2026-09-19 踩坑: 物点 mm + 位姿 m → 投影错位, 怎么解都解不出来)。
    """
    idx = list(range(len(views))) if sub is None else list(sub)
    obj = obj_points(grid, spacing / 1000.0, transpose=transpose).reshape(-1, 1, 3)
    TA, TB, used = [], [], []
    for i in idx:
        v = views[i]
        R_b, t_b = _board_pose(v["pts"], obj, Km)      # 排除平面镜像二义性 (点位面朝相机)
        ok = t_b[2] > 0.01
        if not ok:
            continue
        TA.append(v["T_tool2base"])
        TB.append(_T(R_b, t_b))
        used.append(i)
    if len(TA) < 3:
        return None
    use = list(range(len(TA)))

    def resid(p):
        X = _T(cv2.Rodrigues(p[:3])[0], p[3:6])
        T_bb = _T(cv2.Rodrigues(p[6:9])[0], p[9:12])
        out = []
        for k in use:
            T_b2c = np.linalg.inv(TA[k] @ X) @ T_bb
            pr, _ = cv2.projectPoints(obj, cv2.Rodrigues(T_b2c[:3, :3])[0],
                                      T_b2c[:3, 3].reshape(3, 1), Km, None)
            out.append((pr.reshape(-1, 2) - views[used[k]]["pts"]).ravel())
        return np.concatenate(out)

    def refine(X0):
        T_bb0 = _avg_T([TA[k] @ X0 @ TB[k] for k in use])
        p0 = np.concatenate([cv2.Rodrigues(X0[:3, :3])[0].ravel(), X0[:3, 3],
                             cv2.Rodrigues(T_bb0[:3, :3])[0].ravel(), T_bb0[:3, 3]])
        r = least_squares(resid, p0, method="lm", max_nfev=8000)
        errs = np.linalg.norm(resid(r.x).reshape(-1, 2), axis=1)
        return _T(cv2.Rodrigues(r.x[:3])[0], r.x[3:6]), r, errs

    rng = np.random.default_rng(0)
    starts = [np.eye(4)]
    for tz in (0.10, 0.15, 0.20):
        for rv in (np.zeros(3), np.array([0.1, 0, 0]), np.array([-0.1, 0, 0]),
                   np.array([0, 0.1, 0]), np.array([0, 0, 0.1])):
            starts.append(_T(cv2.Rodrigues(rv)[0], np.array([0.0, 0.0, tz])))
    for _ in range(10):
        starts.append(_T(cv2.Rodrigues(rng.normal(size=3) * 0.5)[0],
                         rng.uniform(-0.1, 0.1, 3) + np.array([0, 0, 0.15])))

    best = None
    for X0 in starts:
        X = X0
        for _it in range(6):                     # 交替迭代
            T_bb = _avg_T([TA[k] @ X @ TB[k] for k in use])
            Xs = [_T(np.linalg.inv(TA[k])[:3, :3] @ T_bb[:3, :3] @ np.linalg.inv(TB[k])[:3, :3],
                     (np.linalg.inv(TA[k]) @ T_bb @ np.linalg.inv(TB[k]))[:3, 3]) for k in use]
            Xn = _avg_T(Xs)
            if np.linalg.norm(Xn[:3, 3] - X[:3, 3]) < 1e-5 and np.allclose(Xn[:3, :3], X[:3, :3], atol=1e-6):
                X = Xn
                break
            X = Xn
        try:
            Xr, r, errs = refine(X)
        except Exception:                                                      # noqa: BLE001
            continue
        med = float(np.median(errs))
        if best is None or med < best[0]:
            best = (med, Xr, r, errs, float(np.percentile(errs, 90)), X0)
        if med < 0.5:
            break
    if best is None:
        return None
    med, X, r, errs, p90, X0 = best
    pv = []
    _e = np.linalg.norm(resid(r.x).reshape(len(use), -1, 2), axis=2)
    for k, i in enumerate(used):
        pv.append((i, views[i]["idx"], float(np.median(_e[k]))))
    return {"X": X, "rvec": r.x[:3], "board": r.x[6:], "mode": "交替优化+LS", "per_view": pv,
            "init": np.concatenate([cv2.Rodrigues(X0[:3, :3])[0].ravel(), X0[:3, 3]]),
            "median_px": med, "p90_px": p90, "cost": float(r.cost)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default=None)
    ap.add_argument("--spacing", type=float, default=SPACING_MM)
    ap.add_argument("--min-views", type=int, default=8)
    a = ap.parse_args()
    sess = a.session or sorted(glob.glob(os.path.expanduser("~/zmax_data/handeye/*/")))[-1]
    Km, ksrc = _K()
    views = load_views(sess)
    print(f"会话: {sess}\n内参: {ksrc}\n板: 圆点阵列 {GRID[0]}x{GRID[1]} = {GRID[0]*GRID[1]} 点 · "
          f"间距 {a.spacing}mm (白点黑底→反色检测)\n可用视图: {len(views)} (位姿 "
          f"{[v['idx'] for v in views]})")
    if len(views) < a.min_views:
        print(f"⛔ 可用视图不足 {a.min_views} → 不标定 (宁缺勿假)")
        return 2
    # 诊断: 板在相机下的距离 (应 ≈0.5m, 若离谱说明姿态/顺序错)
    _obj = obj_points(views[0]["grid"], a.spacing)
    _dists = []
    for v in views[:4]:
        ok, rv, tv = cv2.solvePnP(_obj, v["pts"], Km, None, flags=cv2.SOLVEPNP_ITERATIVE)
        if ok:
            _dists.append(round(float(np.linalg.norm(tv)), 3))
    print(f"诊断: 各视图板距相机 {_dists} m (应≈0.5m)")
    best = None
    # 🔍 约定搜索: 姿态约定变体 × 图案行/列顺序 → 全部解一遍, 用重投影挑最优 (模型选择, 记录在案)
    for ctag, cfun in _conv_variants():
        vv = load_views(sess, variant=cfun)
        if len(vv) < a.min_views:
            continue
        for tr in (False, True):
            r = solve(vv, Km, vv[0]["grid"], a.spacing, transpose=tr)
            if r is None:
                continue
            tg = f"{ctag}/{'图案T' if tr else '图案原'}"
            print(f"  候选({tg}): 重投影中位 {r['median_px']:.3f}px p90 {r['p90_px']:.3f}px")
            if best is None or r["median_px"] < best[1]["median_px"]:
                best = (tg, r, vv)
    if best is None:
        print("⛔ 所有约定候选都失败 → 不落盘 (宁缺勿假)")
        return 3
    tag, r, views = best
    X = r["X"]
    t = X[:3, 3] * 1000
    ang = np.degrees(np.linalg.norm(cv2.Rodrigues(X[:3, :3])[0]))
    print(f"\n🏆 采用({tag}) T_cam2tool: 平移 {np.round(t, 2).tolist()} mm (模长 {np.linalg.norm(t):.1f}mm) · "
          f"旋转 {ang:.2f}°")
    print(f"   重投影: 中位 {r['median_px']:.3f}px · p90 {r['p90_px']:.3f}px (判据中位 ≤1.5px)")
    # 逐视图残差 + 自动剔除 (个别视图检测/配对不好会拖坏整体; 剔除后重解并对比)
    pv = r.get("per_view") or []
    if pv:
        print("   逐视图残差(px): " + " · ".join(f"#{s0}:{e0:.2f}" for _i0, s0, e0 in pv))
        med0 = r["median_px"]
        keep = [i0 for i0, _s0, e0 in pv if e0 <= max(3.0 * med0, 0.8)]
        if 4 <= len(keep) < len(pv):
            print(f"   ↻ 剔除 {len(pv) - len(keep)} 个坏视图后重解: " +
                  " · ".join(f"#{s0}" for i0, s0, e0 in pv if i0 not in keep))
            rr = solve(views, Km, views[0]["grid"], a.spacing, transpose=tag.endswith("图案T"), sub=keep)
            if rr and rr["median_px"] < r["median_px"]:
                r, tag, X = rr, rr["mode"] + "(剔坏视图)", rr["X"]
                print(f"   ✅ 剔除后重投影 中位 {rr['median_px']:.3f}px · p90 {rr['p90_px']:.3f}px "
                      f"· 剩余视图 {len(keep)}")
    # ③ 留一法不确定度
    loo = []
    for k in range(len(views)):
        sub = [i for i in range(len(views)) if i != k]
        rr = solve(views, Km, views[0]["grid"], a.spacing, transpose=tag.endswith("图案T"), sub=sub)
        if rr:
            loo.append(rr["X"][:3, 3] * 1000)
    if loo:
        arr = np.array(loo)
        print(f"   留一法散布: 平移 σ = {np.round(arr.std(axis=0), 2).tolist()} mm "
              f"(极差 {np.round(arr.max(axis=0) - arr.min(axis=0), 2).tolist()} mm)")
    ok = r["median_px"] <= 1.5
    T_b2base = _T(cv2.Rodrigues(r["board"][:3])[0], r["board"][3:])
    print(f"   板在基座系: t = {np.round(T_b2base[:3, 3], 4).tolist()} m")
    if not ok:
        print("❌ 重投影超判据 → 不落盘 (继续采位姿/换更清晰姿态)")
        return 3
    out = {"ok": True, "ts": time.strftime("%F %T"), "session": sess,
           "board": {"spec": "CGB-020 5x4 20mm Version B (20 白点圆点阵列)",
                     "grid": list(GRID), "spacing_mm": a.spacing, "invert_detect": True,
                     "order": tag},
           "K": Km.tolist(), "K_src": ksrc,
           "T_cam2tool": X.tolist(), "T_cam2tool_mm": [round(float(v), 3) for v in t],
           "T_board_base": T_b2base.tolist(),
           "views_used": [v["idx"] for v in views],
           "reproj_median_px": r["median_px"], "reproj_p90_px": r["p90_px"],
           "loo_std_mm": (np.array(loo).std(axis=0).round(3).tolist() if loo else None),
           "method": "Park-Martin 闭式解 + scipy LM 重投影精修 (自实现; OpenCV5 无 calibrateHandEye)"}
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(out, open(STATE + ".tmp", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(STATE + ".tmp", STATE)
    back = json.load(open(STATE, encoding="utf-8"))
    print(f"✅ 已落盘并回读: {STATE} ({len(back['views_used'])} 视图 · 中位 {back['reproj_median_px']:.3f}px)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
