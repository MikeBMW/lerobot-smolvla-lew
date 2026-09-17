#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""(可复用) 真机测集自检: 画面里到底有没有"可检目标"? (不需要模型, 纯图像统计)

用途: 判定"模型 0 检出"是**模型问题**还是**测集问题** — 如果目标区域本身没有结构 (纯背景/纯黑),
那 0 检出不能算模型的锅, 必须先修采集 (相机朝向/对焦/光照)。

给出的事实 (可核查):
  · 指定 ROI (默认画面下方正中 = 光模块现场位置) 的梯度能量密度 vs 全图
  · ROI 内最大边缘连通块面积 (物体应成块; 背景纹理是零散小点)
  · 3x3 区带里"最物体化"的区带 → 物体实际落在画面哪个位置
  · 退化帧 (纯色/纯黑, std<5) 单独列出并从分母剔除

用法: python tools/real_frame_selfcheck.py --src ~/zmax_data/real_cam/orin_d405_eval \
        --out reports/sim2real_20260917/real_frame_selfcheck.json --roi 0.30 0.60 0.70 1.00
"""
import argparse, glob, json, os
import cv2
import numpy as np


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="/home/ubuntu/zmax_data/real_cam/orin_d405_eval")
    ap.add_argument("--out", default="reports/sim2real_20260917/real_frame_selfcheck.json")
    ap.add_argument("--roi", nargs=4, type=float, default=[0.30, 0.60, 0.70, 1.00],
                    metavar=("X0", "Y0", "X1", "Y1"), help="ROI 归一化 (默认下方正中)")
    ap.add_argument("--std-min", type=float, default=5.0, help="退化帧阈值 (std)")
    args = ap.parse_args()

    rows = []
    for p in sorted(glob.glob(os.path.join(os.path.expanduser(args.src), "*.jpg")) +
                    glob.glob(os.path.join(os.path.expanduser(args.src), "*.png"))):
        img = cv2.imread(p)
        if img is None:
            continue
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        h, w = g.shape
        if float(g.std()) < args.std_min:
            rows.append({"frame": os.path.basename(p), "degenerate": True,
                         "note": f"纯色/纯黑帧 (mean={g.mean():.1f} std={g.std():.1f}) — 从分母剔除"})
            continue
        lab = cv2.Laplacian(g, cv2.CV_32F)
        x0, y0, x1, y1 = args.roi
        roi = lab[int(h * y0):int(h * y1), int(w * x0):int(w * x1)]
        bw = (np.abs(roi) > 40).astype(np.uint8)
        n, _, stats, _ = cv2.connectedComponentsWithStats(bw, 8)
        big = 0 if n <= 1 else int(stats[1:, cv2.CC_STAT_AREA].max())
        grid = []
        for i in range(3):
            for j in range(3):
                blk = lab[int(h * i / 3):int(h * (i + 1) / 3), int(w * j / 3):int(w * (j + 1) / 3)]
                grid.append(round(float(np.abs(blk).mean()), 1))
        gi = int(np.argmax(grid))
        rows.append({"frame": os.path.basename(p),
                     "roi_edge_density": round(float(np.abs(roi).mean()), 1),
                     "global_edge_density": round(float(np.abs(lab).mean()), 1),
                     "roi_max_blob_px": big,
                     "most_objectlike_band": f"行{gi // 3 + 1}列{gi % 3 + 1} (密度 {grid[gi]})",
                     "grid_density": grid})

    valid = [r for r in rows if not r.get("degenerate")]
    print(f"帧 {len(rows)} 张 (退化剔除 {len(rows) - len(valid)}) · ROI={args.roi}")
    print(f"{'帧':34s} {'ROI梯度':>8s} {'全图梯度':>8s} {'ROI最大块px':>10s}  最物体化区带")
    for r in valid:
        print(f"{r['frame'][:33]:34s} {r['roi_edge_density']:8.1f} {r['global_edge_density']:8.1f} "
              f"{r['roi_max_blob_px']:10d}  {r['most_objectlike_band']}")
    if valid:
        roi = np.array([r["roi_edge_density"] for r in valid])
        glb = np.array([r["global_edge_density"] for r in valid])
        blob = np.array([r["roi_max_blob_px"] for r in valid])
        print(f"\nROI 梯度密度 {roi.mean():.1f} vs 全图 {glb.mean():.1f} → ROI/全图 = {roi.mean()/glb.mean():.2f}")
        print(f"ROI 内最大边缘连通块: 中位 {int(np.median(blob))}px (min {blob.min()} / max {blob.max()})")
        print(f"→ 最大块 <50px 的帧: {int((blob < 50).sum())}/{len(valid)} "
              f"(这些帧目标区几乎没结构, 0 检出不代表模型差)")
    if args.out:
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        json.dump({"roi": args.roi, "frames": rows}, open(args.out, "w"), ensure_ascii=False, indent=1)
        print(f"→ {args.out}")


if __name__ == "__main__":
    main()
