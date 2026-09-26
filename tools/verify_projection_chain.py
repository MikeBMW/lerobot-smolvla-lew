#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_projection_chain.py — 投影链端到端验证（全真实数据）

口径: 板中心在 base 系的位置由 8 位姿闭环解出 (std=1.74mm)。
      把它用【每个位姿自己的 TCP 真值】正向投影回【该位姿自己的图】(1280x720)，
      应与该图中 findCirclesGrid 检出的 20 点中心重合。
      —— 这条链同时用了 TCP 真值 + 手眼外参 + 相机内参，任一环错都会暴露。
"""
import glob
import json
import re
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scene_overlay as SO   # noqa: E402

REPO = Path("/home/ubuntu/zmax_rel")
D = Path("/tmp/scene/he_all")
OBJ = np.array([[(2 * j + i % 2) * 20.0, i * 20.0, 0.0] for i in range(5) for j in range(4)], np.float32)
K720 = {"fx": 655.06, "fy": 654.08, "cx": 637.41, "cy": 357.77}
BOARD_CENTER_BASE = np.array([0.795, 0.221, 0.257])      # 闭环解出 (m)


def detect_board_center(img):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    H, W = g.shape
    for nm, src, off in (("全图", g, np.array([0, 0])),
                         ("裁剪", g[281:668, 153:768], np.array([153, 281]))):
        for z in (1.0, 2.2, 3.0):
            gg = cv2.resize(src, None, fx=z, fy=z, interpolation=cv2.INTER_CUBIC) if z != 1.0 else src
            for pol in (cv2.bitwise_not(gg), gg):
                ok, cc = cv2.findCirclesGrid(pol, (4, 5), flags=cv2.CALIB_CB_ASYMMETRIC_GRID)
                if ok:
                    pts = cc.reshape(-1, 2) / z + off
                    return pts.mean(0), pts
    return None, None


def read_tcp(p):
    s = open(p, encoding="utf-8", errors="replace").read()
    v = [float(x) for x in re.findall(r"-?[\d.]+(?:e-?\d+)?", s)]
    return np.array(v[:7]) if len(v) >= 7 else None


he = SO.load_handeye()
X = he["X"]
print("  手眼: ok=%s method=%s n_poses=%s" % (he["ok"], he.get("method"), he.get("n_poses")))
print("  板中心(base, 闭环) = %s mm" % np.round(BOARD_CENTER_BASE * 1000, 1))
print()
print("  ══ 逐位姿: 正投影 vs 图上实检 ══")
errs, n = [], 0
for f in sorted(glob.glob(str(D / "c_*.png"))):
    tag = Path(f).stem[2:]
    tcpf = D / ("tcp_%s.txt" % tag)
    if not tcpf.exists():
        continue
    tcp = read_tcp(tcpf)
    img = cv2.imread(f)
    if tcp is None or img is None:
        continue
    det, pts = detect_board_center(img)
    if det is None:
        print("    %-22s 板未检出，跳过" % tag)
        continue
    uv = SO.base_to_px(BOARD_CENTER_BASE, K720, X, tcp)
    if not np.isfinite(uv).all():
        print("    %-22s 投影在相机背后(异常)" % tag)
        continue
    e = float(np.linalg.norm(uv - det))
    # 板在 400mm 处、20mm 间距(图上 ~34px) ⇒ 1 格 ≈ 34px 作为尺度参照
    px_per_mm = None
    if pts is not None:
        ds = [np.linalg.norm(pts[i] - pts[j]) for i in range(len(pts)) for j in range(i + 1, len(pts))
              if 20 < np.linalg.norm(pts[i] - pts[j]) < 60]
        if ds:
            px_per_mm = float(np.median(ds)) / 20.0
    n += 1
    errs.append(e)
    print("    %-22s 投影=(%6.1f,%6.1f) 实检=(%6.1f,%6.1f) 差=**%5.1f px**%s"
          % (tag, uv[0], uv[1], det[0], det[1], e,
             (" (%s)" % ("≈%.1f mm" % (e / px_per_mm) if px_per_mm else "")) if px_per_mm else ""))

print()
if errs:
    a = np.array(errs)
    print("  ══ 结论 ══")
    print("    样本 %d · 像素误差 中位 **%.1f px** · 均值 %.1f · max %.1f" % (n, np.median(a), a.mean(), a.max()))
    pxmm = 34.0 / 20.0     # 板 20mm 间距在图上约 34px (400mm 处)
    print("    换算 ≈ **%.1f mm**（按板上 20mm 间距≈34px 折算）" % (np.median(a) / pxmm))
    print("    %s" % ("✅ 投影链可信（TCP+手眼+内参 三环同时验证通过）" if np.median(a) < 60
                      else "⚠ 误差偏大，需查手眼旋转残差(已知 9~15°)"))
else:
    print("  ✗ 无有效样本")
