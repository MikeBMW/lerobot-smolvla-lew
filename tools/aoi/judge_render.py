#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""judge_render.py — 「判据图」渲染 (从 4060 侧 tools/aoi_exposure_fix.py 逐条移植)。

用途: 让**工控机自己**在检测时渲染出与 4060 网页「判据图」同一口径的图, 并存成该轮的记录图
(老倪 2026-09-29: 「在工控机保存的 topview图片…改成判据图的样子」)。

口径 (与 4060 侧 _aoi_frame(canonical) 完全一致, 一步不多一步不少):
  原图(BGR) → clean_judge_frame(过曝带切除 + 只留金手指条 + 列方向裁死白列, 短边拉 K 倍)
            → 按实测倾角反旋(白底填充) → resize 定尺 (900, 332)
  · 灰度加权是 0.299R+0.587G+0.114B ⇒ 进出各转一次颜色 (喂 BGR 会裁错行 —— 4060 侧踩过的坑)
  · 返回 (rgb_or_none, meta): 找不到合格条带时如实 None, 不硬裁一张错的
"""
from __future__ import annotations

import numpy as np

SAT_LEVEL = 250          # 判"饱和像素"的灰度门限
K_DEFAULT = 2.0          # 只把短边拉 k 倍(长边不动) —— 老倪 2026-09-24 口径
JUDGE_HW = (900, 332)    # 判据图定尺 (内容按比例适配, 逐帧不跳动)
DEF = {"sat_thr": 0.40, "edge_pct": 92, "min_h": 20, "merge_gap": 6, "pad": 8, "cliff_win": 15}


def _gray(rgb):
    a = np.asarray(rgb)
    if a.ndim == 3:
        g = (0.299 * a[:, :, 0] + 0.587 * a[:, :, 1] + 0.114 * a[:, :, 2])
    else:
        g = a.astype(np.float32)
    return g.astype(np.float32)


def _runs(mask, merge_gap):
    out, cur = [], None
    for y, m in enumerate(mask):
        if m:
            cur = [y, y] if cur is None else [cur[0], y]
        elif cur is not None:
            out.append(cur)
            cur = None
    if cur is not None:
        out.append(cur)
    merged = []
    for r in out:
        if merged and r[0] - merged[-1][1] <= merge_gap:
            merged[-1][1] = r[1]
        else:
            merged.append([r[0], r[1]])
    return merged


def row_stats(rgb) -> dict:
    import cv2
    g = _gray(rgb)
    gx = np.abs(cv2.Sobel(g, cv2.CV_32F, 1, 0))
    return {"mean": g.mean(axis=1), "sat": (g >= SAT_LEVEL).mean(axis=1),
            "edge": gx.mean(axis=1), "H": g.shape[0], "W": g.shape[1],
            "sat_all": float((g >= SAT_LEVEL).mean()), "mean_all": float(g.mean())}


def col_stats(rgb) -> dict:
    import cv2
    g = _gray(rgb)
    gy = np.abs(cv2.Sobel(g, cv2.CV_32F, 0, 1))
    return {"sat": (g >= SAT_LEVEL).mean(axis=0), "edge": gy.mean(axis=0),
            "H": g.shape[0], "W": g.shape[1]}


def trim_x(rgb, sat_thr: float = 0.60, min_w_frac: float = 0.20, merge_gap: int = 24):
    cs = col_stats(rgb)
    ok = cs["sat"] <= sat_thr
    runs = [r for r in _runs(ok, merge_gap) if (r[1] - r[0] + 1) >= int(cs["W"] * min_w_frac)]
    if not runs:
        return 0, cs["W"], {"trimmed": False, "why": "没有合格列区间 → 保持全宽 (如实记录)",
                            "col_sat_max": round(float(cs["sat"].max()), 3)}
    best = max(runs, key=lambda r: (r[1] - r[0]))
    return best[0], best[1] + 1, {"trimmed": True, "x_span": [best[0], best[1] + 1],
                                  "dropped_cols": [0, best[0]] if best[0] else [],
                                  "col_sat_before_max": round(float(cs["sat"].max()), 3)}


def find_cliff(prof: dict) -> dict:
    d = np.diff(prof["mean"])
    w = DEF["cliff_win"]
    if len(d) <= w:
        return {"y": -1, "jump": 0.0}
    k = int(np.argmax(np.convolve(d, np.ones(w), "valid")))
    return {"y": k, "jump": float(d[k:k + w].mean())}


def stretch_short(rgb, k: float = K_DEFAULT):
    import cv2
    a = np.asarray(rgb)
    h, w = a.shape[:2]
    if k is None or abs(float(k) - 1.0) < 1e-6:
        return a, {"k": 1.0, "axis": "none", "out_hw": [h, w], "in_hw": [h, w], "stretch_desc": "无拉长 (×1.0)"}
    if h <= w:
        out = (w, max(1, int(round(h * float(k)))))
        axis = "h"
    else:
        out = (max(1, int(round(w * float(k)))), h)
        axis = "w"
    img = cv2.resize(a, out, interpolation=cv2.INTER_CUBIC)
    _short_in, _short_out = (h, out[1]) if axis == "h" else (w, out[0])
    return img, {"k": round(float(k), 2), "axis": axis, "out_hw": [out[1], out[0]], "in_hw": [h, w],
                 "stretch_desc": f"短边{'高' if axis == 'h' else '宽'} {_short_in}→{_short_out} (×{float(k):.1f}) · 长边不动"}


def analyze(rgb) -> dict:
    prof = row_stats(rgb)
    cliff = find_cliff(prof)
    thr = float(np.percentile(prof["edge"], DEF["edge_pct"]))
    bands = [r for r in _runs(prof["edge"] >= thr, DEF["merge_gap"]) if r[1] - r[0] + 1 >= DEF["min_h"]]
    sat_bands = [r for r in _runs(prof["sat"] > DEF["sat_thr"], DEF["merge_gap"]) if r[1] - r[0] + 1 >= 8]
    cands = []
    for a, b in bands:
        s = float(prof["sat"][a:b + 1].mean())
        e = float(prof["edge"][a:b + 1].mean())
        cands.append({"y0": a, "y1": b, "h": b - a + 1, "sat": round(s, 3), "edge": round(e, 2),
                      "ok": s <= DEF["sat_thr"]})
    return {"H": prof["H"], "W": prof["W"], "sat_all": round(prof["sat_all"], 4),
            "mean_all": round(prof["mean_all"], 1), "cliff": cliff,
            "sat_bands": sat_bands, "gold_candidates": cands,
            "verdict": ("overexposed" if prof["sat_all"] > 0.10 else "ok")}


def clean_judge_frame(rgb, out=None, sat_thr=None, pad=None, return_natural=False, k: float = K_DEFAULT):
    """原始图 → 无过曝判据图: 切死白带, 只留金手指条, 短边拉 k 倍(或 out×out)。返回 (clean_rgb, meta)。"""
    import cv2
    sat_thr = DEF["sat_thr"] if sat_thr is None else sat_thr
    pad = DEF["pad"] if pad is None else pad
    prof = row_stats(rgb)
    a = analyze(rgb)
    ok = [c for c in a["gold_candidates"] if c["sat"] <= sat_thr]
    if not ok:
        return None, {"ok": False, "err": "没有找到未过曝的金手指条带 (全图都可能过曝)",
                      "sat_all": a["sat_all"], "analyze": a}
    best = max(ok, key=lambda c: c["edge"])
    y0 = max(0, best["y0"] - pad)
    y1 = min(prof["H"], best["y1"] + 1 + pad)
    band = np.asarray(rgb)[y0:y1]
    x0, x1, xmeta = trim_x(band)
    band = band[:, x0:x1]
    sat_dropped = int((prof["sat"] > sat_thr).sum())
    if out:
        clean = cv2.resize(band, (int(out), int(out)), interpolation=cv2.INTER_CUBIC)
        kmeta = {"k": None, "axis": "square", "out_hw": [int(out), int(out)]}
    else:
        clean, kmeta = stretch_short(band, k)
    meta = {"ok": True, "kept_rows": [y0, y1], "kept_h": y1 - y0, "src_h": prof["H"], "src_w": prof["W"],
            "dropped_sat_rows": sat_dropped, "dropped_pct": round(sat_dropped / prof["H"] * 100, 1),
            "sat_before": round(a["sat_all"], 4), "sat_after": round(float((_gray(clean) >= SAT_LEVEL).mean()), 4),
            "cliff": a["cliff"], "candidate": best, "out": list(clean.shape[:2])[::-1], **kmeta,
            "x_trim": xmeta, "col_sat_after_max": round(float((_gray(clean) >= SAT_LEVEL).mean(axis=0).max()), 3),
            "rule": f"sat≤{sat_thr} 且 边缘密集(P{DEF['edge_pct']}) 且 高≥{DEF['min_h']}行, 上下留 {pad} 行"}
    if return_natural:
        meta["natural"] = band
    return clean, meta


def render_judge(bgr, deskew_deg: float = 0.0, hw=JUDGE_HW, k: float = K_DEFAULT):
    """工控机原图(BGR) → 判据图(BGR, 定尺 hw)。与 4060 网页判据图同一口径。

    返回 (judge_bgr | None, meta): meta 里如实记录 裁掉多少过曝行/保留行区间/列裁/倾角/定尺/饱和比。
    """
    import cv2
    clean_rgb, meta = clean_judge_frame(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), return_natural=True, k=k)
    if clean_rgb is None:
        return None, meta
    band = meta.get("natural") if meta.get("natural") is not None else clean_rgb
    img = cv2.cvtColor(np.asarray(band), cv2.COLOR_RGB2BGR)
    meta = dict(meta or {})
    if abs(float(deskew_deg)) > 0.05:
        h0, w0 = img.shape[:2]
        M = cv2.getRotationMatrix2D((w0 / 2.0, h0 / 2.0), -float(deskew_deg), 1.0)
        img = cv2.warpAffine(img, M, (w0, h0), flags=cv2.INTER_LINEAR,
                             borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))
        meta["deskew_deg"] = round(float(deskew_deg), 3)
    if hw:
        img = cv2.resize(img, (int(hw[0]), int(hw[1])), interpolation=cv2.INTER_LINEAR)
        meta["fix_hw"] = [int(hw[0]), int(hw[1])]
    meta["out"] = [int(img.shape[1]), int(img.shape[0])]
    meta["sat_after"] = round(float((_gray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)) >= SAT_LEVEL).mean()), 4)
    meta["judge"] = True
    return img, meta


if __name__ == "__main__":                                  # 命令行自检: render_judge <origin.png> [angle] [out.jpg]
    import sys
    import cv2
    src = sys.argv[1]
    ang = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
    dst = sys.argv[3] if len(sys.argv) > 3 else "/tmp/judge_render_out.jpg"
    bgr = cv2.imread(src)
    img, meta = render_judge(bgr, deskew_deg=ang)
    if img is None:
        print("FAIL:", meta)
        raise SystemExit(2)
    cv2.imwrite(dst, img, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    g = _gray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    print("OK ->", dst, "size=", img.shape[1], "x", img.shape[0],
          "mean=%.1f sat>=250=%.1f%%" % (g.mean(), (g >= SAT_LEVEL).mean() * 100))
    print("meta:", {k: meta[k] for k in ("kept_rows", "kept_h", "dropped_sat_rows", "dropped_pct",
                                         "sat_before", "sat_after", "x_trim", "k", "fix_hw") if k in meta})
