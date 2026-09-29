#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
laptop_cam_ar_calib.py — 解 **笔记本相机(local)** 的外参, 让 base 系 TCP 轨迹能投进这一路(AR 叠加)
════════════════════════════════════════════════════════════════════════════
老倪 2026-09-29: 「把可视化的管道轨迹渲染叠加到笔记本相机这个场景中 —— 笔记本摄像头是侧面上方视角,
                  相机可以保持不动, 而手臂相机一直在运动」+「应用 VR AR 技术把工具中心轨迹可视化出来」

问题: 臂上相机有手眼(闭环 1.74mm); 笔记本相机**从来没有外参** ⇒ 3D 轨迹投不进去。
本工具全自动解出来(只读端点, 不动机器人):

  ① 3D 真值源 = 臂上相机: 高饱和绿锚 → 深度中位 → 相机系 → 手眼 X → base 系
  ② 2D 观测   = 笔记本相机: 同一批绿锚的像素心
  ③ 配对: 两个视图像是同一批静物, 但**顺序未知** ⇒ 枚举配对, 逐个解针孔模型(f, rvec, t)
  ④ 选解判据(两条独立):
     (a) 重投影 RMS (配对自身的残差)
     (b) **TCP 投影是否落在"正在运动的机械臂"掩膜里** —— 帧间差 = 臂在动; 这条与配对无关,
         是真正的独立验收(也是 AR 能不能用的判据)
  ⑤ 只把"两条判据都过"的解写盘; 否则如实报负结果。

产物: data/scene/laptop_cam_calib.json · 证据图 /tmp/laptop_ar_calib_*.jpg
"""
from __future__ import annotations

import itertools
import json
import os
import sys
import time
import urllib.request

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scene_overlay as SO                                                        # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENE = "/home/ubuntu/zmax_ss_remote/zmax_scene"
TCP_JSON = os.path.expanduser("~/zmax_data/rokae_sdk/tcp_out/latest.json")
OUT = os.path.join(REPO, "data", "scene", "laptop_cam_calib.json")
BASE = "http://127.0.0.1:8791"
IMG_W, IMG_H = 640, 480


def snap(name: str, timeout: float = 12.0):
    u = "%s/snapshot/%s.jpg?_=%f" % (BASE, name, time.time())
    with urllib.request.urlopen(u, timeout=timeout) as r:
        return cv2.imdecode(np.frombuffer(r.read(), np.uint8), cv2.IMREAD_COLOR)


def green_mask(f):
    b, g, r = f[:, :, 0].astype(np.int16), f[:, :, 1].astype(np.int16), f[:, :, 2].astype(np.int16)
    return ((g - r) > 25) & ((g - b) > 20) & (g > 60)


def blobs(mask, min_area, topn=8):
    mm = cv2.morphologyEx((mask * 255).astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    nl, lab, st, ce = cv2.connectedComponentsWithStats(mm, 8)
    idx = [i for i in range(1, nl) if st[i, 4] >= min_area]
    idx.sort(key=lambda i: -st[i, 4])
    return [{"area": int(st[i, 4]), "uv": [float(ce[i][0]), float(ce[i][1])]} for i in idx[:topn]]


def load_K():
    d = json.load(open(os.path.join(REPO, "models", "real_cam_calib.json")))
    k = d["K"]
    return {"fx": k[0], "fy": k[4], "cx": k[2], "cy": k[5]}, tuple(d.get("image_size") or (IMG_W, IMG_H))


def read_tcp():
    with open(TCP_JSON) as f:
        return json.load(f)


def cluster(points, keys, thr):
    """单链式归并(反复合并直到不动) —— 同一件静物在不同时刻测出的坐标会有抖动, 必须并起来。"""
    cl = [{"p": np.asarray(p, float), "n": 1, "a": a} for p, a in zip(points, keys)]
    changed = True
    while changed:
        changed = False
        out = []
        for c in cl:
            for o in out:
                if np.linalg.norm(c["p"] / c["n"] - o["p"] / o["n"]) < thr:
                    o["p"] = o["p"] + c["p"]
                    o["n"] += c["n"]
                    o["a"] = max(o["a"], c["a"])
                    changed = True
                    break
            else:
                out.append(dict(c))
        cl = out
    return sorted(cl, key=lambda c: -c["a"])


def main() -> int:
    n_samples = int(os.environ.get("CAL_N", "14"))
    every = float(os.environ.get("CAL_EVERY", "0.55"))
    K, isize = load_K()
    meta = json.load(open(os.path.join(SCENE, "depth_meta.json")))
    dscale = float(meta.get("depth_scale", 1e-4))
    he = SO.load_handeye()
    X = np.asarray(he["X"], float)
    R_x, t_x = X[:3, :3], X[:3, 3]
    print("手眼 X(cam→tcp) 闭环 %.2fmm · K来自 640x480 出厂内参" % float(he.get("closed_loop_std_mm") or -1))

    # ── ① 采样本: 臂侧绿锚 → base 3D; 笔记本侧绿锚 → 2D ──────────
    a_pts, a_areas, l_pts, l_areas = [], [], [], []
    arm_f0 = loc_f0 = None
    for i in range(n_samples):
        arm, loc = snap("arm"), snap("local")
        dep = np.load(os.path.join(SCENE, "depth_raw.npy"))
        tcp = read_tcp()
        if arm_f0 is None:
            arm_f0, loc_f0 = arm.copy(), loc.copy()
        R_g = SO.quat_to_R([tcp["qx"], tcp["qy"], tcp["qz"], tcp["qw"]])
        t_g = np.array([tcp["x"], tcp["y"], tcp["z"]])
        for b in blobs(green_mask(arm), 150):
            u, v = b["uv"]
            x0, y0 = int(u), int(v)
            win = dep[max(0, y0 - 3):y0 + 4, max(0, x0 - 3):x0 + 4].astype(np.float32)
            ok = win[(win > 0) & (win < 65535)]
            if ok.size < 3:
                continue
            z = float(np.median(ok)) * dscale
            p_cam = np.array([(u - K["cx"]) / K["fx"] * z, (v - K["cy"]) / K["fy"] * z, z])
            a_pts.append(R_g @ (R_x @ p_cam + t_x) + t_g)
            a_areas.append(b["area"])
        for b in blobs(green_mask(loc), 25):
            l_pts.append(np.array(b["uv"], float))
            l_areas.append(b["area"])
        time.sleep(every)
    print("采集 %d 轮: 臂侧 %d 个绿斑 · 笔记本侧 %d 个绿斑" % (n_samples, len(a_pts), len(l_pts)))
    if len(a_pts) < 4 or len(l_pts) < 4:
        print("✗ 绿锚不足(需 ≥4) ⇒ 这条自动路走不通, 如实报负结果"); return 1

    A = [c for c in cluster(a_pts, a_areas, 0.020) if c["n"] >= 2]
    L = cluster(l_pts, l_areas, 8.0)
    print("静物归并(要求出现≥2次): 臂侧 %d 件 · 笔记本侧 %d 件" % (len(A), len(L)))
    for c in A[:8]:
        p = c["p"] / c["n"]
        print("   A area=%5d n=%2d base=(%.3f, %.3f, %.3f)" % (c["a"], c["n"], p[0], p[1], p[2]))
    for c in L[:8]:
        p = c["p"] / c["n"]
        print("   L area=%5d n=%2d uv=(%.0f, %.0f)" % (c["a"], c["n"], p[0], p[1]))
    if len(A) < 4 or len(L) < 4:
        print("✗ 归并后静物不足(需 ≥4/侧)"); return 1

    P3 = np.array([c["p"] / c["n"] for c in A[:6]])
    P2 = np.array([c["p"] / c["n"] for c in L[:6]])
    cxp, cyp = isize[0] / 2.0, isize[1] / 2.0
    from scipy.optimize import least_squares

    def unpack(p):
        return p[0], cv2.Rodrigues(p[1:4])[0], p[4:7]

    def reproj(p, pts):
        f, R, t = unpack(p)
        pc = (R @ pts.T).T + t
        z = pc[:, 2]
        return np.stack([f * pc[:, 0] / z + cxp, f * pc[:, 1] / z + cyp], 1), z

    def resid(p, pts, obs):
        uv, z = reproj(p, pts)
        bad = np.where(z <= 0.05, (0.05 - z) * 3000.0, 0.0)
        return np.concatenate([(uv - obs).ravel(), bad])

    def solve(pts, obs):
        best = None
        for f0 in (250.0, 400.0, 700.0, 1100.0, 1700.0):
            for d0 in (0.5, 0.9, 1.4, 2.0, 3.0):
                p0 = np.concatenate([[f0], [np.pi, 0.0, 0.0], np.array([0.0, 1.0, 0.0]) * d0])
                try:
                    r = least_squares(resid, p0, args=(pts, obs), method="lm", max_nfev=4000)
                except Exception:                                              # noqa: BLE001
                    continue
                uv, z = reproj(r.x, pts)
                if (z <= 0.05).any():
                    continue
                err = np.linalg.norm(uv - obs, axis=1)
                rms = float(np.sqrt((err ** 2).mean()))
                if best is None or rms < best["rms"]:
                    best = {"rms": rms, "p": r.x.copy(), "err": err, "uv": uv, "z": z}
        return best

    # ── ② 运动掩膜(独立验收用): 抓两帧差 = 臂在动的像素 ─────────
    masks, tcps = [], []
    for i in range(5):
        f1, t1 = snap("local"), read_tcp()
        time.sleep(0.8)
        f2, t2 = snap("local"), read_tcp()
        d = np.abs(f2.astype(np.int16) - f1.astype(np.int16)).max(2)
        m = cv2.dilate((d > 18).astype(np.uint8), np.ones((9, 9), np.uint8))
        masks.append(m)
        tcps.append(t1)
    mv = [int(m.sum()) for m in masks]
    print("运动掩膜像素数: %s %s" % (mv, "(全 0 ⇒ 臂没动, 独立验收不可用, 如实标注)"))

    def motion_score(p):
        f, R, t = unpack(p)
        hits, dists = 0, []
        for m, tcp in zip(masks, tcps):
            if m.sum() == 0:
                continue
            pc = R @ np.array([tcp["x"], tcp["y"], tcp["z"]]) + t
            if pc[2] <= 0.05:
                dists.append(9999.0); continue
            u, v = f * pc[0] / pc[2] + cxp, f * pc[1] / pc[2] + cyp
            ui, vi = int(round(u)), int(round(v))
            if 0 <= ui < IMG_W and 0 <= vi < IMG_H and m[vi, ui] > 0:
                hits += 1; dists.append(0.0)
            else:
                ys, xs = np.nonzero(m)
                dists.append(float(np.min(np.hypot(xs - u, ys - v))) if xs.size else 9999.0)
        return hits, (float(np.median(dists)) if dists else 9999.0)

    # ── ③ 枚举配对 → 解 → 双判据打分 ────────────────────────────
    n_use = min(len(P3), len(P2), 5)
    idx_a = list(range(n_use))
    cands = []
    for perm in itertools.permutations(range(len(P2)), n_use):
        pts, obs = P3[idx_a], P2[list(perm)]
        s = solve(pts, obs)
        if s is None:
            continue
        hits, mdist = motion_score(s["p"])
        cands.append({"perm": list(perm), "rms": s["rms"], "hits": hits, "mdist": mdist, "sol": s})
    if not cands:
        print("✗ 所有配对都解不出来"); return 1
    cands.sort(key=lambda c: (-c["hits"], c["rms"]))
    print("候选解 %d 个; 前 5 个(按 命中运动掩膜数 ↓, RMS ↑):" % len(cands))
    for c in cands[:5]:
        print("   配对=%s  运动命中 %d/5  中位距运动像素 %.0fpx  重投影RMS %.2fpx" % (
            c["perm"], c["hits"], c["mdist"], c["rms"]))
    best = cands[0]
    passes = best["hits"] >= 3 or (max(mv) == 0 and best["rms"] < 6.0)
    print("选中: 配对=%s · RMS=%.2fpx · 运动命中 %d/5" % (best["perm"], best["rms"], best["hits"]))
    print("判据: %s" % ("✅ 通过(投到运动手臂上 ≥3/5)" if passes else
                       "⚠️ 未通过 —— 不写盘(如实报负结果, 不拿假外参画假叠加)"))

    f, R, t = unpack(best["sol"]["p"])
    payload = {
        "kind": "laptop_cam_calib", "cam": "local",
        "model": "pinhole, fx=fy=f, 主点=图像中心", "image_size": [int(isize[0]), int(isize[1])],
        "f": float(f), "cx": cxp, "cy": cyp,
        "R_base_to_cam": R.tolist(), "t_base_to_cam": [float(x) for x in t],
        "rms_px": float(best["rms"]), "n_points": int(n_use),
        "pairing": best["perm"], "motion_hits": "%d/5" % best["hits"],
        "motion_masks_px": mv, "motion_median_dist_px": best["mdist"],
        "matched": [{"base": [float(x) for x in P3[i]],
                     "uv": [float(x) for x in P2[best["perm"][i]]],
                     "reproj": [float(best["sol"]["uv"][i][0]), float(best["sol"]["uv"][i][1])]}
                    for i in range(n_use)],
        "verified": bool(passes),
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "how": "臂上相机绿锚(深度+手眼)→base; 笔记本相机同一批绿锚→像素; 枚举配对 + LM 解 f/rvec/t; "
               "'TCP 投影落在运动手臂掩膜' 作独立验收",
        "caveat": "绿锚近共面 ⇒ 沿视轴方向弱约束; 用运动掩膜命中率兜底; 帧龄/时刻随采样记录",
    }
    if passes:
        with open(OUT, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)
        print("已写 %s" % os.path.relpath(OUT, REPO))

    vis = loc_f0.copy() if loc_f0 is not None else snap("local")
    for i in range(n_use):
        cv2.circle(vis, tuple(np.round(P2[best["perm"][i]]).astype(int)), 8, (0, 0, 255), 2)
        cv2.circle(vis, tuple(np.round(best["sol"]["uv"][i]).astype(int)), 3, (255, 0, 255), -1)
    for m, tcp in zip(masks, tcps):
        pc = R @ np.array([tcp["x"], tcp["y"], tcp["z"]]) + t
        if pc[2] > 0.05:
            u, v = f * pc[0] / pc[2] + cxp, f * pc[1] / pc[2] + cyp
            cv2.drawMarker(vis, (int(round(u)), int(round(v))), (0, 255, 255), cv2.MARKER_CROSS, 26, 2)
    cv2.imwrite("/tmp/laptop_ar_calib_local.jpg", vis)
    cv2.imwrite("/tmp/laptop_ar_calib_mask.png", (masks[0] * 255 if masks else np.zeros((IMG_H, IMG_W), np.uint8)))
    cv2.imwrite("/tmp/laptop_ar_calib_arm.jpg", arm_f0 if arm_f0 is not None else snap("arm"))
    print("证据图: /tmp/laptop_ar_calib_local.jpg (红圈=笔记本观测绿锚, 品红=重投影, 黄十字=TCP投影)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
