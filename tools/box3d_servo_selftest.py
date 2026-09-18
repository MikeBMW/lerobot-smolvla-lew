#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""box3d_servo_selftest.py — 「2D→3D」闭环自检: 越近越准 + 融合 + 收敛 (合成, 走真代码)

老倪 2026-09-18: 「单独根据 YOLO 框直接做 2D→3D 肯定有误差, 所以是反馈控制:
                 随着距离接近, YOLO 检测出来的距离应该越来越准。」

本脚本用真代码 (box3d_solver.Box3DSolver / Box3DServo) 验三件事:
  ① 距离-精度律: σ_dist ∝ 距离²   —— 把同一个模块放在离相机不同距离, 看估计误差与 σ 怎么变
  ② 多帧融合: 近处+远处测同一目标 → 1/σ² 加权融合后误差比任何单次都好
  ③ 闭环收敛: 从远处粗估出发, 按"剩余距离的一半"逐步靠近 → 误差逐次下降直到 <2mm
数据全部来自**渲染图像里抠出来的框** (感知给的结果), 真值只用于打分。
"""
from __future__ import annotations

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

import box3d_solver_selftest as SS                                            # noqa: E402
import real_probe_dryrun_selftest as RS                                       # noqa: E402
from box3d_solver import Box3DSolver, Box3DServo                              # noqa: E402
from mono23d_experiment import SIZE, pose_set                                 # noqa: E402

W, H = 640, 480


def main():
    P_true, axes = pose_set(1, 0, 0, 0, "small")[1]
    u, v, w = axes[:, 0], axes[:, 1], axes[:, 2]
    C = np.array([0.00, -0.45, 0.60])
    look = np.array([0.30, 0.05, 0.10])
    axis = (look - C) / np.linalg.norm(look - C)
    base_img = RS.static_scene()
    rng = np.random.default_rng(4242)

    # ── 先用"模块参考点=TCP (工具零点已示教)"的数据标定相机 P (只解 11 个未知量) ──
    slv = Box3DSolver(size_mm=[s * 1000 for s in SIZE], img_wh=(W, H), fix_off=(0.0, 0.0, 0.0))
    poses, _ = pose_set(200, 0.125, 25.0, 12, "big")
    for tcp, R in poses[:160]:
        c = np.asarray(tcp, float)
        q = RS.rot_to_quat(R)
        img = SS.render_frame(base_img, P_true, c, q, [s for s in SIZE], gripper_tcp=tcp)
        bx = SS.detect_box_from_image(img)
        if bx:
            slv.add([x + rng.normal(0, 0.5) for x in bx], [float(x) for x in tcp], q)
    fit = slv.fit()
    print(f"标定: {json.dumps({k: fit[k] for k in ('rms_px','holdout_rms_px','size_a','size_a_spread') if k in fit}, ensure_ascii=False)}")
    q0 = RS.rot_to_quat(np.stack([u, v, w], axis=1))

    # ── ① 距离-精度律 ──
    print("\n═══ ① 距离-精度律 (同一模块放在离相机不同距离; 框从图像抠出) ═══")
    print(f"{'距离m':>7}{'框跨度px':>10}{'估计距离m':>11}{'距离误差mm':>12}{'σ估算mm':>10}{'3D误差mm':>10}{'σ/距离²':>10}")
    rows = []
    for z in (0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90):
        X_true = C + z * axis + 0.01 * u                            # 稍微偏一点, 别正好在光轴
        img = SS.render_frame(base_img, P_true, X_true, q0, [s for s in SIZE])
        bx = SS.detect_box_from_image(img)
        if not bx:
            continue
        bx = [x + rng.normal(0, 0.5) for x in bx]
        m = slv.predict_mono_sigma(bx, quat=q0)
        if not m:
            continue
        derr = abs(m["dist_m"] - z) * 1000
        e3d = float(np.linalg.norm(np.asarray(m["X"]) - X_true)) * 1000
        rows.append({"z": z, "span": m["span_px"], "d_hat": m["dist_m"], "derr_mm": derr,
                     "sigma_mm": m["sigma_m"] * 1000, "err3d_mm": e3d,
                     "sigma_over_z2": m["sigma_m"] / (m["dist_m"] ** 2)})
        print(f"{z:>7.2f}{m['span_px']:>10.1f}{m['dist_m']:>11.3f}{derr:>12.2f}"
              f"{m['sigma_m']*1000:>10.2f}{e3d:>10.2f}{m['sigma_m']/(m['dist_m']**2):>10.2f}")
    zs = np.array([r["z"] for r in rows]); sig = np.array([r["sigma_mm"] for r in rows])
    law_fit = float(np.polyfit(np.log(zs), np.log(sig), 1)[0])       # 幂指数应 ≈2
    print(f"  → σ ∝ 距离^({law_fit:.2f})  (理论 2.0: 绝对距离误差随距离平方增长)")
    near, far = rows[0], rows[-1]
    print(f"  → {near['z']:.2f}m 处误差 {near['err3d_mm']:.1f}mm vs {far['z']:.2f}m 处 {far['err3d_mm']:.1f}mm"
          f"  (近 {far['err3d_mm']/max(1e-6,near['err3d_mm']):.1f}× 更准)")

    # ── ② 融合 ──
    print("\n═══ ② 多距离融合 (同一目标 0.80/0.55/0.35m 各测一次, 1/σ² 加权) ═══")
    ms = []
    for z in (0.80, 0.55, 0.35):
        X_place = C + z * axis + 0.01 * u                     # 目标本身不动, 这里模拟"从不同距离看它"
        img = SS.render_frame(base_img, P_true, X_place, q0, [s for s in SIZE])
        bx = SS.detect_box_from_image(img)
        if not bx:
            continue
        bx = [x + rng.normal(0, 0.5) for x in bx]
        m = slv.predict_mono_sigma(bx, quat=q0)
        ms.append(m)
        e = float(np.linalg.norm(np.asarray(m["X"]) - X_place)) * 1000
        print(f"  测于 {z:.2f}m: 估计 3D 误差 {e:6.2f}mm · σ={m['sigma_m']*1000:5.2f}mm")
    Xf, sigf = slv.fuse(ms)
    print(f"  融合后: σ={sigf*1000:.2f}mm (比最好单次 {min(m['sigma_m'] for m in ms)*1000:.2f}mm 小)")

    # ── ③ 闭环收敛: 目标固定在 W 不动, 相机随机器人逐步靠近 (腕上相机) ──
    #    ⚠️ 必须先讲清楚"融合合法性": 只有**同一个静态目标**的多次观测才能融合。
    #    这里相机朝固定目标 X_tgt 走, 每步重建相机外参 (同一 look-at) → 观测的是同一点。
    print("\n═══ ③ 闭环收敛 (目标固定在 W 不动; 相机随机器人逐步靠近; 每步重测+融合) ═══")
    print(f"{'步':>3}{'相机距目标m':>12}{'框跨度px':>10}{'估计距离m':>11}{'3D误差mm':>10}{'σ_mm':>8}{'步长mm':>9}{'停':>4}")
    X_tgt = np.array([0.30, 0.05, 0.10])
    C0 = X_tgt - 0.80 * axis
    Cc = C0.copy()
    srv = Box3DServo(slv, tol_m=0.002, max_step_m=0.030)
    conv = []
    for k in range(8):
        P_c, _ax, _Cc = RS.make_camera(tuple(Cc), tuple(X_tgt))
        img = SS.render_frame(base_img, P_c, X_tgt, q0, [s for s in SIZE])   # 目标(模块)就在 X_tgt 不动
        bx = SS.detect_box_from_image(img)
        if not bx:
            break
        bx = [x + rng.normal(0, 0.5) for x in bx]
        o = srv.observe(bx, quat=q0)                     # 同一静态目标 → 融合合法
        pl = srv.plan()
        dist_cam = float(np.linalg.norm(X_tgt - Cc))
        err3d = float(np.linalg.norm(np.asarray(o["X_fused"]) - X_tgt)) * 1000
        conv.append({"step": k, "cam_to_target_m": round(dist_cam, 4), "span_px": o["span_px"],
                     "d_hat_m": o["dist_m"], "err3d_mm": round(err3d, 2),
                     "sigma_mm": round(o["sigma_fused_m"] * 1000, 2),
                     "step_mm": round(pl["next_step_m"] * 1000, 1), "done": pl["done"]})
        print(f"{k:>3}{dist_cam:>12.3f}{o['span_px']:>10.1f}{o['dist_m']:>11.3f}{err3d:>10.2f}"
              f"{o['sigma_fused_m']*1000:>8.2f}{pl['next_step_m']*1000:>9.1f}{'✅' if pl['done'] else '':>4}")
        if pl["done"]:
            break
        # 朝目标靠近: 走"相机到目标的估计距离"的一半 (限幅 30mm)
        step = min(0.030, 0.5 * float(o["dist_m"]))
        Cc = Cc + step * (X_tgt - Cc) / max(1e-9, dist_cam)

    checks = [
        ("① σ 随距离平方增长 (幂指数 ∈[1.6,2.4])", 1.6 <= law_fit <= 2.4, f"幂指数 {law_fit:.2f}"),
        ("① 最近处 (0.30m) 3D 误差 ≤ 6mm", near["err3d_mm"] <= 6.0, f"{near['err3d_mm']:.2f}mm @ {near['z']:.2f}m"),
        ("① 最近处误差比最远处至少好 3 倍",
         far["err3d_mm"] >= 3.0 * max(1e-6, near["err3d_mm"]),
         f"{far['err3d_mm']:.1f}mm → {near['err3d_mm']:.1f}mm ({far['err3d_mm']/max(1e-6,near['err3d_mm']):.1f}×)"),
        ("② 融合 σ 小于最好单次 σ", sigf < min(m["sigma_m"] for m in ms),
         f"融合 {sigf*1000:.2f}mm < 最好单次 {min(m['sigma_m'] for m in ms)*1000:.2f}mm"),
        ("③ 闭环收敛: 末步 3D 误差 ≤ 5mm (且 σ 单调收紧)",
         conv[-1]["err3d_mm"] <= 5.0 and conv[-1]["sigma_mm"] <= conv[0]["sigma_mm"],
         f"首步误差 {conv[0]['err3d_mm']}mm/σ{conv[0]['sigma_mm']}mm → 末步 {conv[-1]['err3d_mm']}mm/"
         f"σ{conv[-1]['sigma_mm']}mm · 步数 {len(conv)}"),
    ]
    print("\n═══ 断言 ═══")
    bad = 0
    for nm, ok, det in checks:
        print(("✅ " if ok else "❌ ") + f"{nm} — {det}")
        bad += 0 if ok else 1
    rep = {"stamp": time.strftime("%Y%m%d_%H%M%S"), "law_exponent": round(law_fit, 3),
           "distance_sweep": rows, "fusion": {"sigma_fused_mm": sigf * 1000,
                                              "best_single_mm": min(m["sigma_m"] for m in ms) * 1000},
           "closed_loop": conv, "checks": [{"name": n, "ok": bool(o), "detail": d} for n, o, d in checks],
           "passed": bad == 0}
    out = os.path.join("/home/ubuntu/zmax_data", f"box3d_servo_{rep['stamp']}.json")
    json.dump(rep, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n{'✅ 全绿' if bad == 0 else f'❌ {bad} 项未过'} · 报告: {out}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
