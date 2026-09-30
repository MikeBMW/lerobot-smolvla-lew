#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""handeye_solve3.py — 通用手眼标定解算器
用法: python handeye_solve3.py <数据目录> [pitch_mm]

靶标: 4x5 非对称圆阵列（黑底白点 ⇒ 必须反相）
检测: 全图多尺度 + 反相（自适应板位置，应对倾斜导致板移出原裁剪区）
解算: cv2.calibrateHandEye 5 种方法 + 方法间离散度 + 闭环验证（靶标中心在 base 系应处处相同）
"""
import glob
import json
import os
import re
import sys

import cv2
import numpy as np

DIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/scene/he12"
PITCH = float(sys.argv[2]) if len(sys.argv) > 2 else 19.38
K = np.array([[655.06, 0, 637.41], [0, 654.08, 357.77], [0, 0, 1]], dtype=np.float64)
DIST = np.zeros((5, 1))
OBJ = np.array([[2 * c + (r % 2), r, 0.0] for r in range(5) for c in range(4)], dtype=np.float64) * PITCH


def quat_to_R(q):
    qx, qy, qz, qw = q
    n = (qx * qx + qy * qy + qz * qz + qw * qw) ** 0.5
    if n < 1e-9:
        return None
    qx, qy, qz, qw = qx / n, qy / n, qz / n, qw / n
    return np.array([
        [1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
        [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
        [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)]])


def parse_tcp(path):
    s = open(path, encoding="utf-8", errors="replace").read()

    def num(sec, key):
        seg = s.split(sec)[-1] if sec in s else s
        m = re.search(r"\b%s:\s*([-\d.eE+]+)" % key, seg)
        return float(m.group(1)) if m else None
    v = [num("position", "x"), num("position", "y"), num("position", "z"),
         num("orientation", "x"), num("orientation", "y"), num("orientation", "z"), num("orientation", "w")]
    if any(x is None for x in v):
        return None, None
    return np.array(v[:3]) * 1000.0, np.array(v[3:])


def detect(img):
    """自适应：先原裁剪区多尺度，再全图多尺度（板可能因倾斜移位）"""
    H, W = img.shape[:2]
    g0 = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    regions = []
    x0, x1, y0, y1 = max(0, 213 - 60), min(W, 708 + 60), max(0, 341 - 60), min(H, 608 + 60)
    regions.append((g0[y0:y1, x0:x1], np.array([x0, y0]), "裁剪区"))
    regions.append((g0, np.array([0, 0]), "全图"))
    for src, off, nm in regions:
        for z in (2.2, 1.0, 2.0, 3.0):
            g = cv2.resize(src, None, fx=z, fy=z, interpolation=cv2.INTER_CUBIC) if z != 1.0 else src
            for pol, pn in ((cv2.bitwise_not(g), "反相"), (g, "原极性")):
                for pat in ((4, 5), (5, 4)):
                    ok, cc = cv2.findCirclesGrid(pol, pat, flags=cv2.CALIB_CB_ASYMMETRIC_GRID)
                    if ok:
                        pts = cc.reshape(-1, 2).astype(np.float64) / z + off
                        obj = OBJ if pat == (4, 5) else None
                        if obj is None:
                            continue
                        return pts, obj, "%s@%.1fx%s %dx%d" % (nm, z, pn, pat[0], pat[1])
    return None, None, None


rows, fails = [], []
print("══ 目录 %s · 间距 %.2fmm ══" % (DIR, PITCH))
for f in sorted(glob.glob(DIR + "/c_*.png")):
    tag = os.path.basename(f)[2:-4]
    tp = DIR + "/tcp_%s.txt" % tag
    img = cv2.imread(f)
    if img is None or not os.path.exists(tp):
        fails.append((tag, "缺文件")); continue
    pts, obj, how = detect(img)
    if pts is None:
        fails.append((tag, "靶标未检出")); continue
    okp, rv, tv = cv2.solvePnP(obj, pts, K, DIST, flags=cv2.SOLVEPNP_ITERATIVE)
    if not okp:
        fails.append((tag, "PnP失败")); continue
    prj = cv2.projectPoints(obj, rv, tv, K, DIST)[0].reshape(-1, 2)
    rmse = float(np.sqrt(((prj - pts) ** 2).sum(1).mean()))
    p_mm, q = parse_tcp(tp)
    if p_mm is None:
        fails.append((tag, "TCP解析失败")); continue
    R = quat_to_R(q)
    rows.append({"tag": tag, "p": p_mm, "q": q, "Rg": R, "Rt": cv2.Rodrigues(rv)[0],
                 "tt": tv.ravel(), "rmse": rmse, "how": how})
    print("  %-22s rmse=%.3fpx  t_cam_tgt=(%7.1f,%7.1f,%7.1f)  TCP=(%.5f,%.5f,%.5f)  [%s]"
          % (tag, rmse, float(tv.ravel()[0]), float(tv.ravel()[1]), float(tv.ravel()[2]),
             p_mm[0] / 1000, p_mm[1] / 1000, p_mm[2] / 1000, how))
if fails:
    print("  失败 %d 个: %s" % (len(fails), fails))

# 去重（位置<1.5mm 且姿态夹角<0.5° 视为同位姿）
uniq = []
for r in rows:
    dup = None
    for u in uniq:
        dp = float(np.linalg.norm(r["p"] - u["p"]))
        dq = float(np.degrees(2 * np.arccos(min(1.0, abs(float(np.dot(r["q"], u["q"])) / (np.linalg.norm(r["q"]) * np.linalg.norm(u["q"])))))))
        if dp < 1.5 and dq < 0.5:
            dup = u["tag"]; break
    if dup:
        print("  ✗ %-22s 与 %s 重复(Δp=%.2fmm) 剔除" % (r["tag"], dup, float(np.linalg.norm(r["p"] - next(x["p"] for x in uniq if x["tag"] == dup)))))
    else:
        uniq.append(r)

print()
print("══ 独立位姿 %d 个 ══" % len(uniq))
# 旋转多样性诊断（OpenCV 报错的根因就在这里）
if len(uniq) >= 2:
    angs = []
    for i in range(len(uniq)):
        for j in range(i + 1, len(uniq)):
            Rrel = uniq[i]["Rg"].T @ uniq[j]["Rg"]
            angs.append(float(np.degrees(np.arccos(np.clip((np.trace(Rrel) - 1) / 2, -1, 1)))))
    angs = np.array(angs)
    print("  位姿间旋转角: 中位 %.1f° · max %.1f° · **>10°的对数 %d/%d** %s"
          % (np.median(angs), angs.max(), int((angs > 10).sum()), len(angs),
             "✅ 旋转多样性够" if (angs > 10).sum() >= 3 else "⚠ 旋转仍偏少（OpenCV 可能仍报 informational）"))
# ★ 转轴散布诊断（比"旋转角够不够"更本质：手眼必须 ≥2 条不平行转轴）
axis_ok = True
if len(uniq) >= 3:
    axs = []
    for i in range(len(uniq)):
        for j in range(i + 1, len(uniq)):
            Rrel = uniq[i]["Rg"].T @ uniq[j]["Rg"]
            a = float(np.degrees(np.arccos(np.clip((np.trace(Rrel) - 1) / 2, -1, 1))))
            if a < 8:
                continue
            w, V = np.linalg.eig(Rrel)
            k = int(np.argmin(np.abs(w - 1)))
            v = np.real(V[:, k]); v = v / (np.linalg.norm(v) + 1e-12)
            if v[2] < 0:
                v = -v
            axs.append(v)
    if len(axs) >= 2:
        A = np.array(axs)
        d = np.abs(A @ A.T)
        iu = np.triu_indices(len(A), 1)
        au = np.degrees(np.arccos(np.clip(d[iu], -1, 1)))
        axis_ok = np.median(au) > 8
        print("  **转轴散布: 夹角中位 %.1f° · max %.1f°** %s"
              % (np.median(au), au.max(),
                 "✅ 双轴可辨识" if axis_ok else "🔴 **转轴全平行 ⇒ 数学退化，必解不出（需加第二条旋转轴）**"))
if len(uniq) < 3:
    print("  ✗ 不足 3 个，无法解算"); raise SystemExit

Rg = np.array([u["Rg"] for u in uniq]); tg = np.array([u["p"].reshape(3, 1) for u in uniq])
Rt = np.array([u["Rt"] for u in uniq]); tt = np.array([u["tt"].reshape(3, 1) for u in uniq])
res = {}
print()
for nm, fl in (("TSAI", cv2.CALIB_HAND_EYE_TSAI), ("PARK", cv2.CALIB_HAND_EYE_PARK),
               ("HORAUD", cv2.CALIB_HAND_EYE_HORAUD), ("ANDREFF", cv2.CALIB_HAND_EYE_ANDREFF),
               ("DANIILIDIS", cv2.CALIB_HAND_EYE_DANIILIDIS)):
    try:
        R, t = cv2.calibrateHandEye(Rg, tg, Rt, tt, method=fl)
    except Exception as e:
        print("  %-11s ✗ %s" % (nm, str(e)[:70])); continue
    tv_ = t.ravel()
    nrm = float(np.linalg.norm(tv_))
    if nrm > 3000 or nrm < 1.0:      # 退化：过大(十万mm级) 或 几乎为零(Tsai 失败时返回 0)
        print("  %-11s 退化 |t|=%.1fmm 丢弃" % (nm, nrm)); continue
    res[nm] = (R, tv_)
    try:
        eul = np.degrees(cv2.RQDecomp3x3(R)[0])
    except Exception:
        eul = np.array([float("nan")] * 3)
    print("  %-11s t_base_cam=(%7.1f,%7.1f,%7.1f)mm  |t|=%.1fmm  欧拉=(%.1f,%.1f,%.1f)°"
          % (nm, tv_[0], tv_[1], tv_[2], nrm, eul[0], eul[1], eul[2]))

if not res:
    print()
    print("  ✗ 所有方法均退化 ⇒ 位姿旋转仍不足，需再补更大角度的倾斜")
    raise SystemExit

ts = np.array([v[1] for v in res.values()])
print()
print("  方法间离散: 各轴 std = (%.2f, %.2f, %.2f) mm  %s"
      % (ts[:, 0].std(), ts[:, 1].std(), ts[:, 2].std(),
         "✅ 一致（可信）" if ts.std(0).max() < 15 else "⚠ 离散偏大"))

print()
print("══ 闭环验证：靶标中心投到 base 系（9 个位姿应得同一点）══")
best, beststd = None, 1e9
for nm, (R, t) in res.items():
    P = []
    for u in uniq:
        p_cam = u["Rt"] @ OBJ.mean(0) + u["tt"]
        p_tcp = R @ p_cam + t
        P.append(u["Rg"] @ p_tcp + u["p"])
    P = np.array(P)
    sd = float(P.std(0).max())
    print("  %-11s 各轴std=(%6.2f,%6.2f,%6.2f)mm  中心=(%.1f,%.1f,%.1f)mm"
          % (nm, P[:, 0].std(), P[:, 1].std(), P[:, 2].std(), P[:, 0].mean(), P[:, 1].mean(), P[:, 2].mean()))
    if sd < beststd:
        beststd, best = sd, nm

R, t = res[best]
T = np.vstack([np.hstack([R, t.reshape(3, 1)]), [0, 0, 0, 1]])
np.save("/tmp/scene/T_base_cam.npy", T)
json.dump({"method": best, "T_base_cam": T.tolist(), "t_mm": t.tolist(),
           "n_unique_poses": len(uniq), "poses": [u["tag"] for u in uniq],
           "target_rmse_med_px": float(np.median([u["rmse"] for u in uniq])),
           "closed_loop_std_mm": beststd, "pitch_mm": PITCH},
          open("/tmp/scene/handeye_result.json", "w"), indent=1)
print()
print("★★ 最优方法 %s（闭环 std=%.2fmm）→ 已存 T_base_cam.npy + handeye_result.json" % (best, beststd))
print("   T_base_cam 平移 = (%.2f, %.2f, %.2f) mm · |t|=%.2f mm" % (t[0], t[1], t[2], np.linalg.norm(t)))
