#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""box3d_fitpath_rehearsal.py — 现场动作前的**彩排**: 把 box3d_live_box 的自动拟合链路跑一遍

为什么要彩排: 现场要靠"人拖着机器人走 10 个位姿"来标定 (60 秒一次性动作)。若 `try_fit` 的链路
(拟合 → 前提自证 → 落盘 → 重载 → 出 3D 框) 有 bug, 那 60 秒就白费了。这里用真机内参 K
(从 models/real_cam_calib.json 读) + 合成位姿, 走**和现场完全相同的函数** (`try_fit`/`save`/`load`/
`predict_box3d`) 验两件事:

  ① 正例 (模块真被夹持): 前提自证通过 → 落盘 → 重载 → 3D 边界框角点误差 (mm)
  ② 反例 (模块躺在台面不动, 机器人空手走): 前提自证**必须失败** → 不落盘 (否则现场会存进垃圾状态)

用法: gui-venv311/bin/python tools/box3d_fitpath_rehearsal.py
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

import real_probe_dryrun_selftest as RS                                        # noqa: E402
import box3d_live_box as LB                                                    # noqa: E402
from box3d_solver_selftest import detect_box_from_image, render_frame, iou     # noqa: E402
from mono23d_experiment import OFF_TRUE, SIZE, pose_set                        # noqa: E402
from box3d_solver import Box3DSolver, _corners_R, _R_euler                     # noqa: E402

W, H = 640, 480
RREL_TRUE_DEG = (6.0, -4.0, 12.0)


def real_K():
    d = json.load(open(os.path.join(_REPO, "models", "real_cam_calib.json"), encoding="utf-8"))
    return np.asarray(d["K"], float).reshape(3, 3), (d.get("image_size") or [W, H])


def build(K, held=True, n=160):
    """held=True: 模块被夹 (中心=TCP+R·off, 随动) · held=False: 模块静放台面 (TCP 空手动)"""
    FX, FY, CX, CY = K[0, 0], K[1, 1], K[0, 2], K[1, 2]
    Rm = RS.make_camera((0.00, -0.45, 0.60), (0.30, 0.05, 0.10))[1].T     # 相机→base 的 R (行=轴)
    C = np.asarray((0.00, -0.45, 0.60), float)
    P_true = K @ np.hstack([Rm, (-Rm @ C).reshape(3, 1)])
    poses, _ = pose_set(n, 0.125, 25.0, 12, "big")
    rng = np.random.default_rng(7)
    base = RS.static_scene()
    Rrel = _R_euler([math.radians(v) for v in RREL_TRUE_DEG])
    size_m = [float(s) for s in SIZE]
    fixed_c = np.asarray((0.30, 0.05, 0.10), float)          # 台面上的固定位置 (反例用)
    R_fixed = _R_euler([0.0, 0.0, 0.0])
    out = []
    for tcp, R_tool in poses:
        R_box = R_tool @ Rrel
        c_true = (np.asarray(tcp, float) + R_tool @ OFF_TRUE) if held else fixed_c
        Rb = R_box if held else R_fixed
        img = render_frame(base, P_true, c_true.tolist(), RS.rot_to_quat(Rb), size_m, gripper_tcp=tcp)
        bx = detect_box_from_image(img)
        if bx is None:
            continue
        bx = [v + rng.normal(0, 0.5) for v in bx]
        out.append({"box": bx, "tcp": [float(v) for v in tcp], "quat": RS.rot_to_quat(R_tool),
                    "corners_true": [list(p) for p in _corners_R(c_true, Rb, size_m)]})
    return out


def main():
    stamp = time.strftime("%Y%m%d_%H%M%S")
    K, (w, h) = real_K()
    print(f"═══ 拟合链路彩排 (真机内参 fx={K[0,0]:.2f}, {w}x{h}) ═══")
    # 落盘路径改到彩排目录 —— 绝不碰现场的 models/box3d_state.json
    tmp_state = os.path.expanduser(f"~/zmax_data/rehearsal/box3d_state_{stamp}.json")
    os.makedirs(os.path.dirname(tmp_state), exist_ok=True)
    LB.STATE = tmp_state
    res = {}

    # ── ① 正例: 模块被夹持 ──
    samp = build(K, held=True)
    slv = Box3DSolver(size_mm=[s * 1000 for s in SIZE], img_wh=(w, h), K=K)
    for s in samp[:120]:
        slv.add(s["box"], s["tcp"], s["quat"])
    print(f"\n① 正例 (夹持): 攒 {len(slv.obs)} 帧 · 多样性 {slv.diversity()['ok']} "
          f"(tilt={slv.diversity().get('tilt_deg')}°)")
    f1 = LB.try_fit(slv, log=True)
    print(f"   前提自证 IoU={f1.get('holdout_iou_median')} · premise_ok={f1.get('premise_ok')} · "
          f"落盘={os.path.exists(tmp_state)}")
    errs, ious, modes = [], [], {}
    if os.path.exists(tmp_state):
        r2 = Box3DSolver.load(tmp_state)
        for s in samp[120:]:
            b3 = r2.predict_box3d(s["box"], tcp=s["tcp"], quat=s["quat"])
            modes[b3["mode"]] = modes.get(b3["mode"], 0) + 1
            if b3["mode"] == "held":
                a = np.asarray(b3["corners8"], float); b = np.asarray(s["corners_true"], float)
                errs.append(float(np.median(np.linalg.norm(a - b, axis=1))) * 1000)
                ious.append(iou(b3["box2d_reproj"], s["box"]))
        print(f"   重载 {tmp_state} → fitted={r2.fitted} K保留={r2.K is not None} · 留出 {len(errs)} 帧: "
              f"mode={modes} · **8 角点误差 中位 {np.median(errs):.2f}mm** · 反投影 IoU 中位 "
              f"{np.median(ious):.3f}")
        res["positive"] = {"premise_ok": f1.get("premise_ok"), "iou_fit": f1.get("holdout_iou_median"),
                           "corner_mm_median": round(float(np.median(errs)), 2),
                           "iou_median": round(float(np.median(ious)), 3), "saved": True,
                           "holdout_rms_px": f1.get("holdout_rms_px"), "off_mm": f1.get("off_mm"),
                           "rrel_deg": f1.get("rrel_deg")}
    else:
        res["positive"] = {"premise_ok": f1.get("premise_ok"), "saved": False}
        print("   ❌ 正例没落盘 —— 现场动作会白费, 先修链路")
    assert f1.get("premise_ok") and os.path.exists(tmp_state), "正例前提自证应通过并落盘"

    # ── ② 反例: 模块静放台面, 机器人空手动 (夹持前提不成立) ──
    os.remove(tmp_state) if os.path.exists(tmp_state) else None
    samp2 = build(K, held=False)
    slv2 = Box3DSolver(size_mm=[s * 1000 for s in SIZE], img_wh=(w, h), K=K)
    for s in samp2[:120]:
        slv2.add(s["box"], s["tcp"], s["quat"])
    f2 = LB.try_fit(slv2, log=True)
    saved2 = os.path.exists(tmp_state)
    print(f"\n② 反例 (模块没被夹, 台面静放): 前提自证 IoU={f2.get('holdout_iou_median')} · "
          f"premise_ok={f2.get('premise_ok')} · 落盘={saved2} (必须 False)")
    res["negative"] = {"premise_ok": f2.get("premise_ok"), "iou_fit": f2.get("holdout_iou_median"),
                       "saved": saved2, "holdout_rms_px": f2.get("holdout_rms_px")}
    assert saved2 is False, "反例不许落盘 (夹持前提不成立时存状态 = 假标定)"

    out = {"stamp": stamp, "K": K.tolist(), "img_wh": [w, h], "checks": res, "ok": True}
    path = os.path.expanduser(f"~/zmax_data/box3d_fitpath_rehearsal_{stamp}.json")
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n✅ 彩排通过 (正例可信落盘 / 反例正确拒绝) · 证据: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
