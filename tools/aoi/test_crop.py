"""v4 离线验证: 模板法 vs v3 现状 —— 真图, 量化指标 + 证据图
判据: 裁剪内金手指条 ①顶边斜率(px/1000) ②顶边残差std ③金覆盖率(裁进来多少金/全图金) ④跨张一致性
"""
import cv2
import numpy as np
import glob
import os
import sys
import time

sys.path.insert(0, "/home/ubuntu/aoi_v4")
from gf_template import build_template, measure_strip
from gf_metric import gold_mask, centerline_slope, core_band_slope, top_edge_slope, core_band_slope
from gf_crop import GoldFingerCropper, annotate

D = "/home/ubuntu/aoi_v4/imgs"
OUT = "/home/ubuntu/aoi_v4/out"
os.makedirs(OUT, exist_ok=True)
REF = os.path.join(D, "Finger_Image_W2448_H2048_No_8.png")

print("① 先量参考图的金手指条几何 (逐行/逐列剖面 + 用\"去倾斜后顶边最平\"定倾角):")
rref = measure_strip(cv2.imread(REF), verbose=True)
print(f"   参考图: 条 {rref['w']:.0f}x{rref['h']:.0f} @({rref['cx']:.0f},{rref['cy']:.0f}) 倾角 {rref['tilt']:+.2f}°")
tpl_path, meta = build_template(REF, verbose=True)

# 两种规范化模式: ①保比例(几何诚实, 默认) ②1600x220(旧文件名口径)
crop_asp = GoldFingerCropper(tpl_path, canonical_w=1600, canonical_h=220,
                             margin_x=0.03, margin_y=0.04, preserve_aspect=True)
crop_220 = GoldFingerCropper(tpl_path, canonical_w=1600, canonical_h=220,
                             margin_x=0.03, margin_y=0.10, preserve_aspect=False)


def v3_view(im, out_w=1600, out_h=220, legacy_size=False):
    h, w = im.shape[:2]
    ow, oh = (w, h) if legacy_size else (out_w, out_h)
    src = np.float32([[400, 1000], [2000, 1000], [2000, 1250], [400, 1250]])
    dst = np.float32([[0, 0], [ow, 0], [ow, oh], [0, oh]])
    return cv2.warpPerspective(im, cv2.getPerspectiveTransform(src, dst), (ow, oh))


def metrics(im, full=None):
    gm = gold_mask(im)
    s, res, cols = core_band_slope(gm, min_gold=8)
    cover = None
    if full is not None:
        gf = gold_mask(full)
        for_ = gm.sum() / 255.0, gf.sum() / 255.0
        cover = round(for_[0] / max(for_[1], 1e-6), 3)
    return {"size": (im.shape[1], im.shape[0]), "gold_frac": round(gm.mean() / 255 * 100, 2),
            "slope": None if s is None else round(s, 2), "cols": cols,
            "resid": None if res is None else round(res, 2), "cover": cover}


print("\n" + "=" * 118)
print(f"{'图':<9}{'方案':<26}{'尺寸':<12}{'金占比%':>8}{'金覆盖':>8}{'条质心线斜率/1000':>14}{'残差px':>11}{'score':>8}{'PSR':>7}{'角°':>7}{'耗时ms':>8}")
print("=" * 118)
rows = []
for p in sorted(glob.glob(os.path.join(D, "Finger_Image_*.png"))):
    im = cv2.imread(p)
    name = os.path.basename(p)[-10:-4]
    m3 = metrics(v3_view(im, legacy_size=True), im)
    m3b = metrics(v3_view(im), im)
    t0 = time.time(); c4, info4 = crop_asp.crop(im); dt4 = (time.time() - t0) * 1000
    m4 = metrics(c4, im)
    c5, info5 = crop_220.crop(im)
    m5 = metrics(c5, im)
    def line(tag, m, extra=""):
        print(f"{name if tag.startswith('v3 现状') else '':<9}{tag:<26}{str(m['size']):<12}{m['gold_frac']:>8.2f}"
              f"{str(m['cover']):>8}{str(m['slope']):>14}{str(m['resid']):>11}{extra}")
    line("v3 现状(固定窗→拉原尺寸)", m3, f"{'-':>8}{'-':>7}{'-':>7}{'-':>8}")
    line("v3 按设计(固定窗→1600x220)", m3b, f"{'-':>8}{'-':>7}{'-':>7}{'-':>8}")
    line("v4 模板法·保比例 ★", m4, f"{info4['score']:>8.3f}{info4.get('psr', '-'):>7}{info4['angle']:>7.2f}{dt4:>8.0f}")
    line("v4 模板法·1600x220", m5, f"{info5['score']:>8.3f}{info5.get('psr', '-'):>7}{info5['angle']:>7.2f}")
    rows.append((name, m3, m3b, m4, m5, info4, info5))
    # 证据图: 标注原图 + v3现状 + v4保比例 + v4 1600x220
    ann = annotate(im, info4)
    W = 900
    def fit(x):
        return cv2.resize(x, (W, max(1, int(W * x.shape[0] / x.shape[1]))))
    imgs = [fit(ann), fit(v3_view(im, legacy_size=True)), fit(v3_view(im)), fit(c4), fit(c5)]
    labs = ["RAW 2448x2048 + detected strip (red box)",
            f"v3 current: fixed window stretched to {im.shape[1]}x{im.shape[0]}",
            "v3 designed: fixed window -> 1600x220",
            f"v4 template aspect-keep {c4.shape[1]}x{c4.shape[0]} score={info4['score']:.3f}",
            f"v4 template 1600x220 score={info5['score']:.3f}"]
    for a, l in zip(imgs, labs):
        cv2.putText(a, l, (10, 34), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
        cv2.line(a, (0, 42), (a.shape[1], 42), (0, 255, 0), 1)
    cv2.imwrite(os.path.join(OUT, f"compare_{name}.png"), np.vstack(imgs))
    cv2.imwrite(os.path.join(OUT, f"v4crop_{name}.png"), c4)

print()
print("=" * 112)
print("跨张一致性 (v4 保比例): 条几何 / 角度 / 覆盖率 / 方法")
print("=" * 112)
for name, m3, m3b, m4, m5, i4, i5 in rows:
    s = i4["strip"]
    print(f"{name}: 条中心=({s['cx']:6.0f},{s['cy']:6.0f}) 条={s['w']:.0f}x{s['h']:.0f} 角={s['angle']:+.2f}° "
          f"score={i4['score']:.3f} PSR={i4.get('psr')} 金覆盖={m4['cover']} 斜率={m4['slope']} "
          f"方法={i4['method']} {i4.get('warn','')}")
print("\n证据图:", OUT)
