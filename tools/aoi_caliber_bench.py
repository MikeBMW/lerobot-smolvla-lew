#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aoi_caliber_bench.py — AOI 判据图口径基准: 同一张真图上比三种口径 (老倪: 手选框>原图自裁>拉长图)

目的 (会话十二发现的真问题): 工控机 /crop_info.score 实测仅 **0.325** (v3 固定窗).
  技能记载验收口径: **v4 模板法 ≥0.95** / v3 固定窗 ≈0.29 ⇒ 工厂口径不合格 ⇒ 它的 OK/NG 判决不可信.
  本工具在 4060 侧对**同一批真图**跑我们的两种口径, 用数字决定该用哪个:
    ① 工厂口径   : GET /picture?kind=crop (960×960) + /crop_info.score
    ② 本机 v4 模板: /home/ubuntu/aoi_v4/gf_crop.GoldFingerCropper → 960×960 (与模型 imgsz=960 对齐)
    ③ 本机 自裁   : tools/aoi_exposure_fix.clean_judge_frame → 无过曝带 (可另存原比例版)
指标: 尺寸 · 均值/std · 饱和(≥250)占比 · 死白行 · Tenengrad(细节能量) · score/残余倾角/金覆盖
产物: 每帧三口径图 + 判决 JSON 落到 data/yolo_aoi_annot/caliber_bench/ + 汇总 reports/aoi_caliber_bench_*.json
用法: ./gui-venv311/bin/python tools/aoi_caliber_bench.py --frames 12
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request

import numpy as np
import cv2

R = "/home/ubuntu/zmax_rel"
sys.path.insert(0, os.path.join(R, "tools"))
sys.path.insert(0, "/home/ubuntu/aoi_v4")
CAM = "http://192.168.23.23:10082"
TPL = "/home/ubuntu/aoi_v4/templates/gf_strip_template.png"
OUT = os.path.join(R, "data/yolo_aoi_annot/caliber_bench")


def post(path, obj, timeout=90):
    req = urllib.request.Request(CAM + path, data=json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def get_img(path, timeout=40):
    with urllib.request.urlopen(CAM + path, timeout=timeout) as r:
        return cv2.imdecode(np.frombuffer(r.read(), np.uint8), cv2.IMREAD_COLOR)


def get_json(path, timeout=20):
    try:
        with urllib.request.urlopen(CAM + path, timeout=timeout) as r:
            return json.loads(r.read().decode() or "{}")
    except Exception as e:                                                      # noqa: BLE001
        return {"err": type(e).__name__, "code": getattr(e, "code", None)}


def stats(g, tag):
    if g is None:
        return {"口径": tag, "状态": "取不到"}
    if g.ndim == 3:
        g = cv2.cvtColor(g, cv2.COLOR_BGR2GRAY)
    gf = g.astype(np.float32)
    gx = np.abs(np.diff(gf, axis=1))[:-1, :]      # (H-1, W-1) —— 两轴梯度对齐同一网格
    gy = np.abs(np.diff(gf, axis=0))[:, :-1]      # (H-1, W-1)
    ten = float((gx ** 2 + gy ** 2).mean())
    return {"口径": tag, "尺寸": "%dx%d" % (g.shape[1], g.shape[0]),
            "均值": round(float(g.mean()), 1), "std": round(float(g.std()), 1),
            "饱和%": round(float((g >= 250).mean() * 100), 1),
            "死白行": int((g >= 250).all(axis=1).sum()),
            "Tenengrad": round(ten, 0)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=12)
    ap.add_argument("--nocap", action="store_true", help="不真拍, 复用最近一次")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    sys.path.insert(0, os.path.join(R, "tools"))
    import aoi_exposure_fix as FX
    from gf_crop import GoldFingerCropper
    crop = GoldFingerCropper(TPL, canonical_w=960, canonical_h=960)

    rows = []
    print("═" * 96)
    print("🎯 AOI 判据图口径基准 · %d 帧 · 三口径对照 (工厂 v3 / 本机 v4 模板 / 本机自裁)" % a.frames)
    print("═" * 96)
    for i in range(a.frames):
        rec = {"i": i, "ts": time.strftime("%F %T")}
        try:
            if not a.nocap:
                post("/capture_detect", {})
                time.sleep(4)
            origin = get_img("/picture?kind=origin")
            if origin is None:
                print("  帧%d ❌ origin 取不到" % (i + 1))
                continue
            fi = get_json("/crop_info")
            lr = get_json("/last_result")
            rec["verdict"] = {"count": lr.get("count"), "type": lr.get("detect_type"), "ms": lr.get("ms")}
            rec["factory_score"] = fi.get("score")
            ts = time.strftime("%Y%m%d_%H%M%S")
            jo = os.path.join(OUT, "origin_%s_%d.png" % (ts, i))
            cv2.imwrite(jo, origin)
            # ① 工厂口径图
            fac = get_img("/picture?kind=crop")
            r_fac = stats(fac, "① 工厂 v3 (?kind=crop)")
            # ② 本机 v4 模板法
            try:
                res = crop.crop(origin)
                if isinstance(res, tuple):
                    img_v4, meta_v4 = res[0], (res[1] if len(res) > 1 and isinstance(res[1], (dict, list)) else {})
                else:
                    img_v4, meta_v4 = res, {}
                r_v4 = stats(img_v4, "② 本机 v4 模板")
                r_v4["score"] = (meta_v4 or {}).get("score") if isinstance(meta_v4, dict) else None
                r_v4["残余倾角"] = (meta_v4 or {}).get("slope") if isinstance(meta_v4, dict) else None
                r_v4["金覆盖"] = (meta_v4 or {}).get("gold_cover") if isinstance(meta_v4, dict) else None
                rec["v4_meta"] = meta_v4 if isinstance(meta_v4, dict) else str(meta_v4)[:200]
                if img_v4 is not None:
                    cv2.imwrite(os.path.join(OUT, "v4_%s_%d.png" % (ts, i)), img_v4)
            except Exception as e:                                              # noqa: BLE001
                r_v4 = {"口径": "② 本机 v4 模板", "状态": "%s: %s" % (type(e).__name__, str(e)[:70])}
            # ③ 本机自裁
            try:
                got = FX.clean_judge_frame(origin, out=960, return_natural=True)
                if isinstance(got, tuple):
                    clean, meta_c = got[0], (got[1] if len(got) > 1 else {})
                else:
                    clean, meta_c = got, {}
                cimg = clean[0] if isinstance(clean, tuple) else clean
                r_cut = stats(np.asarray(cimg), "③ 本机自裁")
                rec["cut_meta"] = meta_c if isinstance(meta_c, dict) else str(meta_c)[:200]
                if cimg is not None:
                    cv2.imwrite(os.path.join(OUT, "cut_%s_%d.png" % (ts, i)), np.asarray(cimg))
            except Exception as e:                                              # noqa: BLE001
                r_cut = {"口径": "③ 本机自裁", "状态": "%s: %s" % (type(e).__name__, str(e)[:70])}
            rec.update({"factory": r_fac, "v4": r_v4, "cut": r_cut})
            rows.append(rec)
            json.dump(rec, open(os.path.join(OUT, "frame_%s_%d.json" % (ts, i)), "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
            def g(r, k, d="—"):
                return r.get(k, d) if "状态" not in r else "取不到"
            print("  帧%d 工厂score=%s | 工厂饱和%s%% 细节%s | v4 score=%s 饱和%s%% 细节%s | 自裁饱和%s%% 细节%s | 判决count=%s" %
                  (i + 1, rec.get("factory_score"), g(r_fac, "饱和%"), g(r_fac, "Tenengrad"),
                   g(r_v4, "score"), g(r_v4, "饱和%"), g(r_v4, "Tenengrad"),
                   g(r_cut, "饱和%"), g(r_cut, "Tenengrad"), rec["verdict"]["count"]))
        except Exception as e:                                                  # noqa: BLE001
            print("  帧%d ❌ %s: %s" % (i + 1, type(e).__name__, str(e)[:90]))

    def agg(key, field):
        vs = [r[key].get(field) for r in rows if key in r and isinstance(r[key].get(field), (int, float))]
        return (round(float(np.mean(vs)), 3), len(vs)) if vs else (None, 0)

    print("\n" + "─" * 96)
    print("汇总 (%d 帧):" % len(rows))
    for key, name in (("factory", "① 工厂 v3"), ("v4", "② 本机 v4 模板"), ("cut", "③ 本机自裁")):
        sat, n1 = agg(key, "饱和%")
        ten, n2 = agg(key, "Tenengrad")
        sc, n3 = agg(key, "score")
        print("  %-16s 饱和 %s%% · 细节能量 %s · score %s  (样本 %d)" % (name, sat, ten, sc, max(n1, n2, n3)))
    fsc = [r.get("factory_score") for r in rows if isinstance(r.get("factory_score"), (int, float))]
    vsc = [r["v4"].get("score") for r in rows if "v4" in r and isinstance(r["v4"].get("score"), (int, float))]
    if fsc and vsc:
        print("\n  ★ 判据: 工厂口径 score 均值 %.3f (验收 ≥0.95) vs 本机 v4 %.3f ⇒ %s" %
              (float(np.mean(fsc)), float(np.mean(vsc)),
               "本机口径达标, 工厂口径不合格 → 现场应切 v4" if float(np.mean(vsc)) >= 0.95 > float(np.mean(fsc))
               else "需现场复测"))
    dst = os.path.join(R, "reports", "aoi_caliber_bench_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    json.dump({"ts": time.strftime("%F %T"), "frames": len(rows), "rows": rows},
              open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n取证: %s\n产物: %s" % (dst, OUT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
