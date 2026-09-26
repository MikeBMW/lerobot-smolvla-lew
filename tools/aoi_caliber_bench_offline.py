#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aoi_caliber_bench_offline.py — 对**已落盘**的 origin 真图跑三口径对照 (不真拍, 不打扰产线)

用途: aoi_caliber_bench.py 采到的 origin_*.png 逐帧重跑口径对比 (修了 Tenengrad 公式之后复用, 无需再拍)
产物: reports/aoi_caliber_bench_offline_*.json + 每帧三口径图 (caliber_bench/off_*)
"""
from __future__ import annotations

import glob
import json
import os
import sys
import time

import numpy as np
import cv2

R = "/home/ubuntu/zmax_rel"
sys.path.insert(0, os.path.join(R, "tools"))
sys.path.insert(0, "/home/ubuntu/aoi_v4")
BENCH = os.path.join(R, "data/yolo_aoi_annot/caliber_bench")
TPL = "/home/ubuntu/aoi_v4/templates/gf_strip_template.png"


def stats(g, tag):
    if g is None:
        return {"口径": tag, "状态": "取不到"}
    if g.ndim == 3:
        g = cv2.cvtColor(g, cv2.COLOR_BGR2GRAY)
    gf = g.astype(np.float32)
    gx = np.abs(np.diff(gf, axis=1))[:-1, :]
    gy = np.abs(np.diff(gf, axis=0))[:, :-1]
    return {"口径": tag, "尺寸": "%dx%d" % (g.shape[1], g.shape[0]),
            "均值": round(float(g.mean()), 1), "std": round(float(g.std()), 1),
            "饱和%": round(float((g >= 250).mean() * 100), 1),
            "死白行": int((g >= 250).all(axis=1).sum()),
            "Tenengrad": round(float((gx ** 2 + gy ** 2).mean()), 0)}


def main() -> int:
    import aoi_exposure_fix as FX
    from gf_crop import GoldFingerCropper
    crop = GoldFingerCropper(TPL, canonical_w=960, canonical_h=960)
    files = sorted(glob.glob(os.path.join(BENCH, "origin_*.png")))
    print("═" * 104)
    print("🎯 AOI 判据图口径基准 (离线复算 · %d 张已落盘 origin 真图 · 不再真拍)" % len(files))
    print("═" * 104)
    rows = []
    for f in files:
        origin = cv2.imread(f)
        if origin is None:
            continue
        joint = os.path.splitext(f)[0] + ".json"
        fac = None
        if os.path.isfile(joint):
            j = json.load(open(joint, encoding="utf-8"))
            fac = j.get("factory") or None
        rec = {"file": os.path.basename(f)}
        r_fac = (fac if fac else {"口径": "① 工厂 v3 (?kind=crop)", "状态": "无落档"})
        try:
            res = crop.crop(origin)
            img_v4, meta = (res[0], res[1] if len(res) > 1 and isinstance(res[1], dict) else {}) \
                if isinstance(res, tuple) else (res, {})
            r_v4 = stats(img_v4, "② 本机 v4 模板")
            r_v4["score"] = meta.get("score")
            r_v4["残余倾角"] = meta.get("slope")
            r_v4["金覆盖"] = meta.get("gold_cover")
            if img_v4 is not None:
                cv2.imwrite(os.path.join(BENCH, "off_v4_" + os.path.basename(f)), img_v4)
            rec["v4_meta"] = {k: meta.get(k) for k in ("score", "slope", "gold_cover", "scale", "angle")}
        except Exception as e:                                                  # noqa: BLE001
            r_v4 = {"口径": "② 本机 v4 模板", "状态": "%s: %s" % (type(e).__name__, str(e)[:70])}
        try:
            got = FX.clean_judge_frame(origin, out=960, return_natural=True)
            clean, meta_c = (got[0], got[1] if len(got) > 1 else {}) if isinstance(got, tuple) else (got, {})
            cimg = clean[0] if isinstance(clean, tuple) else clean
            r_cut = stats(np.asarray(cimg) if cimg is not None else None, "③ 本机自裁")
            rec["cut_meta"] = {k: meta_c.get(k) for k in list(meta_c or {})[:6]} if isinstance(meta_c, dict) else str(meta_c)[:150]
            if cimg is not None:
                cv2.imwrite(os.path.join(BENCH, "off_cut_" + os.path.basename(f)), np.asarray(cimg))
        except Exception as e:                                                  # noqa: BLE001
            r_cut = {"口径": "③ 本机自裁", "状态": "%s: %s" % (type(e).__name__, str(e)[:70])}
        rec.update({"factory": r_fac, "v4": r_v4, "cut": r_cut})
        rows.append(rec)
        g = (lambda r, k: r.get(k, "—") if "状态" not in r else "N/A")
        print("  %-28s 工厂: score=%s 饱和%s%% 细节%s | v4: score=%s 饱和%s%% 细节%s 倾角%s | 自裁: 饱和%s%% 细节%s" %
              (rec["file"][:28], rec["factory"].get("score"), g(r_fac, "饱和%"), g(r_fac, "Tenengrad"),
               g(r_v4, "score"), g(r_v4, "饱和%"), g(r_v4, "Tenengrad"), g(r_v4, "残余倾角"),
               g(r_cut, "饱和%"), g(r_cut, "Tenengrad")))

    def agg(key, field):
        vs = [r[key].get(field) for r in rows if isinstance(r[key].get(field), (int, float))]
        return (round(float(np.mean(vs)), 3), len(vs)) if vs else (None, 0)

    print("\n" + "─" * 104)
    print("汇总 (%d 帧):" % len(rows))
    for key, name in (("factory", "① 工厂 v3 (label=crop 口径)"), ("v4", "② 本机 v4 模板法"), ("cut", "③ 本机自裁(无过曝带)")):
        print("  %-26s 饱和 %5s%% · 细节能量 %8s · score %6s" % (name, agg(key, "饱和%")[0], agg(key, "Tenengrad")[0], agg(key, "score")[0]))
    fsc, n1 = agg("factory", "score")
    vsc, n2 = agg("v4", "score")
    fsat, _ = agg("factory", "饱和%")
    vsat, _ = agg("v4", "饱和%")
    csat, _ = agg("cut", "饱和%")
    print("\n★ 判据 (验收口径 v4 ≥0.95, 工厂 v3 ≈0.29~0.44):")
    print("   工厂口径 score 均值 = %s · 本机 v4 均值 = %s" % (fsc, vsc))
    print("   饱和占比: 工厂 %s%% → 本机 v4 %s%% / 自裁 %s%%" % (fsat, vsat, csat))
    if isinstance(vsc, float):
        print("   → %s" % ("本机 v4 口径达标 (≥0.95), 工厂口径不合格 ⇒ 现场应切 v4 模板法"
                           if vsc >= 0.95 and (fsc is None or fsc < 0.95) else "本机 v4 未达 0.95, 需查模板/现场复测"))
    dst = os.path.join(R, "reports", "aoi_caliber_bench_offline_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    json.dump({"ts": time.strftime("%F %T"), "frames": len(rows), "rows": rows},
              open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n取证: %s" % dst)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
