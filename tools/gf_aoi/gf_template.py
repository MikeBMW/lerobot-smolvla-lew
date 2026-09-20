"""模板生成 (离线) —— 参考图 → 去倾斜的金手指条模板 + 几何 sidecar
角度约定: tilt = 用 cv2.getRotationMatrix2D(center, tilt, 1.0) 旋转后, 条质心线水平 (斜率≈0)。
tilt 由"旋转后质心线斜率最小"直接裁决 (不做任何符号推理)。
"""
import cv2
import numpy as np
import os
import json
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gf_metric import gold_mask, centerline_slope


def _band_extent(counts, frac=0.35):
    mx = counts.max()
    if mx <= 0:
        return None
    idx = np.where(counts > frac * mx)[0]
    if len(idx) == 0:
        return None
    c = int(counts.argmax())
    lo_ = c
    while lo_ - 1 in idx and lo_ > 0:
        lo_ -= 1
    hi_ = c
    while hi_ + 1 in idx and hi_ < len(counts) - 1:
        hi_ += 1
    return int(lo_), int(hi_)


def roi_extent(im, m=None, dens_frac=0.05, dens_min=25, bridge=35, lum_cut=1.25, cut_off=6, verbose=False):
    """金手指区范围 (修 framing: 上面漏掉"焊盘排" / 下面多出"塑料本体亮边沿")
    ① 最大金连通域 → 列段 x0..x1 (剔掉画面别处的杂金, 不做横向搭桥以免把邻区连进来)
    ② 列段内行密度 d(y): 以最密行为中心, 允许 <=bridge 行空隙地向上下扩展
       (焊排与下部金带之间那条 20~30 行的缝靠这个跨过去; 再远就不认, 防止跳到画面别处的金)
    ③ 亮带保险: 行亮度中位数 × lum_cut 以上算"高亮塑料本体反光", 从尾部/头部回退掉
    返回 (x0, x1, ytop, ybot)"""
    if m is None:
        m = gold_mask(im, k=(9, 9))
    n, lab, stats, _ = cv2.connectedComponentsWithStats((m > 0).astype(np.uint8), 8)
    if n <= 1:
        return None
    i = 1 + int(np.argmax(stats[1:, 4]))
    x0, x1 = int(stats[i, 0]), int(stats[i, 0] + stats[i, 2] - 1)
    sub = m[:, x0:x1 + 1]
    rows = (sub > 0).sum(axis=1)
    dmax = int(rows.max())
    if dmax <= 0:
        return None
    thr = max(dens_min, dens_frac * dmax)
    idx = np.where(rows > thr)[0]
    if len(idx) == 0:
        return None
    cy = int(rows.argmax())
    ytop = cy
    while True:
        nxt = idx[idx < ytop]
        if len(nxt) and ytop - nxt[-1] <= bridge:
            ytop = int(nxt[-1])
        else:
            break
    ybot = cy
    while True:
        nxt = idx[idx > ybot]
        if len(nxt) and nxt[0] - ybot <= bridge:
            ybot = int(nxt[0])
        else:
            break
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    prof = g[:, x0:x1 + 1].mean(axis=1).astype(np.float32)
    band_lum = float(np.median(prof[ytop:ybot + 1]))
    ceil = max(band_lum * lum_cut, band_lum + 15.0, 55.0)
    while ybot > ytop and prof[ybot] > ceil:
        ybot -= 1
    while ytop < ybot and prof[ytop] > ceil:
        ytop += 1
    if verbose:
        print(f"    ROI: 列段 x[{x0},{x1}] 宽{x1-x0+1} | 行密度峰 {dmax} 阈值 {thr:.0f} 空隙容限 {bridge}行 "
              f"→ 行段 y[{ytop},{ybot}] 高{ybot-ytop+1} | 行亮度中位 {band_lum:.0f} 亮带判据 >{ceil:.0f}")
    return int(x0), int(x1), int(ytop), int(ybot)


def measure_strip(im, verbose=False, top_extra=6, bottom_extra=0):
    """金手指条几何 {cx,cy,w,h,tilt} —— 覆盖整块金手指区(含上排焊盘 + 下部金带), 不含底部塑料亮边沿"""
    m = gold_mask(im, k=(9, 9))
    ext = roi_extent(im, m, verbose=verbose)
    if ext is None:
        return None
    x0, x1, y0, y1 = ext
    y0e, y1e = max(0, y0 - top_extra), min(m.shape[0] - 1, y1 + bottom_extra)
    roi = np.zeros_like(m)
    roi[y0e:y1e + 1, x0:x1 + 1] = m[y0e:y1e + 1, x0:x1 + 1]
    cnts, _ = cv2.findContours(roi, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    cxr, cyr = (x0 + x1) / 2.0, (y0e + y1e) / 2.0
    # 倾角: 枚举小角, 让"ROI 内金像素质心线"最平 (符号不用猜)
    best = None
    for t in np.arange(-3.0, 3.0001, 0.05):
        M = cv2.getRotationMatrix2D((cxr, cyr), float(t), 1.0)
        r = cv2.warpAffine(m, M, (m.shape[1], m.shape[0]), flags=cv2.INTER_NEAREST)
        bb = np.zeros_like(r)
        bb[y0e:y1e + 1, x0:x1 + 1] = r[y0e:y1e + 1, x0:x1 + 1]
        s, resid, n = centerline_slope(bb, min_gold=8)
        if s is None:
            continue
        if best is None or abs(s) < best[0]:
            best = (abs(s), float(t))
    tilt = best[1] if best else 0.0
    w2, h2 = float(x1 - x0 + 1), float(y1e - y0e + 1)
    if verbose:
        print(f"    条(整块金手指区): {w2:.0f}x{h2:.0f} @({cxr:.0f},{cyr:.0f}) 倾角 {tilt:+.2f}° "
              f"(质心线残差评分 {best[0] if best else float('nan'):.2f})")
    return {"cx": cxr, "cy": cyr, "w": w2, "h": h2, "tilt": tilt,
            "roi_rows": [int(y0e), int(y1e)], "roi_cols": [int(x0), int(x1)]}


def build_template(ref_png, name="gf_strip_template", mx_ratio=0.02, my_ratio=0.06, verbose=True):
    im = cv2.imread(ref_png)
    r = measure_strip(im, verbose=verbose)
    assert r, "参考图里找不到金手指条"
    cx, cy, w, h, tilt = r["cx"], r["cy"], r["w"], r["h"], r["tilt"]
    M = cv2.getRotationMatrix2D((cx, cy), tilt, 1.0)
    dk = cv2.warpAffine(im, M, (im.shape[1], im.shape[0]), flags=cv2.INTER_LINEAR,
                        borderMode=cv2.BORDER_REPLICATE)
    mx, my = int(round(w * mx_ratio)), int(round(h * my_ratio))
    x0 = int(round(cx - w / 2 - mx)); x1 = int(round(cx + w / 2 + mx))
    y0 = int(round(cy - h / 2 - my)); y1 = int(round(cy + h / 2 + my))
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(x1, dk.shape[1]), min(y1, dk.shape[0])
    tpl = dk[y0:y1, x0:x1].copy()
    outdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
    os.makedirs(outdir, exist_ok=True)
    out_png = os.path.join(outdir, name + ".png")
    cv2.imwrite(out_png, tpl)
    meta = {"ref": os.path.basename(ref_png), "strip_w": w, "strip_h": h, "ref_tilt_deg": tilt,
            "tpl_w": tpl.shape[1], "tpl_h": tpl.shape[0],
            "strip_off": [(tpl.shape[1] / 2.0) - (cx - x0), (tpl.shape[0] / 2.0) - (cy - y0)],
            "roi_cols": r["roi_cols"], "roi_rows": r["roi_rows"]}
    json.dump(meta, open(os.path.join(outdir, name + ".json"), "w"), ensure_ascii=False, indent=1)
    if verbose:
        print(f"  模板 {out_png} {tpl.shape[1]}x{tpl.shape[0]} | 条 {w:.0f}x{h:.0f} 倾角 {tilt:+.2f}° "
              f"| 条相对模板中心 ({meta['strip_off'][0]:+.1f},{meta['strip_off'][1]:+.1f})")
    return out_png, meta


if __name__ == "__main__":
    ref = sys.argv[1] if len(sys.argv) > 1 else "/home/ubuntu/aoi_v4/imgs/Finger_Image_W2448_H2048_No_8.png"
    build_template(ref)
