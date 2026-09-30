#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aoi_geom_parity.py — 几何口径对照: 线上方图(工控机 960x960 规整拉长) vs 我们(原图裁切 短边x2 + 过曝切除)

用途: 老倪 09-24 口径「训练口径必须与推理口径一致, 先统一再训」的取证件。
对同一支光模块的同一时刻两张图做同指标对照 (只读, 不判定"谁漂亮", 只看数字):
  尺寸 / 饱和度>250 占比 (死白) / 死白行 / 拉普拉斯清晰度 / 金手指 ROI 有效像素(短边像素数)
输出 JSON 到 reports/aoi_geom_parity_<ts>.json 并打印表格。
用法: ./gui-venv311/bin/python tools/aoi_geom_parity.py [--pair DIR]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import time

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def metrics(bgr: np.ndarray) -> dict:
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    sat = float((g >= 250).mean() * 100.0)
    dead_rows = int(((g >= 250).mean(axis=1) > 0.9).sum())
    lap = float(cv2.Laplacian(g.astype(np.float32), cv2.CV_32F).var())
    return {"shape": [int(bgr.shape[0]), int(bgr.shape[1])],
            "sat_pct": round(sat, 2), "dead_rows": dead_rows,
            "lap_var": round(lap, 1),
            "mean": round(float(g.mean()), 1), "std": round(float(g.std()), 1)}


def short_side_stretch(bgr: np.ndarray, k: float = 2.0, cut_over: bool = True) -> np.ndarray:
    """我们口径: 短边×k, 长边不动; 可选过曝切除 (裁掉饱和行/列)。"""
    h, w = bgr.shape[:2]
    if h <= w:
        out = cv2.resize(bgr, (int(round(w)), int(round(h * k))), interpolation=cv2.INTER_CUBIC)
    else:
        out = cv2.resize(bgr, (int(round(w * k)), int(round(h))), interpolation=cv2.INTER_CUBIC)
    if cut_over:
        g = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
        rows = g.mean(axis=1) > 250 * 0.9
        cols = g.mean(axis=0) > 250 * 0.9
        if rows.any() or cols.any():
            y0, y1 = int(np.argmax(~rows)) if (~rows).any() else 0, len(rows) - int(np.argmax(~rows[::-1])) if (~rows).any() else len(rows)
            x0, x1 = int(np.argmax(~cols)) if (~cols).any() else 0, len(cols) - int(np.argmax(~cols[::-1])) if (~cols).any() else len(cols)
            if y1 - y0 > 16 and x1 - x0 > 16:
                out = out[y0:y1, x0:x1]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair", default=os.path.join(ROOT, "reports", "opt_view"),
                    help="含 *_origin.png 与 *_topview.png 的目录")
    ap.add_argument("--k", type=float, default=2.0)
    a = ap.parse_args()

    recs = []
    for op in sorted(glob.glob(os.path.join(a.pair, "*_origin*.png"))):
        name = os.path.basename(op).replace("_origin", "").replace(".png", "")
        tp = ""
        for c in (op.replace("_origin", "_topview"), os.path.join(a.pair, f"{name}_topview.png")):
            if os.path.isfile(c):
                tp = c
                break
        orig = cv2.imread(op)
        if orig is None:
            continue
        ours = short_side_stretch(orig, k=a.k)
        rows = [{"tag": "线上方图(工控机 960x960 拉长)", "file": os.path.basename(tp) if tp else "(缺)",
                 "m": metrics(cv2.imread(tp)) if tp and cv2.imread(tp) is not None else None},
                {"tag": f"我们(原图裁切 短边x{a.k:g}+过曝切除)", "file": os.path.basename(op), "m": metrics(ours)},
                {"tag": "原图(基准)", "file": os.path.basename(op), "m": metrics(orig)}]
        recs.append({"stem": name, "rows": rows})

    if not recs:
        print("❌ 没找到 *_origin*.png 对照图")
        return 2

    for r in recs:
        print(f"\n■ {r['stem']}")
        print(f"  {'口径':38s} {'尺寸':>12s} {'死白%':>7s} {'死白行':>7s} {'清晰度':>9s} {'mean':>6s} {'std':>6s}")
        for row in r["rows"]:
            m = row["m"]
            if not m:
                print(f"  {row['tag']:38s} {'—':>12s}")
                continue
            print(f"  {row['tag']:38s} {str(m['shape'][1])+'x'+str(m['shape'][0]):>12s} "
                  f"{m['sat_pct']:>7.2f} {m['dead_rows']:>7d} {m['lap_var']:>9.1f} {m['mean']:>6.1f} {m['std']:>6.1f}")

    out = os.path.join(ROOT, "reports", f"aoi_geom_parity_{time.strftime('%Y%m%d_%H%M%S')}.json")
    json.dump({"ts": time.strftime("%F %T"), "pair_dir": a.pair, "k": a.k, "records": recs},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n→ {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
