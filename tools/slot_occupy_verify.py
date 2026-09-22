#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""slot_occupy_verify.py — 对 slot_occupy 结论做**不依赖 YOLO** 的像素级复核 + 出证据图

为什么要有它 (老倪口径: 画面自身要标状态; 结论要有第二条独立证据):
  slot_occupy 的结论来自 YOLO 框 + 手眼投影对账; 若 YOLO 框漂了, 结论会跟着漂。
  这里用**原始像素**独立判一次: 在 slot1/slot2 各自的手眼投影处取同尺寸 ROI, 量
  ①垂直边缘能量(模块金属棱边) ②竖直连续亮带高度(模块本体 vs 空槽底) ③对比度,
  谁显著高谁就有件 —— 与 YOLO 结论相互独立, 一致才认。
输出: 终端对照表 + 证据图 ~/zmax_data/ss_slot_occupy_evidence.png (白框/十字/文字标注)
只读, 不含任何运动指令。
"""
from __future__ import annotations

import json
import os
import sys

import cv2
import numpy as np

REPO = "/home/ubuntu/lerobot-smolvla-lew"
IMG = os.path.expanduser("~/zmax_ss_remote/cam_rs.png")
OUT = os.path.expanduser("~/zmax_data/ss_slot_occupy_evidence.png")
sys.path.insert(0, os.path.join(REPO, "tools"))


def load_inputs():
    """与 slot_occupy.py 完全同源: K/畸变 + 手眼 X + 当前 TCP + 槽位示教点 + YOLO 检出"""
    import slot_occupy as so                                        # noqa: PLC0415
    cal = json.load(open(so.CALIB, encoding="utf-8"))
    k = cal["K"]
    Km = np.array([[k[0], 0, k[2]], [0, k[4], k[5]], [0, 0, 1]], float)
    dist = np.array(cal.get("dist") or [0, 0, 0, 0, 0], float)
    X = np.array(json.load(open(so.STATE, encoding="utf-8"))["T_cam2tool"], float)
    slots = json.load(open(so.PTS, encoding="utf-8"))
    slots = slots.get("points", slots)
    pos, quat = so.tcp_pose()
    G = np.eye(4)
    G[:3, :3] = so.R_from_quat(quat)
    G[:3, 3] = pos
    T_cam_base = np.linalg.inv(G @ X)
    proj = {}
    for nm in ("slot1", "slot2"):
        ent = slots.get(nm)
        p = (ent or {}).get("pos") if isinstance(ent, dict) else ent
        if not p:
            continue
        pc = T_cam_base @ np.array([p[0], p[1], p[2], 1.0])
        if pc[2] <= 0.05:
            continue
        uv, _ = cv2.projectPoints(np.array([[0.0, 0.0, 0.0]]), np.zeros(3),
                                  pc[:3].reshape(3, 1), Km, dist)
        uv = uv.reshape(2)
        proj[nm] = (float(uv[0]), float(uv[1]), float(pc[2]))
    det = json.load(open(so.DET, encoding="utf-8"))
    return pos, proj, det


def main() -> int:
    img = cv2.imread(IMG, cv2.IMREAD_GRAYSCALE)
    col = cv2.imread(IMG)
    if img is None:
        print("❌ 读不到帧", IMG)
        return 1
    H, W = img.shape
    pos, proj, det = load_inputs()
    print(f"帧: {IMG}  {W}x{H}")
    print(f"当前工具位姿(基座): [{pos[0]:.4f}, {pos[1]:.4f}, {pos[2]:.4f}]")
    print(f"检出帧龄: {det.get('frame_age_s', -1)}s · 检出数: {det.get('n', 0)}")
    for nm, (u, v, dd) in proj.items():
        print(f"  {nm} 投影: 像素({u:.1f},{v:.1f}) · 距相机 {dd:.3f}m")

    RH, RW = 150, 44          # ⚠️ 槽间距只有 ~46px → 窗必须窄, 否则两槽 ROI 互相重叠, 判据失效
    print(f"\n{'槽位':6s}{' ROI x[):':>16s}{'边缘能量':>10s}{'亮带高度':>10s}{'对比度':>9s}{'像素判定':>10s}")
    stat = {}
    for nm, (u, v, _d) in proj.items():
        x0 = int(max(0, u - RW // 2)); x1 = int(min(W, u + RW // 2))
        y1 = int(min(H, v + 10)); y0 = int(max(0, y1 - RH))
        roi = img[y0:y1, x0:x1].astype(np.float32)
        gx = float(np.abs(np.diff(roi, axis=1)).mean())
        ys = roi.mean(axis=1)
        m = float(np.median(roi))
        best = cur = 0
        for b in (ys > m + 12).astype(int):
            cur = cur + 1 if b else 0
            best = max(best, cur)
        contrast = float(np.percentile(roi, 85) - np.percentile(roi, 20))
        stat[nm] = {"gx": gx, "band": int(best), "contrast": contrast,
                    "roi": (x0, y0, x1, y1)}
        print(f"  {nm:6s}{f'[{x0},{x1})x[{y0},{y1})':>16s}{gx:10.2f}{best:10d}{contrast:9.1f}")

    # ★ 模型无关的判据: 全图「竖直棱边能量」列剖面 (只看模块所在竖直带) → 峰值列在哪
    band = img[int(min(v for _u, v, _d in proj.values())) - 140:
               int(max(v for _u, v, _d in proj.values())) + 8, :].astype(np.float32)
    prof = np.abs(np.diff(band, axis=1)).sum(axis=0)          # 每列竖直棱边总量
    k = 25                                                    # 平滑窗, 抗单列噪点
    prof_s = np.convolve(prof, np.ones(k) / k, mode="same")
    top = np.argsort(prof_s)[::-1]
    peaks = []
    for c in top:
        if all(abs(int(c) - p) > 30 for p in peaks):
            peaks.append(int(c))
        if len(peaks) == 3:
            break
    print(f"\n  全图竖直棱边列剖面 (y 带 {int(min(v for _u, v, _d in proj.values())) - 140}"
          f"..{int(max(v for _u, v, _d in proj.values())) + 8}) 前 3 峰列 x = {peaks}")
    for nm, (u, v, _d) in proj.items():
        near = min(abs(p - u) for p in peaks)
        print(f"    {nm} 投影 x={u:.1f} → 距最近棱边峰 {near:.1f}px "
              f"{'✅ 峰就在该槽' if near <= 20 else '✗ 该槽附近无强棱边'}")
    pix_slot = min(proj, key=lambda nm: min(abs(p - proj[nm][0]) for p in peaks))
    near_best = min(min(abs(p - proj[nm][0]) for p in peaks) for nm in proj)
    print(f"  像素判据(棱边峰值列归属): {pix_slot if near_best <= 20 else '不确定'}"
          f"  (最近峰距 {near_best:.1f}px)")

    yolo_slot, yolo_line = None, "无检出"
    dets = det.get("detections") or []
    if dets:
        d0 = dets[0]
        bx0, by0, bx1, by1 = d0["xyxy"]
        bcx, bby = (bx0 + bx1) / 2, by1
        yolo_line = (f"框 conf={d0['conf']:.2f} 底心({bcx:.0f},{bby:.0f})")
        print(f"\n  YOLO {yolo_line}")
        for nm, (u, v, _d) in proj.items():
            dx, dy = abs(bcx - u), bby - v
            hit = dx <= 12.0 and -5.0 <= dy <= 25.0
            print(f"    {nm}: Δx={dx:5.1f}px  框底-投影={dy:+6.1f}px  → {'✅ 对上' if hit else '✗'}")
            if hit:
                yolo_slot = nm
    print(f"\n  YOLO 判位: {yolo_slot} · 像素判位: {pix_slot if near_best <= 20 else '不确定'}  → "
          f"{'✅ 两路一致' if yolo_slot and near_best <= 20 and pix_slot == yolo_slot else '⚠️ 未双路一致, 人工看画面再定'}")
    for nm, (u, v, _d) in proj.items():
        print(f"    {nm}: 边缘能量 {stat[nm]['gx']:.2f} · 亮带 {stat[nm]['band']}px")

    # 证据图 (单色标注, 不花)
    for nm, (u, v, dd) in proj.items():
        x0, y0, x1, y1 = stat[nm]["roi"]
        cv2.rectangle(col, (x0, y0), (x1, y1), (255, 255, 255), 1)
        cv2.drawMarker(col, (int(u), int(v)), (255, 255, 255), cv2.MARKER_CROSS, 14, 1)
        cv2.putText(col, f"{nm} d={dd:.3f}m gx={stat[nm]['gx']:.1f} band={stat[nm]['band']}",
                    (x0, max(12, y0 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
    if dets:
        bx0, by0, bx1, by1 = dets[0]["xyxy"]
        cv2.rectangle(col, (int(bx0), int(by0)), (int(bx1), int(by1)), (255, 255, 255), 2)
        cv2.putText(col, f"YOLO peg {dets[0]['conf']:.2f}",
                    (int(bx0), max(12, int(by0) - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    cv2.putText(col, f"module in {str(yolo_slot).upper()} | age {det.get('frame_age_s')}s",
                (8, H - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    cv2.imwrite(OUT, col)
    print(f"\n证据图: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
