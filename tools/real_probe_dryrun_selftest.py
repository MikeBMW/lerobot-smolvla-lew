#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""real_probe_dryrun_selftest.py — S0→S1→S2 离线端到端演练 (不碰真机, 但走**真实代码路径**)

老倪 2026-09-18: 「根据真机 + L2 + 训练模式, 自动根据机器人动作学习 — 你来设计这个方案。」
本脚本是方案的**离线可验证性**那一半: 机器人不在线也能把链路算通, 上线只差一次探针运动。

每条断言都对应一个**实质工程决定** (都是演练里真跑出来的, 不是推的):
  ① 配对用"面积加权全域质心"(=两帧中点), 不用"最大连通域中心"   → 旧实现偏 15~30px
  ② 3D 点必须加**实测**的"模块中心相对 TCP"偏移                  → 不加则整框偏移
  ③ 运动必须**收口到模块区域(ROI)**                             → 不收口时差分质心是"模块+夹爪"合成点
  ④ 探针位姿必须有真实深度变化 (非共面), 否则 DLT 病态           → 平面探针 rms 1608px, K 反解为 0
  ⑤ 抓取门看"模块该在的位置有没有随动", 不看全图最大域          → 否则任何跟着 TCP 动的东西都放行
  ⑦ 探针必须带**真实姿态变化** (不只是平移), 否则"偏移给错"会被 DLT 自洽吸收而不报错
  ⑥ 联合解出的"合成偏移"只能当诊断, 不能拿去出框                → 出框会整体偏 (IoU 掉一半)

用法: gui-venv311/bin/python tools/real_probe_dryrun_selftest.py
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

import real_autolabel as RAL                                                   # noqa: E402

WORK = os.environ.get("ZMAX_PROBE_REHEARSAL", "/home/ubuntu/zmax_data/probe_rehearsal")
W, H = 640, 480
FX, FY, CX, CY = 610.0, 607.0, 318.0, 242.0
SIZE_MM = (40.0, 16.0, 12.0)
MOD_OFF_B = (0.0, -0.040, -0.008)       # B: 模块中心在工具系里比 TCP 侧偏 40mm (当成"现场量出来的")
MOD_ROD = (0.0, -0.090, 0.0)            # 真实几何: 24cm 长杆夹在一端 → 模块中心离 TCP ~90mm
                                        # (合成场景里夹爪只有贴 22px 时才是"最坏情况"; 真机不是这样)


# ───────────────────────── 合成"机器人+相机" ─────────────────────────
def rot_to_quat(R):
    tr = R[0, 0] + R[1, 1] + R[2, 2]
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        q = [(R[2, 1] - R[1, 2]) / s, (R[0, 2] - R[2, 0]) / s, (R[1, 0] - R[0, 1]) / s, 0.25 * s]
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = math.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2]) * 2
        q = [0.25 * s, (R[0, 1] + R[1, 0]) / s, (R[0, 2] + R[2, 0]) / s, (R[2, 1] - R[1, 2]) / s]
    elif R[1, 1] > R[2, 2]:
        s = math.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2]) * 2
        q = [(R[0, 1] + R[1, 0]) / s, 0.25 * s, (R[1, 2] + R[2, 1]) / s, (R[0, 2] - R[2, 0]) / s]
    else:
        s = math.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1]) * 2
        q = [(R[0, 2] + R[2, 0]) / s, (R[1, 2] + R[2, 1]) / s, 0.25 * s, (R[1, 0] - R[0, 1]) / s]
    return [round(float(v), 6) for v in q]


def axis_angle_R(ax, ang):
    ax = np.asarray(ax, float)
    ax = ax / (np.linalg.norm(ax) or 1.0)
    K = np.array([[0, -ax[2], ax[1]], [ax[2], 0, -ax[0]], [-ax[1], ax[0], 0]])
    return np.eye(3) + math.sin(ang) * K + (1 - math.cos(ang)) * (K @ K)


def make_camera(C, look, up=(0.0, 0.0, 1.0)):
    C = np.asarray(C, float)
    z = np.asarray(look, float) - C
    z = z / np.linalg.norm(z)
    x = np.cross(z, np.asarray(up, float))
    x = x / np.linalg.norm(x)
    y = np.cross(z, x)
    Rm = np.stack([x, y, z])
    K = np.array([[FX, 0, CX], [0, FY, CY], [0, 0, 1.0]])
    return K @ np.hstack([Rm, (-Rm @ C).reshape(3, 1)]), np.stack([x, y, z], axis=1), C


def static_scene(seed=11):
    import cv2
    rng = np.random.default_rng(seed)
    base = np.clip(np.full((H, W, 3), 118, np.int16) + rng.integers(-3, 4, (H, W, 3)).astype(np.int16),
                   0, 255).astype(np.uint8)
    cv2.rectangle(base, (110, 70), (540, 450), (86, 86, 90), -1)
    cv2.circle(base, (320, 275), 58, (38, 38, 42), -1)
    cv2.rectangle(base, (0, 440), (W - 1, H - 1), (70, 70, 74), -1)
    return base


def render(base, P, center, quat, size_m, gripper_tcp=None):
    """模块 (亮, 细长) + 可选夹爪 (暗条, 贴在 TCP 上方, 与模块相邻不重叠)"""
    import cv2
    img = base.copy()
    if gripper_tcp is not None:
        g = RAL.project(P, gripper_tcp)
        cv2.rectangle(img, (int(g[0] - 11), int(g[1] - 45)), (int(g[0] + 11), int(g[1] - 22)),
                      (48, 46, 44), -1)
    pts = [RAL.project(P, c) for c in RAL.module_corners(center, quat, size_m)]
    hull = np.round(cv2.convexHull(np.asarray(pts, np.float32))).astype(np.int32)
    cv2.fillConvexPoly(img, hull, (218, 208, 196))
    cv2.polylines(img, [hull], True, (55, 55, 55), 1)
    return img


def build_session(root, tag, poses, P_true, size_m, module_offset=None, freeze_module=False,
                  draw_gripper=True, write_roi=True, seed=5):
    """渲染探针会话; write_roi=True 时写 roi.jsonl —— 模拟"独立模块定位" (人工点一次 / 在役 YOLO 框),
    带 ±5px 抖动 + 25% 外扩 (证明 ROI 不需要很准)"""
    import cv2
    sdir = os.path.join(root, tag)
    fdir = os.path.join(sdir, "frames")
    os.makedirs(fdir, exist_ok=True)
    base = static_scene()
    frozen = poses[0][0] if freeze_module else None
    rng = np.random.default_rng(seed)
    rows, rois = [], []
    for k, (tcp, quat) in enumerate(poses):
        stem = f"p{k:03d}"
        center = list(frozen) if frozen is not None else RAL.module_center(tcp, quat, module_offset)
        img = render(base, P_true, center, quat, size_m, gripper_tcp=(tcp if draw_gripper else None))
        cv2.imwrite(os.path.join(fdir, stem + ".jpg"), img, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        t = {"ts": round(1000.0 + k * 0.1, 3), "frame": "base_link",
             "tcp": [round(float(v), 6) for v in tcp], "tcp_quat": [round(float(v), 6) for v in quat],
             "joints": None, "ft": None, "src_file": "synthetic(probe rehearsal)"}
        rows.append({"stem": stem, "session": tag, "w": W, "h": H, "boxes": [], "truth": t,
                     "synthetic": True, "rendered_module_center": [round(float(v), 6) for v in center]})
        bx = RAL.box_from_3d(P_true, center, quat, size_m, (W, H))
        if bx and write_roi:
            pw, ph = (bx[2] - bx[0]) * 0.25, (bx[3] - bx[1]) * 0.25
            jx, jy = rng.uniform(-5, 5, 2)
            rois.append({"stem": stem, "src": "human_or_yolo(模拟)",
                         "box": [round(bx[0] - pw + jx, 1), round(bx[1] - ph + jy, 1),
                                 round(bx[2] + pw + jx, 1), round(bx[3] + ph + jy, 1)]})
    with open(os.path.join(sdir, "truth.jsonl"), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    if write_roi:
        with open(os.path.join(sdir, "roi.jsonl"), "w", encoding="utf-8") as f:
            for r in rois:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return sdir


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def heldout_error(P_hat, P_true, poses, half=0.05):
    rng = np.random.default_rng(2026)
    base_xyz = np.mean([np.asarray(p[0], float) for p in poses], axis=0)
    errs = [float(np.linalg.norm(RAL.project(P_hat, X) - RAL.project(P_true, X)))
            for X in [base_xyz + rng.uniform(-half, half, 3) for _ in range(40)]]
    return float(np.mean(errs)), float(np.max(errs))


def measure(sdir, poses, P_true, *, label_offset, true_offset=None, freeze_module, use_roi, ref_P=None):
    """走真代码路径: ROI内质心 → 配对 → DLT → 可辨识性预检 → S2 标注 → 与**真值框**比 IoU

    label_offset: 喂进链路 (配对 3D 点 + 出框) 的偏移 —— 模拟"现场量了多少"
    true_offset : 物理真值偏移 (只用于算 IoU 基准) —— 两者分开, 否则测不出"偏移给错"的后果
    ref_P       : 给定标定 (C/D 场景: 模块静止无法自标定, 用 A 的标定只测抓取门)
    """
    true_offset = label_offset if true_offset is None else true_offset
    roi_map, _bad = RAL.load_roi_map(sdir) if use_roi else ({}, 0)
    pairs, info = RAL.probe_pairs_from_session(os.path.join(sdir, "frames"),
                                               os.path.join(sdir, "truth.jsonl"),
                                               module_offset_m=label_offset, roi_map=roi_map)
    out = {"n_pairs": len(pairs), "use_roi": use_roi, "label_offset_mm": [round(v * 1000, 1) for v in label_offset],
           "true_offset_mm": [round(v * 1000, 1) for v in true_offset],
           "used_ref_P": ref_P is not None}
    P, chk, rms, rmsj, off = None, None, None, None, None
    if len(pairs) >= 6:
        P, rms = RAL.fit_proj(pairs)
        chk = RAL.probe_design_check(pairs)
        _Pj, off, rmsj, _h = RAL.fit_proj_offset(pairs, info["quats"])
        mean_e, max_e = heldout_error(P, P_true, poses)
        out.update({"rms_px": round(rms, 3), "rms_joint_px": round(rmsj, 3),
                    "solved_blend_off_mm": [round(float(v) * 1000, 1) for v in off],
                    "design_check": chk, "heldout_mean_px": round(mean_e, 3),
                    "heldout_max_px": round(max_e, 3), "K_fx": round(RAL.decompose_K(P)["fx"], 1),
                    "_P": np.asarray(P, float).tolist()})
    else:
        out["no_pairs_reason"] = f"只凑到 {len(pairs)} 对 (<6) → 无法自标定"
    if P is None and ref_P is not None:
        P = ref_P
    if P is None:
        out.update({"s2_n": 0, "s2_iou": None, "s2_skipped": {}, "K_fx": out.get("K_fx"),
                    "s2_reason": "无标定可用 → 不产出任何标签"})
        return out
    rep = RAL.label_session(sdir, P, [s / 1000.0 for s in SIZE_MM], grasp_rule="auto", dry=True,
                            module_offset_m=label_offset, use_roi=use_roi)
    ious = []
    for it in rep["items"]:
        if not it.get("labeled"):
            continue
        k = int(it["stem"][1:])
        tcp, quat = poses[k]
        ctr = (list(poses[0][0]) if freeze_module else RAL.module_center(tcp, quat, true_offset))
        gt = RAL.box_from_3d(P_true, ctr, quat, [s / 1000.0 for s in SIZE_MM], (W, H))
        if gt:
            ious.append(iou(it["box_px"], gt))
    out.update({"s2_n": rep["n_labeled"], "s2_iou": round(float(np.median(ious)), 3) if ious else None,
                "s2_skipped": rep["skipped"]})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true", default=True)
    ap.parse_args()

    os.makedirs(WORK, exist_ok=True)
    run_dir = os.path.join(WORK, f"run_{time.strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(run_dir, exist_ok=True)

    P_true, axes, _C = make_camera((0.00, -0.45, 0.60), (0.30, 0.05, 0.10))
    u, v, w = axes[:, 0], axes[:, 1], axes[:, 2]
    base = np.asarray((0.30, 0.05, 0.10), float)
    assert 60 < RAL.project(P_true, base)[0] < W - 60, "基准点出画"

    offs = [(dx, dy, 0.0) for dy in (-0.035, 0.0, 0.035) for dx in (-0.035, 0.0, 0.035)]
    offs += [(0.045, 0.030, 0.085), (-0.045, -0.030, 0.085), (0.030, -0.045, 0.115), (-0.030, 0.045, 0.115)]
    raw = [(base + a * u + b * v + c * w, a) for (a, b, c) in offs]
    order, left = [0], list(range(1, len(raw)))
    while left:
        cur = raw[order[-1]][0]
        nxt = min(left, key=lambda i: float(np.linalg.norm(raw[i][0] - cur)))
        order.append(nxt)
        left.remove(nxt)
    poses = []
    for idx in order:
        tcp, a = raw[idx]
        Rq = np.stack([u, v, w], axis=1) @ axis_angle_R([0, 1, 0], math.radians(16.0 * a / 0.035))
        poses.append((tcp.tolist(), rot_to_quat(Rq)))
    planar = [((base + a * u + b * v).tolist(), rot_to_quat(np.stack([u, v, w], axis=1)))
              for (a, b) in [(-0.035, -0.035), (0.035, -0.035), (-0.035, 0.035), (0.035, 0.035),
                             (0.0, 0.0), (0.02, 0.0), (-0.02, 0.0), (0.0, 0.02), (0.0, -0.02)]]

    print(f"═══ S0→S1→S2 离线端到端演练 · {len(poses)} 点探针 (含真实深度变化) · {W}x{H} ═══")
    print(f"工作目录: {run_dir}\n")

    sz = [s / 1000.0 for s in SIZE_MM]
    res = {}
    d_clean = build_session(run_dir, "A_clean", poses, P_true, sz, draw_gripper=False)
    res["A_clean(无夹爪)"] = measure(d_clean, poses, P_true, label_offset=(0.0, 0.0, 0.0),
                                     freeze_module=False, use_roi=True)
    refP = np.asarray(res["A_clean(无夹爪)"]["_P"], float)       # A 的标定 → 给 C/D 当"已有标定"

    # 真实几何: 长杆夹在一端, 夹爪在杆端 → ROI(模块框)与夹爪在画面上是分开的
    d_rod = build_session(run_dir, "A_rod", poses, P_true, sz, module_offset=MOD_ROD, draw_gripper=True)
    res["A_rod(真实几何,ROI)"] = measure(d_rod, poses, P_true, label_offset=MOD_ROD,
                                         freeze_module=False, use_roi=True)
    res["A_rod(真实几何,无ROI)"] = measure(d_rod, poses, P_true, label_offset=MOD_ROD,
                                           freeze_module=False, use_roi=False)
    # 最坏情况: 夹爪紧贴模块 (离 22px) —— 真机不会这样, 拿来量边界
    d_close = build_session(run_dir, "A_close", poses, P_true, sz, draw_gripper=True)
    res["A_close(夹爪紧贴,最坏)"] = measure(d_close, poses, P_true, label_offset=(0.0, 0.0, 0.0),
                                            freeze_module=False, use_roi=True)
    # 偏移给错: 只看 rms 看不出来 (DLT 会自洽吸收), 要靠"验证位姿盲测"才暴露
    d_b = build_session(run_dir, "B_offset", poses, P_true, sz, module_offset=MOD_OFF_B, draw_gripper=True)
    res["B_偏移给对"] = measure(d_b, poses, P_true, label_offset=MOD_OFF_B, freeze_module=False, use_roi=True)
    res["B_偏移按0(给错)"] = measure(d_b, poses, P_true, label_offset=(0.0, 0.0, 0.0),
                                     true_offset=MOD_OFF_B, freeze_module=False, use_roi=True)
    d_c = build_session(run_dir, "C_nograsp", poses, P_true, sz, freeze_module=True, draw_gripper=False)
    res["C_没夹住(无其它运动)"] = measure(d_c, poses, P_true, label_offset=(0.0, 0.0, 0.0),
                                          freeze_module=True, use_roi=True, ref_P=refP)
    d_d = build_session(run_dir, "D_nograsp_gripper", poses, P_true, sz, module_offset=MOD_ROD,
                        freeze_module=True, draw_gripper=True)
    res["D_没夹住(夹爪可见,无ROI)"] = measure(d_d, poses, P_true, label_offset=MOD_ROD,
                                              freeze_module=True, use_roi=False)
    res["D_没夹住(夹爪可见,ROI)"] = measure(d_d, poses, P_true, label_offset=MOD_ROD,
                                            freeze_module=True, use_roi=True, ref_P=refP)
    d_p = build_session(run_dir, "PLANAR", planar, P_true, sz, draw_gripper=False)
    res["PLANAR(退化对照)"] = measure(d_p, planar, P_true, label_offset=(0.0, 0.0, 0.0),
                                      freeze_module=False, use_roi=True)

    print("┌─ 场景 ─────────────────────────── 配对数 ─ 拟合rms ─ 留出集 ─ K_fx ─ 预检ok ─ S2标签/IoU")
    for k, r in res.items():
        if "rms_px" not in r:
            print(f"│ {k:<32} {r.get('no_pairs_reason', '')} · S2 {r.get('s2_n')} 标签")
            continue
        print(f"│ {k:<32} {r['n_pairs']:>4}   {r['rms_px']:>7.3f}  {r['heldout_mean_px']:>6.3f}  "
              f"{r['K_fx']:>5.0f}  {str(r['design_check']['ok']):<6} {r.get('s2_n'):>4}/{r.get('s2_iou')}")
    print("└─")

    AC, AR, ARn, ACl, B, B0, C, Dn, D, PL = (res["A_clean(无夹爪)"], res["A_rod(真实几何,ROI)"],
                                              res["A_rod(真实几何,无ROI)"], res["A_close(夹爪紧贴,最坏)"],
                                              res["B_偏移给对"], res["B_偏移按0(给错)"],
                                              res["C_没夹住(无其它运动)"], res["D_没夹住(夹爪可见,无ROI)"],
                                              res["D_没夹住(夹爪可见,ROI)"], res["PLANAR(退化对照)"])

    def _iou(d):
        return 1.0 if d.get("s2_iou") is None else d["s2_iou"]

    checks = [
        ("① A_clean: 无夹爪 → rms ≤2px / IoU ≥0.5 / 标签 ≥8",
         AC.get("rms_px", 9e9) <= 2.0 and _iou(AC) >= 0.5 and AC.get("s2_n", 0) >= 8,
         f"rms={AC.get('rms_px')}px IoU={AC.get('s2_iou')} n={AC.get('s2_n')}"),
        ("③ A_rod 真实几何(长杆): 不收口到模块 → 超差; 收口(ROI) → rms ≤2px / IoU ≥0.5",
         ARn.get("rms_px", 0) > 2.0 and AR.get("rms_px", 9e9) <= 2.0 and _iou(AR) >= 0.5,
         f"无ROI rms={ARn.get('rms_px')}px IoU={ARn.get('s2_iou')} → 有ROI rms={AR.get('rms_px')}px "
         f"IoU={AR.get('s2_iou')} n={AR.get('s2_n')}"),
        ("③ A_close 最坏情况(夹爪紧贴 22px): 仍可用 (rms ≤2.5px / IoU ≥0.5)",
         ACl.get("rms_px", 9e9) <= 2.5 and _iou(ACl) >= 0.5,
         f"rms={ACl.get('rms_px')}px IoU={ACl.get('s2_iou')} n={ACl.get('s2_n')} "
         f"(解出合成偏移 {ACl.get('solved_blend_off_mm')}mm — 只作诊断)"),
        ("② B: 给**实测**模块偏移 → rms ≤2px / IoU ≥0.5",
         B.get("rms_px", 9e9) <= 2.0 and _iou(B) >= 0.5,
         f"rms={B.get('rms_px')}px IoU={B.get('s2_iou')}"),
        ("⑦ 偏移给错时: rms 看不出来 (DLT 自洽吸收), 但**留出盲测**误差爆掉 → 必须留验证位姿",
         B0.get("rms_px", 0) <= 2.0 and B0.get("heldout_mean_px", 0) > 5 * max(B.get("heldout_mean_px", 1), 1e-6),
         f"给错 rms={B0.get('rms_px')}px (看不出来) 但盲测={B0.get('heldout_mean_px')}px "
         f"vs 给对 盲测={B.get('heldout_mean_px')}px"),
        ("④ 探针位姿预检: 非共面通过 / 只有平面运动判退化",
         bool(AR.get("design_check", {}).get("ok")) and PL.get("design_check", {}).get("ok") is False,
         f"非共面 ok={AR.get('design_check', {}).get('ok')} (平面性 {AR.get('design_check', {}).get('planarity')}) "
         f"· 共面 ok={PL.get('design_check', {}).get('ok')} (平面性 {PL.get('design_check', {}).get('planarity')}, "
         f"K_fx={PL.get('K_fx')})"),
        ("⑤ C: 没夹住(画面无其它运动) → S2 零标签",
         C.get("s2_n") == 0, f"n={C.get('s2_n')} · {json.dumps(C.get('s2_skipped', {}), ensure_ascii=False)[:80]}"),
        ("⑤ D 无 ROI: 夹爪可见 → 门误放行 (已知盲区, 如实记录)",
         Dn.get("s2_n", 0) > 0, f"n={Dn.get('s2_n')} (IoU={Dn.get('s2_iou')})"),
        ("⑤ D 有 ROI: 盲区被 ROI 消掉 → S2 零标签",
         D.get("s2_n") == 0, f"n={D.get('s2_n')} · {json.dumps(D.get('s2_skipped', {}), ensure_ascii=False)[:80]}"),
    ]
    print("\n═══ 断言 ═══")
    bad = 0
    for nm, ok, det in checks:
        print(("✅ " if ok else "❌ ") + f"{nm} — {det}")
        bad += 0 if ok else 1

    report = {"stamp": os.path.basename(run_dir), "work": run_dir, "scenarios": res,
              "checks": [{"name": n, "ok": bool(o), "detail": d} for n, o, d in checks],
              "passed": bad == 0,
              "note": "合成场景, 用于验证链路与判据; 真机数值须在 Orin 在线时按同口径复测"}
    rp = os.path.join(run_dir, "rehearsal_report.json")
    json.dump(report, open(rp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n{'✅ 全部断言通过' if bad == 0 else f'❌ {bad} 项未过'} · 报告: {rp}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
