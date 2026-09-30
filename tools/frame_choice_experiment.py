#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""frame_choice_experiment.py — 坐标系选择对 2D→3D 精度的影响 (实测, 合成)

老倪 2026-09-18: 「是不是得选一个坐标系, 让"抓取点到光模块的相对距离"目标是 0 更合理?
                 机器人知道世界坐标系, 原点是 1 轴法兰盘正中心。」

比较三种"未知量集合"在**同一套数据/同一套算法**下的精度 (数据: 机器人夹着模块走 160 位姿,
框从渲染图像里抠 = 感知给的结果; 真值只用于打分):
  A 世界系 + 模块偏移未知   : 解 P(11) + off(3) = 14 个未知量   ← 现在的做法
  B 世界系 + 工具零点已示教 : off≡0 (把机器人 TCP 示教到模块参考点) → 只解 P(11)
  C 世界系 + 零点给错       : 数据是 90mm, 却告诉它 0 → 看错零点的代价
"""
from __future__ import annotations

import json
import os
import sys
import time

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_REPO, "src", "lerobot", "policies", "yolo_3d"))

import box3d_solver_selftest as SS                                            # noqa: E402
from box3d_solver import Box3DSolver                                          # noqa: E402
from mono23d_experiment import SIZE, pose_set                                 # noqa: E402
import real_probe_dryrun_selftest as RS                                       # noqa: E402

W, H = 640, 480


def build(n_train=160, n_hold=40, off_true=(0.0, -0.090, 0.0), seed=12):
    P_true, _ = pose_set(1, 0, 0, 0, "small")[1]
    poses, _ = pose_set(n_train + n_hold, 0.125, 25.0, seed, "big")
    rng = np.random.default_rng(2026)
    base_img = RS.static_scene()
    out = []
    for tcp, R in poses:
        c = np.asarray(tcp, float) + R @ np.asarray(off_true, float)
        q = RS.rot_to_quat(R)
        img = SS.render_frame(base_img, P_true, c, q, [s for s in SIZE], gripper_tcp=tcp)
        bx = SS.detect_box_from_image(img)
        if bx is None:
            continue
        out.append(([v + rng.normal(0, 0.5) for v in bx], [float(v) for v in tcp], q, c.tolist()))
    return out[:n_train], out[n_train:]


def run(tag, train, holdout, off_true, fix_off):
    slv = Box3DSolver(size_mm=[s * 1000 for s in SIZE], img_wh=(W, H), fix_off=fix_off)
    for bx, tcp, q, _t in train:
        slv.add(bx, tcp, q)
    res = slv.fit()
    e3d, ious = [], []
    for bx, tcp, q, truth in holdout:
        p = slv.predict_held(tcp, q)
        if not p:
            continue
        e3d.append(float(np.linalg.norm(np.asarray(p) - np.asarray(truth))) * 1000)
        pb = slv.project_box(p, q)
        if pb:
            ious.append(SS.iou(pb, bx))
    off_err = (None if fix_off is not None else
               float(np.linalg.norm(np.asarray(slv.off) - np.asarray(off_true))) * 1000)
    return {"tag": tag, "mode": slv.status()["mode"], "rms_px": res.get("rms_px"),
            "holdout_rms_px": res.get("holdout_rms_px"), "off_hat_mm": res.get("off_mm"),
            "off_err_mm": (round(off_err, 2) if off_err is not None else None),
            "holdout_3d_mm_median": round(float(np.median(e3d)), 2),
            "holdout_iou_median": round(float(np.median(ious)), 3),
            "degenerate": bool(res.get("degenerate"))}


def main():
    OFF = (0.0, -0.090, 0.0)
    tr_a, ho_a = build(off_true=OFF)                       # 模块离 TCP 90mm (现状)
    tr_b, ho_b = build(off_true=(0.0, 0.0, 0.0))           # 工具零点示教到模块参考点 → 相对距离 0
    res = {
        "A 偏移未知 (解 P+off=14 个)": run("A", tr_a, ho_a, OFF, None),
        "B 零点已示教 off≡0 (只解 P=11 个)": run("B", tr_b, ho_b, (0, 0, 0), (0.0, 0.0, 0.0)),
        "C 零点给错 (真 90mm 却按 0)": run("C", tr_a, ho_a, OFF, (0.0, 0.0, 0.0)),
    }
    print("═══ 坐标系/未知量选择 → 2D→3D 精度 (同一算法同一数据规模, 160 训练 / 40 留出) ═══")
    print(f"{'方案':<34}{'拟合rms':>9}{'留出rms':>9}{'off误差':>10}{'留出3D中位':>11}{'留出框IoU':>10}")
    for k, v in res.items():
        print(f"{k:<34}{str(v['rms_px']):>9}{str(v['holdout_rms_px']):>9}"
              f"{str(v['off_err_mm']):>10}{v['holdout_3d_mm_median']:>10.2f}mm{v['holdout_iou_median']:>10.3f}")
    out = os.path.join("/home/ubuntu/zmax_data", f"frame_choice_{time.strftime('%Y%m%d_%H%M%S')}.json")
    json.dump({"note": "A=世界系+偏移未知; B=世界系+工具零点示教(相对距离0); C=零点给错",
               "off_true_mm": [v * 1000 for v in OFF], "size_mm": [s * 1000 for s in SIZE],
               "results": res}, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n报告: {out}")


if __name__ == "__main__":
    raise SystemExit(main())
