#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aoi_caliber_offline_check.py — 离线自证: 10082 判据口径两模式 + 检测结果叠加(anno) 在本机就能验

为什么要有它: 工控机程序改动不能靠"推上去再看"。本工具把
`~/aoi_v4/cam_finger_10082_work_v6.py` **用桩模块 exec 进来**(不装 flask / 无相机 / 无权重),
在真原图上跑三种产物的**真实代码路径**, 给出: 尺寸/饱和/细节能量/空白占比/像素差。

覆盖:
  ① caliber=canonical → crop_goldfinger_regular() 必须仍是 960x960 (不回归)
  ② caliber=same      → 同一口径图 900x332 (原比例+去倾斜+定尺), 并给 原比例条带尺寸/去倾角/空白裁除
  ③ draw_detections() → 检测框真的画上去了吗 (用注入的假框做像素级差分, 与判据图逐点比)
  ④ 与 4060 侧页面渲染(clean_judge_frame+去倾角+900x332) 的口径差 (只报数, 不作等价声明)

用法:
  ./gui-venv311/bin/python tools/aoi_caliber_offline_check.py                 # 用本机历史真图
  ./gui-venv311/bin/python tools/aoi_caliber_offline_check.py --live 3        # 从 10082 取 3 张真原图
产物: data/yolo_aoi_annot/caliber_offline/ 里的 png + 一份 JSON 汇总
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import time
import types
import urllib.request

import cv2
import numpy as np

R = "/home/ubuntu/zmax_rel"
AOI = "/home/ubuntu/aoi_v4"
SRC = os.path.join(AOI, "cam_finger_10082_work_v6.py")
OUT = os.path.join(R, "data/yolo_aoi_annot/caliber_offline")
CAM = "http://192.168.23.23:10082"


# ───────────────────────── 桩模块 (让工控机程序能在本机 exec) ─────────────────────────
class _Any:
    def __call__(self, *a, **k):
        return self

    def __getattr__(self, name):
        return self

    def __getitem__(self, k):
        return self

    def __iter__(self):
        return iter(())

    def __bool__(self):
        return True


# 工控机程序在**导入期**就要用到的外部名 (相机 SDK / 检测器 / flask) —— 只做桩, 只有相机相关函数会真调它们
_STUB_NAMES = ["SciCamera", "SCI_DEVICE_INFO_LIST", "SCI_CAMERA_OK", "SciCamTLType",
               "SCI_CAM_PAYLOAD_ATTRIBUTE", "SciCam_Payload_GetAttribute", "SciCamPayloadMode",
               "SciCam_Payload_GetImage", "SciCamPixelType", "SciCam_Payload_ConvertImage",
               "SciCam_Payload_SaveImage", "YoloDetector", "Flask", "request", "jsonify", "Response"]


def load_aoi_module(path=SRC):
    """把工控机程序 exec 进来 (桩掉相机 SDK/检测器/flask + 去掉那几行 import), 代码本体一字不改。"""
    if AOI not in sys.path:
        sys.path.insert(0, AOI)
    src = open(path, encoding="utf-8").read()
    src = re.sub(r"^from (SciCam\w*|yolo_detector|flask) import .*$", "", src, flags=re.M)
    mod = types.ModuleType("aoi_under_test")
    mod.__file__ = path
    mod.__dict__["__name__"] = "aoi_under_test"      # 不跑 __main__
    for n in _STUB_NAMES:                            # 桩: 任意属性/调用都吞掉
        mod.__dict__[n] = _Any()
    exec(compile(src, path, "exec"), mod.__dict__)
    return mod


# ───────────────────────── 指标 ─────────────────────────
def stats(bgr, tag):
    if bgr is None:
        return {"口径": tag, "状态": "无图"}
    a = np.asarray(bgr)
    g = (cv2.cvtColor(a, cv2.COLOR_BGR2GRAY) if a.ndim == 3 else a).astype(np.float32)
    gx = np.abs(np.diff(g, axis=1))[:-1, :] if g.shape[1] > 1 else np.zeros((g.shape[0], 1))
    gy = np.abs(np.diff(g, axis=0))[:, :-1] if g.shape[0] > 1 else np.zeros((1, g.shape[1]))
    n = min(gx.shape[0], gy.shape[0]), min(gx.shape[1], gy.shape[1])
    ten = float((gx[:n[0], :n[1]] ** 2 + gy[:n[0], :n[1]] ** 2).mean())
    return {"口径": tag, "尺寸": "%dx%d" % (a.shape[1], a.shape[0]),
            "均值": round(float(g.mean()), 1), "std": round(float(g.std()), 1),
            "饱和%": round(float((g >= 250).mean() * 100), 2),
            "死白行": int((g >= 250).all(axis=1).sum()),
            "Tenengrad": round(ten, 0)}


def diff(a, b):
    """两张同尺寸图的差异 (证明"加框"这一步真的改了像素, 且改动集中在哪)。"""
    a = np.asarray(a, np.float32)
    b = np.asarray(b, np.float32)
    if a.shape != b.shape:
        return {"形状不同": [list(a.shape), list(b.shape)]}
    d = np.abs(a - b).mean(axis=2)
    rows = d.mean(axis=1)
    ys = np.where(rows > 1.0)[0]
    return {"平均绝对差": round(float(d.mean()), 3), "最大差": round(float(d.max()), 1),
            "变化像素占比%": round(float((d > 8).mean() * 100), 3),
            "变化行区间": ([int(ys.min()), int(ys.max())] if ys.size else None),
            "变化行数": int(ys.size)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", type=int, default=0, help="从 10082 取几张真原图(只读, 不触发拍照)")
    ap.add_argument("--imgs", default="", help="逗号分隔的本地原图")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    mod = load_aoi_module()
    print("已把工控机程序 exec 进本机 (桩模块, 版本=%s)" % getattr(mod, "VERSION", "?"))
    print("   canonical 画布 %dx%d · same 定尺 %dx%d · 模板 %s"
          % (mod.CANONICAL_W, mod.CANONICAL_H, mod.SAME_OUT_W, mod.SAME_OUT_H,
             os.path.exists(mod.TEMPLATE_PNG)))

    imgs = []
    if a.imgs:
        imgs = [p for p in a.imgs.split(",") if p]
    if a.live:
        for i in range(a.live):
            try:
                with urllib.request.urlopen(CAM + "/picture?kind=origin", timeout=30) as r:
                    b = r.read()
                p = os.path.join(OUT, "live_origin_%d_%s.jpg" % (i, time.strftime("%H%M%S")))
                open(p, "wb").write(b)
                imgs.append(p)
                print("  取真原图 →", p, len(b), "B")
            except Exception as e:                                              # noqa: BLE001
                print("  ✗ 取原图失败:", str(e)[:90])
    if not imgs:
        imgs = sorted(glob.glob(os.path.join(AOI, "goldfinger_images", "Finger_Image_W*_No_*.png")))[-2:]
    print("样本 %d 张: %s" % (len(imgs), [os.path.basename(p) for p in imgs]))

    report = {"ts": time.strftime("%F %T"), "src": SRC, "samples": []}
    for k, p in enumerate(imgs):
        bgr = cv2.imread(p)
        if bgr is None:
            print("  ✗ 读不了", p)
            continue
        rec = {"file": os.path.basename(p), "src_hw": [bgr.shape[1], bgr.shape[0]]}
        tag = os.path.splitext(os.path.basename(p))[0]

        # ① canonical
        mod.set_caliber("canonical")
        t0 = time.time()
        c_can, i_can = mod.crop_goldfinger_regular(bgr)
        t_can = (time.time() - t0) * 1000
        rec["canonical"] = {"stats": stats(c_can, "canonical"), "ms": round(t_can, 1),
                            "method": i_can.get("method"), "score": i_can.get("score"),
                            "caliber": i_can.get("caliber"), "natural": i_can.get("natural")}
        cv2.imwrite(os.path.join(OUT, "%s_canonical.png" % tag), c_can)

        # ② same
        mod.set_caliber("same")
        t0 = time.time()
        c_same, i_same = mod.crop_goldfinger_regular(bgr)
        t_same = (time.time() - t0) * 1000
        sm = i_same.get("same") or {}
        rec["same"] = {"stats": stats(c_same, "same"), "ms": round(t_same, 1),
                       "method": i_same.get("method"), "caliber": i_same.get("caliber"),
                       "natural": sm.get("natural"), "deskew_deg": sm.get("deskew_deg"),
                       "kept_rows": sm.get("kept_rows"), "canvas_trim": sm.get("canvas_trim"),
                       "x_trim": sm.get("x_trim"), "fallback": sm.get("fallback")}
        cv2.imwrite(os.path.join(OUT, "%s_same.png" % tag), c_same)

        # ③ 检测框叠加 (注入假框: 位置取图内可辨处, 只为证明"画得上去 + 可被像素级检出")
        h, w = c_same.shape[:2]
        fake = [{"id": 1, "class_name": "demo_scratch", "confidence": 0.87,
                 "bbox_xyxy": [int(w * 0.18), int(h * 0.30), int(w * 0.38), int(h * 0.62)], "judge": "NG"},
                {"id": 2, "class_name": "demo_stain", "confidence": 0.61,
                 "bbox_xyxy": [int(w * 0.55), int(h * 0.25), int(w * 0.72), int(h * 0.55)], "judge": "NG"}]
        objs = mod.detect_objects(fake, coord_hw=[w, h], coord_desc="demo")
        anno = mod.draw_detections(c_same, objs, verdict="NG", count=len(objs), ms=321.4, caliber="same")
        cv2.imwrite(os.path.join(OUT, "%s_same_anno_demo.png" % tag), anno)
        rec["anno_demo"] = {"diff_vs_判据图": diff(c_same, anno), "objects": objs}
        # 空检测(现场常见: 板子 OK) 也必须有一条状态条(所以 anno ≠ crop)
        anno_ok = mod.draw_detections(c_same, [], verdict="OK", count=0, ms=1576.4, caliber="same")
        cv2.imwrite(os.path.join(OUT, "%s_same_anno_ok.png" % tag), anno_ok)
        rec["anno_ok0"] = {"diff_vs_判据图": diff(c_same, anno_ok)}

        # ④ 与 4060 页面口径(canonical 显示) 的差异 —— 同口径渲染链的对照数(不作等价声明)
        try:
            sys.path.insert(0, os.path.join(R, "tools"))
            import aoi_exposure_fix as FX
            clean, _mc = FX.clean_judge_frame(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), out=900,
                                              return_natural=True)
            band = _mc["natural"]
            ang = float(mod.get_caliber() and (i_same.get("angle") or 0.0))
            if abs(ang) > 0.05:
                h0, w0 = band.shape[:2]
                M = cv2.getRotationMatrix2D((w0 / 2.0, h0 / 2.0), -ang, 1.0)
                band = cv2.warpAffine(band, M, (w0, h0), flags=cv2.INTER_LINEAR,
                                      borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))
            page = cv2.resize(cv2.cvtColor(band, cv2.COLOR_RGB2BGR), (mod.SAME_OUT_W, mod.SAME_OUT_H))
            cv2.imwrite(os.path.join(OUT, "%s_page_canonical_render.png" % tag), page)
            rec["page_render"] = {"stats": stats(page, "页面(canonical)"),
                                  "diff_vs_工控机同口径": diff(page, c_same)}
        except Exception as e:                                                  # noqa: BLE001
            rec["page_render"] = {"err": str(e)[:140]}

        report["samples"].append(rec)
        print("\n── %s (原图 %s)" % (rec["file"], rec["src_hw"]))
        print("   canonical %s  %sms  method=%s score=%s"
              % (rec["canonical"]["stats"].get("尺寸"), rec["canonical"]["ms"],
                 rec["canonical"]["method"], rec["canonical"]["score"]))
        print("   same      %s  %sms  原比例条带=%s 去倾角=%s° 空白裁除=%s sat=%s%% 细节=%s"
              % (rec["same"]["stats"].get("尺寸"), rec["same"]["ms"], rec["same"]["natural"],
                 rec["same"]["deskew_deg"], (rec["same"]["canvas_trim"] or {}).get("rows_dropped"),
                 rec["same"]["stats"].get("饱和%"), rec["same"]["stats"].get("Tenengrad")))
        print("   加框(假框) vs 判据图: %s" % replace_ascii(rec["anno_demo"]["diff_vs_判据图"]))
        print("   加框(空检OK) vs 判据图: %s" % replace_ascii(rec["anno_ok0"]["diff_vs_判据图"]))
        if "err" not in (rec.get("page_render") or {}):
            print("   页面(canonical渲染) vs 工控机同口径: %s"
                  % replace_ascii(rec["page_render"]["diff_vs_工控机同口径"]))

    dst = os.path.join(R, "reports", "aoi_caliber_offline_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    json.dump(report, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n产物: %s\n取证: %s" % (OUT, dst))
    return 0


def replace_ascii(d):
    return json.dumps(d, ensure_ascii=False)


if __name__ == "__main__":
    raise SystemExit(main())
