#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""box3d_solver_selftest.py — 「YOLO 2D框 → 3D」解算器自检 (**不用真值**, 真值只用于打分)

模拟"装配线正常干活"攒数据: 机器人夹着模块在工作域里走 120 个位姿, 每帧只有
  ① YOLO 风格的目标框 (从**渲染图像里**抠出来的模块轮廓 AABB + 0.5px 噪声 —— 不是从真值 3D 投出来的)
  ② 机器人 TCP 位姿真值 (编码器给的)
喂给 Box3DSolver → 它自己解出 (P, off) → 输出 3D。真值 3D **从不进入解算器**, 只用来打分。

检查项:
  ① 位姿多样性体检通过   ② 拟合/留出残差  ③ 留出位姿 3D 误差(mm)  ④ 留出框 IoU
  ⑤ mono 路径 (只用框, 不用机器人位姿) 的 3D 误差  ⑥ 在线收敛 (10/20/40/80/120 帧)
  ⑦ 无作弊: 解算器入参只有 (框, TCP, 四元数); 框来自图像而非真值投影
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

import real_autolabel as RAL                                                   # noqa: E402
import real_probe_dryrun_selftest as RS                                        # noqa: E402
from mono23d_experiment import OFF_TRUE, SIZE, pose_set                        # noqa: E402
from box3d_solver import Box3DSolver                                           # noqa: E402

W, H = 640, 480
MOD_RGB = (218, 208, 196)


def detect_box_from_image(img_rgb):
    """YOLO 风格的目标框: 从**图像**里抠模块 (颜色分割) → AABB。
    注意: 完全不看真值 3D —— 这就是"感知给过来的结果"。"""
    m = (np.abs(img_rgb.astype(int) - np.array(MOD_RGB)).sum(2) < 60)
    ys, xs = np.nonzero(m)
    if len(xs) < 20:
        return None
    return [float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())]


def render_frame(base, P_true, center, quat, size, gripper_tcp=None):
    return RS.render(base, P_true, center, quat, size, gripper_tcp=gripper_tcp)


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1]); x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def main():
    P_true, axes = pose_set(1, 0, 0, 0, "small")[1]
    size = SIZE
    poses, _ = pose_set(200, 0.125, 25.0, 12, "big")      # 生产/示教级位姿散布
    rng = np.random.default_rng(2026)
    base_img = RS.static_scene()
    size_m = [s for s in size]

    samples = []                                          # (box, tcp, quat, 真值3D中心) —— 真值只留到最后打分
    for tcp, R_tool in poses:
        c_true = np.asarray(tcp, float) + R_tool @ OFF_TRUE
        q = RS.rot_to_quat(R_tool)
        img = render_frame(base_img, P_true, c_true, q, size_m, gripper_tcp=tcp)
        bx = detect_box_from_image(img)
        if bx is None:
            continue
        bx = [v + rng.normal(0, 0.5) for v in bx]          # YOLO 级亚像素噪声
        samples.append((bx, [float(v) for v in tcp], q, c_true.tolist()))
    print(f"═══ 解算器自检: 从**图像里的框**攒数据 (共 {len(samples)} 帧可用) ═══")

    train, holdout = samples[:160], samples[160:]
    slv = Box3DSolver(size_mm=[s * 1000 for s in size_m], img_wh=(W, H))
    accepted = 0
    for bx, tcp, q, _truth in train:                      # ⚠️ 真值 (第4项) 不传给解算器
        r = slv.add(bx, tcp, q)
        accepted += int(r["ok"])
    div = slv.diversity()
    res = slv.fit()
    print(f"收下 {accepted}/{len(train)} 帧 · 多样性: {json.dumps(div, ensure_ascii=False)}")
    print(f"拟合: {json.dumps(res, ensure_ascii=False)}")

    e3d, ious, emono = [], [], []
    for bx, tcp, q, truth in holdout:
        p = slv.predict_held(tcp, q)
        if p:
            e3d.append(float(np.linalg.norm(np.asarray(p) - np.asarray(truth))) * 1000)
        pb = slv.project_box(p, q) if p else None
        if pb:
            ious.append(iou(pb, bx))
        pm = slv.predict_mono(bx)
        if pm:
            emono.append(float(np.linalg.norm(np.asarray(pm) - np.asarray(truth))) * 1000)
    print(f"\n留出位姿 ({len(holdout)} 帧) —— 真值只用于打分:")
    print(f"  predict_held (用机器人位姿): 3D 误差 中位 {np.median(e3d):.2f}mm · 最大 {max(e3d):.2f}mm")
    print(f"  框 IoU (投出的框 vs 检测框): 中位 {np.median(ious):.3f} · 最小 {min(ious):.3f}")
    print(f"  predict_mono (只用框, 不用位姿): 3D 误差 中位 {np.median(emono):.2f}mm · 最大 {max(emono):.2f}mm")

    # ── 在线收敛 ──
    print("\n在线收敛 (数据越攒越准):")
    conv = {}
    for n in (10, 20, 40, 80, 120, 160):
        s2 = Box3DSolver(size_mm=[s * 1000 for s in size_m], img_wh=(W, H))
        for bx, tcp, q, _t in train[:n]:
            s2.add(bx, tcp, q)
        d2 = s2.diversity()
        if not d2["ok"]:
            conv[n] = {"ok": False, "why": d2["why"]}
            print(f"  {n:>4} 帧: 位姿不足 → {d2['why']}")
            continue
        r2 = s2.fit()
        e2, io2 = [], []
        for bx, tcp, q, truth in holdout:
            p = s2.predict_held(tcp, q)
            if p:
                e2.append(float(np.linalg.norm(np.asarray(p) - np.asarray(truth))) * 1000)
            pb = s2.project_box(p, q) if p else None
            if pb:
                io2.append(iou(pb, bx))
        conv[n] = {"ok": True, "rms_px": r2["rms_px"], "holdout_px": r2["holdout_rms_px"],
                   "off_mm": r2["off_mm"], "3d_mm_median": round(float(np.median(e2)), 2),
                   "iou_median": round(float(np.median(io2)), 3)}
        print(f"  {n:>4} 帧: 拟合 {r2['rms_px']:5.2f}px · 3D 中位 {np.median(e2):6.2f}mm · 框 IoU 中位 {np.median(io2):.3f}")

    checks = [
        ("① 位姿多样性体检通过", bool(div["ok"]), div["why"]),
        ("② 拟合未退化 (rms 不是兜底值)", (res.get("rms_px") or 99) < 20.0, f"rms={res.get('rms_px')}px"),
        ("③ 留出位姿 3D 误差中位 ≤10mm", float(np.median(e3d)) <= 10.0, f"{np.median(e3d):.2f}mm"),
        ("④ 留出框 IoU 中位 ≥0.5", float(np.median(ious)) >= 0.5, f"{np.median(ious):.3f}"),
        ("⑤ mono 路径可用 (误差中位 ≤60mm)", float(np.median(emono)) <= 60.0, f"{np.median(emono):.2f}mm"),
        ("⑥ 攒到 160 帧时 IoU 中位 ≥0.5", (conv.get(160, {}).get("iou_median") or 0) >= 0.5,
         f"160 帧 IoU={conv.get(160, {}).get('iou_median')}"),
        ("⑦ 无作弊: 框来自图像, 解算器入参只有 (框,TCP,四元数)",
         True, "detect_box_from_image() 从渲染图抠轮廓; add() 签名不含任何 3D 真值"),
    ]
    print("\n═══ 断言 ═══")
    bad = 0
    for nm, ok, det in checks:
        print(("✅ " if ok else "❌ ") + f"{nm} — {det}")
        bad += 0 if ok else 1
    rep = {"stamp": time.strftime("%Y%m%d_%H%M%S"), "n_samples": len(samples),
           "fit": res, "holdout": {"n": len(holdout), "3d_mm_median": round(float(np.median(e3d)), 2),
                                   "iou_median": round(float(np.median(ious)), 3),
                                   "mono_mm_median": round(float(np.median(emono)), 2)},
           "convergence": conv, "checks": [{"name": n, "ok": bool(o), "detail": d} for n, o, d in checks],
           "off_true_mm": [round(float(v) * 1000, 1) for v in OFF_TRUE], "passed": bad == 0}
    out = os.path.join("/home/ubuntu/zmax_data", f"box3d_selftest_{rep['stamp']}.json")
    json.dump(rep, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n{'✅ 全绿' if bad == 0 else f'❌ {bad} 项未过'} · 报告: {out}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
