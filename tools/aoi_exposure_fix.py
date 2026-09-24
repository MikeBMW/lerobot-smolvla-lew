#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aoi_exposure_fix.py — 原始图过曝切除 + 自裁判据图 (2026-09-24 老倪现场发现)

老倪: 「灰度信息丢失(过曝): 图像底部亮度到上限(255 纯白), 明暗细节/纹理/衬度完全消失, 一片死白;
       渐变过渡异常: 向下过渡时亮度没有自然线性衰减, 底部出现急剧亮度抬升 (Cliff edge);
       这是拉伸后的图像; 你要将原始图像过曝光的部分, 去掉」

实测 (真拍 10082 金手指, 2026-09-24):
  · 工控机给的拉伸图 (?kind=topview 960x960): y≥255 起 mean 恒在 238.5±0.5, 饱和像素(≥250)占比 **88%**,
    过曝行 705/960 = **73%** → 一片死白, 细节为零 ⇒ **不能直接喂任务头**
  · 原始图 (?kind=origin 2448x2048): 过曝带 y 592~1184 (sat>30%, 453 行), 最陡跳变 y=589 (12.1/行)
    金手指条 (边缘密集) 实测 y 948~1147 (200 行, sat 34~38% = 金面镜反光, 可接受)
  ⇒ 处置: **不用工控机的固定窗拉伸图, 改用原始图自裁**: 先切掉过曝带, 只保留金手指条 → 判据图。
     口径 (sat≤40%, 边缘密集, 高≥20 行) 与训练数据保持一致。

用法:
  from aoi_exposure_fix import clean_judge_frame, analyze
  clean, meta = clean_judge_frame(origin_rgb, out=960)   # 判据图 (无死白)
  st = analyze(origin_rgb)                               # 只诊断不移臂/不改图
"""
from __future__ import annotations

import numpy as np

SAT_LEVEL = 250          # 判"饱和像素"的灰度门限 (255 上限下的实际死白线)
DEF = {
    "sat_thr": 0.40,     # 保留带允许的饱和像素占比上限 (金面镜反光 ~0.35 可过, 死白带 0.6+ 必须切)
    "edge_pct": 92,      # 边缘密集判定分位 (行 |gx| 均值)
    "min_h": 20,         # 条带最小高度 (行)
    "merge_gap": 6,      # 空隙 ≤ 该行数则合并成一条
    "pad": 8,            # 条带上下各留几行余量
    "cliff_win": 15,     # 检测 cliff 的滑窗 (行)
}


def _gray(rgb):
    a = np.asarray(rgb)
    if a.ndim == 3:
        g = (0.299 * a[:, :, 0] + 0.587 * a[:, :, 1] + 0.114 * a[:, :, 2])
    else:
        g = a.astype(np.float32)
    return g.astype(np.float32)


def row_stats(rgb) -> dict:
    """逐行: 灰度均值 / 饱和占比 / 边缘密度(|gx| 均值)。"""
    import cv2
    g = _gray(rgb)
    gx = np.abs(cv2.Sobel(g, cv2.CV_32F, 1, 0))
    return {"mean": g.mean(axis=1), "sat": (g >= SAT_LEVEL).mean(axis=1),
            "edge": gx.mean(axis=1), "H": g.shape[0], "W": g.shape[1],
            "sat_all": float((g >= SAT_LEVEL).mean()), "mean_all": float(g.mean())}


def col_stats(rgb) -> dict:
    """逐列: 饱和占比 / 边缘密度 — 用于把条带左右端裁到"自己的 x 范围"。

    ⚠️ 实测坑 (2026-09-24): 只做行裁切时, 原始图右侧那片亮区会被带进画面 →
    裁后图**最右 10 列饱和占比 100%** (看着还是死白)。必须同时裁 x。
    """
    import cv2
    g = _gray(rgb)
    gy = np.abs(cv2.Sobel(g, cv2.CV_32F, 0, 1))
    return {"sat": (g >= SAT_LEVEL).mean(axis=0), "edge": gy.mean(axis=0),
            "H": g.shape[0], "W": g.shape[1]}


def trim_x(rgb, sat_thr: float = 0.60, min_w_frac: float = 0.20, merge_gap: int = 24):
    """把画面按列裁到"非过曝"的 x 范围 (左右那两片死白切掉)。返回 (x0, x1, meta)。"""
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
    """找"急剧亮度抬升"(Cliff edge): 滑窗内最大正跳变。"""
    d = np.diff(prof["mean"])
    w = DEF["cliff_win"]
    if len(d) <= w:
        return {"y": -1, "jump": 0.0}
    k = int(np.argmax(np.convolve(d, np.ones(w), "valid")))
    return {"y": k, "jump": float(d[k:k + w].mean())}


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


def analyze(rgb) -> dict:
    """只诊断: 过曝带 / cliff / 金手指条候选 / 打分 (不动图)。"""
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


def clean_judge_frame(rgb, out: int = 960, sat_thr: float | None = None, pad: int | None = None,
                      return_natural: bool = False):
    """原始图 → **无过曝判据图**: 切掉死白带, 只保留金手指条, 归一化到 out×out (可另返原比例版)。

    返回 (clean_rgb, meta)。meta 如实记录: 切掉了多少过曝行、切前/切后饱和占比、保留行区间、cliff。
    找不到合格条带时**如实返回 None** (不硬裁一张错的)。
    """
    import cv2
    sat_thr = DEF["sat_thr"] if sat_thr is None else sat_thr
    pad = DEF["pad"] if pad is None else pad
    prof = row_stats(rgb)
    a = analyze(rgb)
    ok = [c for c in a["gold_candidates"] if c["sat"] <= sat_thr]
    if not ok:
        return None, {"ok": False, "err": "没有找到未过曝的金手指条带 (全图都可能过曝)",
                      "sat_all": a["sat_all"], "analyze": a}
    # 取"边缘最密"的合格条带 (金手指焊盘行)
    best = max(ok, key=lambda c: c["edge"])
    y0 = max(0, best["y0"] - pad)
    y1 = min(prof["H"], best["y1"] + 1 + pad)
    band = np.asarray(rgb)[y0:y1]
    # ② 列方向也裁: 切掉左右死白片 (只做行裁切会留 100% 饱和的边列, 实测坑)
    x0, x1, xmeta = trim_x(band)
    band = band[:, x0:x1]
    sat_dropped = int((prof["sat"] > sat_thr).sum())
    clean = cv2.resize(band, (out, out), interpolation=cv2.INTER_CUBIC)
    meta = {"ok": True, "kept_rows": [y0, y1], "kept_h": y1 - y0, "src_h": prof["H"], "src_w": prof["W"],
            "dropped_sat_rows": sat_dropped, "dropped_pct": round(sat_dropped / prof["H"] * 100, 1),
            "sat_before": round(a["sat_all"], 4), "sat_after": round(float((_gray(clean) >= SAT_LEVEL).mean()), 4),
            "cliff": a["cliff"], "candidate": best, "out": [out, out],
            "x_trim": xmeta,
            "col_sat_after_max": round(float((_gray(clean) >= SAT_LEVEL).mean(axis=0).max()), 3),
            "rule": f"sat≤{sat_thr} 且 边缘密集(P{DEF['edge_pct']}) 且 高≥{DEF['min_h']}行, 上下留 {pad} 行"}
    if return_natural:
        meta["natural"] = band
    return clean, meta


if __name__ == "__main__":
    import sys
    import cv2
    p = sys.argv[1] if len(sys.argv) > 1 else ""
    if not p:
        print(__doc__); raise SystemExit(0)
    bgr = cv2.imread(p)
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    a = analyze(rgb)
    print("诊断:", {k: v for k, v in a.items() if k != "gold_candidates"})
    for c in a["gold_candidates"]:
        print("  条带候选:", c)
    clean, meta = clean_judge_frame(rgb, out=960)
    print("裁切:", {k: v for k, v in meta.items() if k not in ("natural", "candidate")})
    if clean is not None:
        o = p.replace(".png", "_clean960.png")
        cv2.imwrite(o, cv2.cvtColor(clean, cv2.COLOR_RGB2BGR))
        print("→", o)
