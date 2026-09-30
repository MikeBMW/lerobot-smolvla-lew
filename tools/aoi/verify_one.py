"""单张深查: 裁剪结果长什么样 (ASCII 可视化, 无眼也能判framing) + 指标"""
import cv2
import numpy as np
import sys
import os

sys.path.insert(0, "/home/ubuntu/aoi_v4")
from gf_template import build_template, measure_strip
from gf_metric import gold_mask, centerline_slope, core_band_slope
from gf_crop import GoldFingerCropper, annotate

D = "/home/ubuntu/aoi_v4/imgs"
REF = os.path.join(D, "Finger_Image_W2448_H2048_No_8.png")
tpl, meta = build_template(REF)
crop = GoldFingerCropper(tpl, canonical_w=1600, canonical_h=220, margin_x=0.03, margin_y=0.04,
                         preserve_aspect=True)
RAMP = " .:-=+*#%@"


def amap(a, cols=100, rows=16, label=""):
    s = cv2.resize(a.astype(np.float32), (cols, rows), interpolation=cv2.INTER_AREA)
    lo, hi = float(s.min()), float(s.max())
    print(f"--- {label} ({a.shape[1]}x{a.shape[0]} → {cols}x{rows} 格; {lo:.0f}..{hi:.0f}) ---")
    for r in range(rows):
        print("   " + "".join(RAMP[min(9, int((s[r, c] - lo) / max(hi - lo, 1e-6) * 9))] for c in range(cols)))


for name in ["Finger_Image_W2448_H2048_No_8.png", "Finger_Image_W2448_H2048_No_5.png"]:
    p = os.path.join(D, name)
    im = cv2.imread(p)
    out, info = crop.crop(im)
    print(f"\n########## {name} ##########")
    print(f"方法={info['method']} score={info['score']} 角={info['angle']}° 尺度={info['scale']}")
    print(f"条(源图): {info['strip']}")
    print(f"质量: {info['quality']}")
    print(f"警示: {info.get('warn','无')}")
    gm = gold_mask(out, k=(41, 5))
    amap(cv2.cvtColor(out, cv2.COLOR_BGR2GRAY), label="v4 裁剪图 亮度")
    amap(gm, label="v4 裁剪图 金色掩膜 (条应当横贯整幅且居中)")
    rows = (gm > 0).sum(axis=1)
    idx = np.where(rows > 0.35 * rows.max())[0]
    print(f"条在裁剪图里占行 [{idx.min()},{idx.max()}] / 共 {out.shape[0]} 行; "
          f"列覆盖 (有金的列数) {int((gm.sum(axis=0) > 0).sum())}/{out.shape[1]}")
    s, res, cols = core_band_slope(gm, min_gold=8)
    print(f"条质心线: 斜率 {s}px/1000 残差 {res}px 有效列 {cols}")
    g2 = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
    bright = int((g2 > 180).sum())
    print(f"高亮(>180)像素: {bright} = 裁剪的 {bright/g2.size*100:.2f}%  ← '大边沿'若在裁剪里这个数会很大")
    rp = (gm > 0).sum(axis=1)
    lp = g2.mean(axis=1)
    print(f"逐行剖面 (行: 金像素/亮度):")
    for y in range(0, out.shape[0], 6):
        print(f"   y={y:4d} 金={rp[y]:5d} 亮度={lp[y]:6.1f} {'#'*int(rp[y]/out.shape[1]*40)}")
    cv2.imwrite(f"/home/ubuntu/aoi_v4/out/v4crop_{name[-6:-4]}.png", out)
    cv2.imwrite(f"/home/ubuntu/aoi_v4/out/anno_{name[-6:-4]}.png", annotate(im, info))
