"""规整度度量口径对比: 同一张裁剪图, 4 种掩膜/行选择下算斜率, 选最稳的口径"""
import cv2
import numpy as np
import sys
sys.path.insert(0, "/home/ubuntu/aoi_v4")
from gf_template import build_template
from gf_metric import gold_mask as gm_free, centerline_slope
from gf_crop import GoldFingerCropper

REF = "/home/ubuntu/aoi_v4/imgs/Finger_Image_W2448_H2048_No_8.png"
tpl, meta = build_template(REF)
cr = GoldFingerCropper(tpl, canonical_w=1600, canonical_h=220, margin_x=0.03, margin_y=0.04,
                       preserve_aspect=True)

for name in ["No_3", "No_5", "No_7", "No_8", "No_9"]:
    im = cv2.imread(f"/home/ubuntu/aoi_v4/imgs/Finger_Image_W2448_H2048_{name}.png")
    crop, info = cr.crop(im)
    out = {}
    for tag, k in [("k41x5", (41, 5)), ("k5x5", (5, 5)), ("k1x1", None)]:
        m = gm_free(crop, k=k)
        rows = (m > 0).sum(axis=1)
        dmax = rows.max()
        for sub_tag, frac in [("all", 0.0), ("d85", 0.85), ("d95", 0.95)]:
            mm = m
            if frac > 0:
                idx = np.where(rows > frac * dmax)[0]
                if len(idx) > 8:
                    mm = np.zeros_like(m)
                    mm[idx.min() - 3:idx.max() + 4, :] = m[idx.min() - 3:idx.max() + 4, :]
            s, res, cols = centerline_slope(mm, min_gold=8)
            out[f"{tag}/{sub_tag}"] = (None if s is None else round(s, 2),
                                       None if res is None else round(res, 2))
    print(f"\n{name}  (crop {crop.shape[1]}x{crop.shape[0]}, 角度 {info['angle']}, score {info['score']})")
    for k, v in out.items():
        print(f"   {k:<14} 斜率={v[0]!s:>8} 残差={v[1]!s:>7}")
