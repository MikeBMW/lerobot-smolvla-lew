#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""box3d_identifiability_experiment.py — 「2D 框 → 3D 边界框」到底什么可辨识 (真值只打分)

背景 (2026-09-18 实测): 先把 (P,off,R_rel,尺寸) 全放开联合解, 像素残差做到 1.1px (几乎完美),
但 3D 框中心仍偏 65mm、姿态错 50° —— 说明存在"像素上等价、3D 上不同"的退化方向。
本脚本把未知量拆成 6 个臂, 同数据同口径比, 回答: **要让 3D 边界框准, 必须钉死哪几样?**

| 臂 | 解算器已知 | 解算器要解 | 尺寸 |
|---|---|---|---|
| A | —            | P, off          | 标称(真值) |
| B | —            | P, off, R_rel   | 标称(真值) |
| C | —            | P, off, R_rel, 尺寸 | 自由 |
| D | —            | P, off          | 标称错 +15% |
| E | —            | P, off, R_rel   | 标称错 +15% |
| F | 工具零点已示教 (off≡0) | P, R_rel | 标称(真值) |

打分: 留出帧像素残差 · off 误差 · R_rel 误差 · 尺寸误差 · 3D 框中心误差 · **8 角点误差** · 反投影 IoU
用法: gui-venv311/bin/python tools/box3d_identifiability_experiment.py [--json OUT.json]
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

from box3d_box3d_selftest import (RREL_TRUE_DEG, W, H, build_samples,      # noqa: E402
                                 corner_err_mm, R_err_deg)
from box3d_solver_selftest import iou                                        # noqa: E402
from mono23d_experiment import K as K_TRUE                                    # noqa: E402
from mono23d_experiment import OFF_TRUE, SIZE                                # noqa: E402
from box3d_solver import Box3DSolver                                         # noqa: E402

OFF_TRUE_MM = [round(float(v) * 1000, 1) for v in OFF_TRUE]
SIZE_TRUE_MM = [round(float(s) * 1000, 1) for s in SIZE]

ARMS = [
    ("A 只解 P,off · 尺寸真值",        dict(size="true",  use_rrel=False, use_scale=False, fix_off=False)),
    ("B 解 P,off,R_rel · 尺寸真值",    dict(size="true",  use_rrel=True,  use_scale=False, fix_off=False)),
    ("C 全放开 · 尺寸自由",            dict(size="true",  use_rrel=True,  use_scale=True,  fix_off=False)),
    ("D 只解 P,off · 尺寸错+15%",      dict(size="wrong", use_rrel=False, use_scale=False, fix_off=False)),
    ("E 解 P,off,R_rel · 尺寸错+15%",  dict(size="wrong", use_rrel=True,  use_scale=False, fix_off=False)),
    ("F off≡0(零点已示教) · 解 P,R_rel", dict(size="true", use_rrel=True,  use_scale=False, fix_off=True)),
    ("G K已知 · 解手眼+off+R_rel · 尺寸真值", dict(size="true", use_rrel=True, use_scale=False,
                                                 fix_off=False, K=True)),
    ("H K已知 · 解手眼+off+R_rel+尺寸", dict(size="true", use_rrel=True, use_scale=True,
                                            fix_off=False, K=True)),
    ("I K已知 · 只解手眼+off · 尺寸真值", dict(size="true", use_rrel=False, use_scale=False,
                                             fix_off=False, K=True)),
]


def run_arm(cfg, train, holdout):
    size_mm = SIZE_TRUE_MM if cfg["size"] == "true" else [round(s * 1000 * 1.15, 1) for s in SIZE]
    fix = [0.0, 0.0, 0.0] if cfg["fix_off"] else None
    slv = Box3DSolver(size_mm=size_mm, img_wh=(W, H), fix_off=fix,
                      K=(K_TRUE if cfg.get("K") else None))
    for s in train:
        slv.add(s["box"], s["tcp"], s["quat"])
    div = slv.diversity()
    if not div["ok"]:
        return {"ok": False, "why": div["why"]}
    fit = slv.fit(use_rrel=cfg["use_rrel"], use_scale=cfg["use_scale"])
    if not fit.get("ok"):
        return {"ok": False, "why": fit.get("why")}
    e_c, e_cor, ious, rr = [], [], [], []
    for s in holdout:
        r = slv.predict_box3d(s["box"], tcp=s["tcp"], quat=s["quat"])
        if r["mode"] != "held":
            continue
        e_c.append(float(np.linalg.norm(np.asarray(r["center"]) - np.asarray(s["center_true"]))) * 1000)
        e_cor.append(float(np.median(corner_err_mm(r["corners8"], s["corners_true"]))))
        ious.append(iou(r["box2d_reproj"], s["box"]))
        rr.append(R_err_deg(np.asarray(r["R"]), s["R_box_true"]))
    off_err = None if cfg["fix_off"] else max(abs(a - b) for a, b in zip(fit["off_mm"], OFF_TRUE_MM))
    rrel_err = None
    if fit.get("rrel_deg"):
        rrel_err = max(abs(a - b) for a, b in zip(fit["rrel_deg"], RREL_TRUE_DEG))
    size_err = max(abs(a - b) for a, b in zip(fit.get("size_mm") or size_mm, SIZE_TRUE_MM))
    return {"ok": True, "rms_px": fit.get("rms_px"), "holdout_px": fit.get("holdout_rms_px"),
            "off_mm": fit.get("off_mm"), "off_err_mm": None if off_err is None else round(off_err, 1),
            "rrel_deg": fit.get("rrel_deg"), "rrel_err_deg": None if rrel_err is None else round(rrel_err, 2),
            "size_mm": fit.get("size_mm"), "size_err_mm": round(size_err, 2),
            "center_mm_median": round(float(np.median(e_c)), 2),
            "corner_mm_median": round(float(np.median(e_cor)), 2),
            "R_err_deg_median": round(float(np.median(rr)), 2),
            "iou_median": round(float(np.median(ious)), 3)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=None)
    ap.add_argument("--n", type=int, default=200)
    args = ap.parse_args()
    stamp = time.strftime("%Y%m%d_%H%M%S")
    samples = build_samples(args.n)
    train, holdout = samples[:160], samples[160:]
    print(f"═══ 可辨识性实验: {len(samples)} 帧合成 (框从图像抠轮廓 + 0.5px 噪声; 真值只打分) ═══")
    print(f"    真值: off={OFF_TRUE_MM}mm · R_rel={list(RREL_TRUE_DEG)}° · 尺寸={SIZE_TRUE_MM}mm")
    rows = {}
    for name, cfg in ARMS:
        r = run_arm(cfg, train, holdout)
        rows[name] = r
        if not r.get("ok"):
            print(f"\n{name}: ❌ {r.get('why')}")
            continue
        print(f"\n{name}")
        print(f"   留出残差 {r['holdout_px']}px · off {r['off_mm']}mm (误差 {r['off_err_mm']}mm) · "
              f"R_rel {r['rrel_deg']}° (误差 {r['rrel_err_deg']}°) · 尺寸 {r['size_mm']}mm (误差 {r['size_err_mm']}mm)")
        print(f"   → 3D 边界框: 中心 中位 {r['center_mm_median']}mm · **8 角点** 中位 {r['corner_mm_median']}mm · "
              f"姿态误差 {r['R_err_deg_median']}° · 反投影 IoU {r['iou_median']}")
    path = args.json or os.path.expanduser(f"~/zmax_data/box3d_identifiability_{stamp}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump({"stamp": stamp, "off_true_mm": OFF_TRUE_MM, "rrel_true_deg": list(RREL_TRUE_DEG),
               "size_true_mm": SIZE_TRUE_MM, "arms": rows},
              open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n证据: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
