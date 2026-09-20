"""规整度度量 —— 金手指条"质心线"斜率 (比顶边鲁棒得多), 全向量化
每列取金像素的质心行 → 得到一条线; 条水平时该线水平 (斜率≈0), 斜率 = 残余倾角。
"""
import cv2
import numpy as np


def gold_mask(im, lo=(8, 60, 50), hi=(45, 255, 255), k=(5, 5)):
    hsv = cv2.cvtColor(im, cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv, np.array(lo), np.array(hi))
    if k:
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, k))
    return m


def centerline(mask, min_gold=15):
    """返回 (斜率 px/1000px, 残差std px, 有效列数)。向量化实现"""
    mb = (mask > 0)
    cnt = mb.sum(axis=0).astype(np.float32)
    rows = np.arange(mask.shape[0], dtype=np.float32)[:, None]
    rsum = (mb * rows).sum(axis=0)
    cy = np.where(cnt >= min_gold, rsum / np.maximum(cnt, 1), np.nan)
    return _fit_line(cy)


def top_edge(mask, min_gold=1, frac_col=0.3):
    mb = (mask > 0)
    h = mask.shape[0]
    filled = np.where(mb, np.arange(h, dtype=np.float32)[:, None], np.inf)
    tops = filled.min(axis=0)
    tops[~np.isfinite(tops)] = np.nan
    cnt = mb.sum(axis=0)
    tops[cnt < min_gold] = np.nan
    s, res, n = _fit_line(tops)
    if n < mask.shape[1] * frac_col:
        return None, None
    return s, res


def _fit_line(cy, smooth_frac=30):
    w = len(cy)
    v = ~np.isnan(cy)
    n = int(v.sum())
    if n < max(50, w * 0.15):
        return None, None, n
    xs = np.where(v)[0].astype(np.float64)
    ys = cy[v].astype(np.float64)
    k = int(max(11, int(xs.max() - xs.min()) // smooth_frac | 1))
    med = np.convolve(ys, np.ones(k) / k, mode="same")
    A = np.polyfit(xs, med, 1)
    return float(A[0] * 1000.0), float(np.std(med - np.polyval(A, xs))), n


def centerline_slope(mask, min_gold=15):
    return centerline(mask, min_gold)


def top_edge_slope(mask, frac_col=0.3):
    s, res = top_edge(mask, frac_col=frac_col)
    return s, res


def core_band_slope(mask, frac=0.95, pad=3, min_gold=8):
    """只在"实心金带核心行"(行密度≥frac×峰值)上拟合质心线。
    实测(5张真图): 用整块 ROI 算会被上排离散焊盘带偏(-5~+2 px/1000); 只用核心带 → 0.0~0.15"""
    rows = (mask > 0).sum(axis=1)
    if rows.max() <= 0:
        return None, None, 0
    idx = np.where(rows > frac * rows.max())[0]
    if len(idx) < 8:
        return centerline_slope(mask, min_gold=min_gold)
    y0 = max(0, int(idx.min()) - pad)
    y1 = min(mask.shape[0], int(idx.max()) + pad + 1)
    sub = np.zeros_like(mask)
    sub[y0:y1, :] = mask[y0:y1, :]
    return centerline_slope(sub, min_gold=min_gold)
