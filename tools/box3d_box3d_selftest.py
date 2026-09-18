#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""box3d_box3d_selftest.py — 「YOLO 2D 框 → **3D 边界框**」自检 (真值只用于打分, 从不入解算器)

老倪 2026-09-18 晚: 「镜头里已经有一个光模块, YOLO 也检测出来了。完善策略:
                 如何根据当前的光模块 2D 检测, 推算出 3D 边界框。」

3D 边界框 = 中心(3) + 姿态 R(3) + 尺寸(3) + 8 角点。本脚本走**真代码路径**
(`box3d_solver.Box3DSolver.predict_box3d`), 合成场景里逐项打分, 并且故意让夹持有歪斜
(真值 roll/pitch/yaw = 6/-4/12°, 解算器不知道), 用来暴露"歪斜不建模会怎样":

  ① 只解 (P, off)      : 歪斜被 off 吸收 → 中心整体偏多少? (实测 ~77mm)
  ② 联合解 (P,off,R_rel,尺寸): off / R_rel / 尺寸 能不能自己恢复? 3D 边界框误差降到多少?
  ③ 反投影自检          : 投出的 2D 框 vs 检测框 IoU (现场唯一能做的"对不对"的判据)
  ④ 非夹持档 mono_pose  : 工件躺在台面 (中心靠框跨度定距离), 误差与 σ
  ⑤ 未标定降级档        : 必须 mode='fk_only' + gaps 写清缺什么; 无位姿必须拒绝出 3D
  ⑥ 诚实性              : 解算器类里不许出现任何仿真/环境真值符号

用法: gui-venv311/bin/python tools/box3d_box3d_selftest.py [--json OUT.json]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_REPO, "src", "lerobot", "policies", "yolo_3d"))

import real_probe_dryrun_selftest as RS                                        # noqa: E402
from box3d_solver_selftest import detect_box_from_image, iou, render_frame    # noqa: E402
from mono23d_experiment import OFF_TRUE, SIZE, pose_set                        # noqa: E402
from box3d_solver import Box3DSolver, _corners_R, _R_euler                     # noqa: E402

W, H = 640, 480
RREL_TRUE_DEG = (6.0, -4.0, 12.0)          # 夹持歪斜真值 (roll/pitch/yaw)
OFF_TRUE_MM = [round(float(v) * 1000, 1) for v in OFF_TRUE]


def build_samples(n=200):
    """攒 (框, TCP, 姿态, 真值3D框) —— 框从**渲染图像**抠轮廓 + 0.5px 噪声 (不是真值投影)"""
    P_true, _axes = pose_set(1, 0, 0, 0, "small")[1]
    poses, _ = pose_set(n, 0.125, 25.0, 12, "big")
    rng = np.random.default_rng(2026)
    base = RS.static_scene()
    Rrel = _R_euler([math.radians(v) for v in RREL_TRUE_DEG])
    size_m = [float(s) for s in SIZE]
    out = []
    for tcp, R_tool in poses:
        R_box = R_tool @ Rrel
        c_true = np.asarray(tcp, float) + R_tool @ OFF_TRUE
        img = render_frame(base, P_true, c_true.tolist(), RS.rot_to_quat(R_box), size_m, gripper_tcp=tcp)
        bx = detect_box_from_image(img)
        if bx is None:
            continue
        bx = [v + rng.normal(0, 0.5) for v in bx]
        out.append({"box": bx, "tcp": [float(v) for v in tcp], "quat": RS.rot_to_quat(R_tool),
                    "center_true": c_true.tolist(), "R_box_true": R_box,
                    "corners_true": [list(p) for p in _corners_R(c_true, R_box, size_m)]})
    return out


def corner_err_mm(cp, ct):
    a = np.asarray(cp, float).reshape(8, 3); b = np.asarray(ct, float).reshape(8, 3)
    return [float(np.linalg.norm(x - y)) * 1000.0 for x, y in zip(a, b)]


def R_err_deg(Ra, Rb):
    c = max(-1.0, min(1.0, (np.trace(np.asarray(Ra).T @ np.asarray(Rb)) - 1.0) / 2.0))
    return math.degrees(math.acos(c))


def fit_solver(samples, size_mm, **kw):
    slv = Box3DSolver(size_mm=size_mm, img_wh=(W, H))
    acc = 0
    for s in samples:
        acc += int(slv.add(s["box"], s["tcp"], s["quat"])["ok"])
    return slv, acc, slv.diversity(), slv.fit(**kw)


def score(slv, holdout, tag, size_true_mm):
    e_c, e_cor, e_cormax, ious, sig_ok, rr_err, sz_err = [], [], [], [], [], [], []
    modes = {}
    for s in holdout:
        r = slv.predict_box3d(s["box"], tcp=s["tcp"], quat=s["quat"])
        modes[r["mode"]] = modes.get(r["mode"], 0) + 1
        if r["mode"] != "held":
            continue
        e = float(np.linalg.norm(np.asarray(r["center"]) - np.asarray(s["center_true"]))) * 1000
        e_c.append(e)
        ce = corner_err_mm(r["corners8"], s["corners_true"])
        e_cor.append(float(np.median(ce))); e_cormax.append(float(max(ce)))
        ious.append(iou(r["box2d_reproj"], s["box"]))
        rr_err.append(R_err_deg(np.asarray(r["R"]), s["R_box_true"]))
        sz_err.append(max(abs(a - b) for a, b in zip(r["size_mm"], size_true_mm)))
        if r["sigma_mm"] and r["sigma_mm"].get("total"):
            sig_ok.append(e <= 2.0 * float(r["sigma_mm"]["total"]))
    d = {"mode_hist": modes, "n_held": len(e_c),
         "center_mm_median": round(float(np.median(e_c)), 2) if e_c else None,
         "center_mm_max": round(float(max(e_c)), 2) if e_c else None,
         "corner_mm_median": round(float(np.median(e_cor)), 2) if e_cor else None,
         "corner_mm_max": round(float(max(e_cormax)), 2) if e_cormax else None,
         "R_err_deg_median": round(float(np.median(rr_err)), 2) if rr_err else None,
         "size_err_mm_max": round(float(max(sz_err)), 2) if sz_err else None,
         "iou_median": round(float(np.median(ious)), 3) if ious else None,
         "iou_min": round(float(min(ious)), 3) if ious else None,
         "sigma_covers_pct": round(100.0 * sum(sig_ok) / max(1, len(e_c)), 1) if sig_ok else None}
    print(f"\n[{tag}] 留出 {len(holdout)} 帧 · mode={modes}")
    print(f"   中心误差 中位 {d['center_mm_median']}mm / 最大 {d['center_mm_max']}mm · "
          f"**8 角点** 中位 {d['corner_mm_median']}mm / 最大 {d['corner_mm_max']}mm")
    print(f"   姿态误差 中位 {d['R_err_deg_median']}° · 尺寸最大偏差 {d['size_err_mm_max']}mm · "
          f"反投影 IoU 中位 {d['iou_median']} (最小 {d['iou_min']}) · σ 覆盖 {d['sigma_covers_pct']}%")
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=None)
    ap.add_argument("--n", type=int, default=200)
    args = ap.parse_args()
    stamp = time.strftime("%Y%m%d_%H%M%S")
    size_true_mm = [round(s * 1000, 1) for s in SIZE]
    out = {"stamp": stamp, "rrel_true_deg": list(RREL_TRUE_DEG), "off_true_mm": OFF_TRUE_MM,
           "size_true_mm": size_true_mm, "checks": {}}
    samples = build_samples(args.n)
    train, holdout = samples[:160], samples[160:]
    print(f"═══ 2D 框 → 3D 边界框 自检: 合成 {len(samples)} 帧 (框从渲染图像抠轮廓 + 0.5px 噪声)")
    print(f"    真值 (只在打分时用): 夹持偏移 {OFF_TRUE_MM}mm · 夹持歪斜 {list(RREL_TRUE_DEG)}° · "
          f"模块 {size_true_mm}mm")

    # ── ① 只解 (P, off): 歪斜没建模 → off 被吸收 ──
    slv, acc, div, res = fit_solver(train, size_true_mm)
    print(f"\n① 只解 (P,off): 收下 {acc}/{len(train)} · 多样性 ok={div['ok']} tilt={div.get('tilt_deg')}° "
          f"planarity={div.get('planarity')}")
    print(f"   rms={res.get('rms_px')}px 留出={res.get('holdout_rms_px')}px · off={res.get('off_mm')}mm "
          f"(真值 {OFF_TRUE_MM}mm → 偏 {max(abs(a-b) for a,b in zip(res['off_mm'], OFF_TRUE_MM)):.1f}mm)")
    out["checks"]["fit_P_off_only"] = {k: res.get(k) for k in
                                       ("rms_px", "holdout_rms_px", "off_mm", "degenerate")}
    out["checks"]["held_baseline"] = score(slv, holdout, "① 只解(P,off) → 3D 框 (歪斜被吸收)", size_true_mm)

    # ── ② 联合解 (P, off, R_rel, 尺寸) ──
    slv2, acc2, div2, res2 = fit_solver(train, size_true_mm, use_rrel=True, use_scale=True)
    print(f"\n② 联合解 (P,off,R_rel,尺寸): rms={res2.get('rms_px')}px 留出={res2.get('holdout_rms_px')}px")
    print(f"   off={res2.get('off_mm')}mm (偏 {max(abs(a-b) for a,b in zip(res2['off_mm'], OFF_TRUE_MM)):.1f}mm) · "
          f"R_rel={res2.get('rrel_deg')}° (真值 {list(RREL_TRUE_DEG)}°) · "
          f"尺寸={res2.get('size_mm')}mm (偏 {max(abs(a-b) for a,b in zip(res2['size_mm'], size_true_mm)):.2f}mm)")
    out["checks"]["fit_joint"] = {k: res2.get(k) for k in
                                  ("rms_px", "holdout_rms_px", "off_mm", "rrel_deg", "size_mm", "size_src")}
    out["checks"]["held_joint"] = score(slv2, holdout, "② 联合解 → 3D 框", size_true_mm)
    out["checks"]["off_err_mm_baseline"] = round(max(abs(a - b) for a, b in zip(res["off_mm"], OFF_TRUE_MM)), 1)
    out["checks"]["off_err_mm_joint"] = round(max(abs(a - b) for a, b in zip(res2["off_mm"], OFF_TRUE_MM)), 1)

    # ── ③ 非夹持档 (工件躺在台面上) ──
    e_mono, sig_mono, modes = [], [], {}
    for s in holdout:
        r = slv2.predict_box3d(s["box"], tcp=None, quat=s["quat"], held=False)
        modes[r["mode"]] = modes.get(r["mode"], 0) + 1
        if r["ok"] and r["center"]:
            e_mono.append(float(np.linalg.norm(np.asarray(r["center"]) - np.asarray(s["center_true"]))) * 1000)
            if r["sigma_mm"]:
                sig_mono.append(float(r["sigma_mm"]["total"]))
    print(f"\n③ 非夹持档 mono_pose: mode={modes} · {len(e_mono)} 帧 中心误差 中位 "
          f"{np.median(e_mono):.1f}mm · σ 中位 {np.median(sig_mono):.1f}mm")
    out["checks"]["mono_pose"] = {"mode_hist": modes, "n": len(e_mono),
                                  "center_mm_median": round(float(np.median(e_mono)), 2),
                                  "sigma_mm_median": round(float(np.median(sig_mono)), 2)}

    # ── ④ 未标定降级档 (宁缺勿假) ──
    blank = Box3DSolver(size_mm=size_true_mm, img_wh=(W, H))
    s0 = holdout[0]
    r0 = blank.predict_box3d(s0["box"], tcp=s0["tcp"], quat=s0["quat"])
    print(f"\n④ 未标定降级档: mode={r0['mode']} ok={r0['ok']} σ={r0['sigma_mm']}")
    for g in r0["gaps"]:
        print(f"   gap: {g}")
    assert r0["mode"] == "fk_only" and r0["sigma_mm"] is None, "未标定档不许给出可信 σ"
    r1 = blank.predict_box3d(s0["box"])
    assert r1["mode"] == "no_3d" and not r1["ok"], "无位姿无标定必须拒绝出 3D"
    out["checks"]["uncalibrated"] = {"mode": r0["mode"], "ok": r0["ok"], "gaps": r0["gaps"],
                                     "no_pose_mode": r1["mode"]}

    # ── ⑤ 诚实性: 类里不许出现仿真/环境真值符号 ──
    src = open(os.path.join(_REPO, "src", "lerobot", "policies", "yolo_3d", "box3d_solver.py"),
               encoding="utf-8").read()
    cls = src.split("class Box3DSolver")[1].split("class Box3DServo")[0]
    leaked = [k for k in ("_get_obs", "site_xpos", "_freeze_rand_vec", "env.render", "truth") if k in cls]
    out["checks"]["no_truth_leak"] = {"leaked_tokens": leaked, "ok": not leaked}
    print(f"\n⑤ 诚实性: 解算器类里出现的真值符号 = {leaked or '无'} (应为空)")

    out["ok"] = bool(not leaked and r0["mode"] == "fk_only")
    path = args.json or os.path.expanduser(f"~/zmax_data/box3d_box3d_selftest_{stamp}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n证据: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
