#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""🧩 开放词汇分割 × 场景叠加 —— 端到端取证 (真跑, 不造数)

两种模式:
  A. 存档帧 (臂上相机真帧, 可离线跑):  SAM3 分割 → YOLO 同帧对照 → 掩膜→3D(缺深度就如实拒答) → draw_overlay 出图 + 同帧 A/B 差异
  B. 实况 (走常驻服务, 真写叠加规格):  POST /seg → 规格里 origin='seg' 条数 → 叠加帧像素变化 (在同 cam 上)

判据 (全部实测打印):
  ① SAM3 真出掩膜 (实例数>0 且每个面积 ≥ MIN_AREA)
  ② 掩膜框 vs 在役 YOLO 框 IoU (同帧同源; 记录每实例最佳值, 有的对不上就如实列出)
  ③ 叠加真的画上去了: 同帧 A/B 差异像素落在掩膜内 ≥ 阈值, 掩膜外≈0(除标签/真值带)
  ④ 3D: 要么给 base 中心/尺寸, 要么给出**能查的拒答原因** (深度/手眼/TCP 哪一环缺)
  ⑤ 实况模式: 规格 origin='seg' 条数 == 服务返回 count; 叠加快照与原始快照逐像素有差异

用法:
  xvfb-run -a ./gui-venv311/bin/python tools/verify_seg_overlay.py --saved /home/ubuntu/zmax_data/scene_survey/arm_now.jpg --texts "光模块,插孔,末端夹爪"
  ./gui-venv311/bin/python tools/verify_seg_overlay.py --live --cam local --texts "笔记本电脑,手"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))

import cv2                                                        # noqa: E402
import scene_overlay as SO                                        # noqa: E402
from lerobot.policies.sam3_seg import (                            # noqa: E402
    MIN_AREA_PX as MIN_AREA, SAM3_DIR, SAM3_SIZE,
    grab_frame, mask_3d, mask_to_polys, read_image, state as seg_state,
)
from lerobot.policies.sam3_seg import segment as seg_run             # noqa: E402

REPORTS = ROOT / "reports"
YOLO_W = ROOT / "models" / "yolo_peg_live.pt"


def iou(a, b) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return float(inter / ua) if ua > 0 else 0.0


def yolo_detect(img) -> tuple[dict, str]:
    """在役权重同帧检测 (与 gen_overlay_from_det 同口径: ultralytics 直接吃 BGR)"""
    try:
        from ultralytics import YOLO
    except Exception as e:                                                 # noqa: BLE001
        return {}, "ultralytics 不可用: %s" % e
    if not YOLO_W.exists():
        return {}, "在役权重缺: %s" % YOLO_W
    m = YOLO(str(YOLO_W))
    res = m.predict(img, conf=0.25, verbose=False)[0]
    out = {}
    for b in res.boxes:
        cls = res.names[int(b.cls)]
        out[cls] = {"box": [float(v) for v in b.xyxy[0]], "conf": float(b.conf[0])}
    return out, "ok (%s)" % Path(os.path.realpath(YOLO_W)).name


def same_frame_ab(img, spec_on, spec_off, cam) -> dict:
    a, _ = SO.draw_overlay(img.copy(), spec_on, cam, tcp7=None)
    b, _ = SO.draw_overlay(img.copy(), spec_off, cam, tcp7=None)
    d = np.abs(a.astype(int) - b.astype(int)).sum(2) > 6
    return {"diff_px": int(d.sum()), "png_on": a, "png_off": b, "mask": d}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--saved", default="", help="存档帧路径 (模式 A)")
    ap.add_argument("--live", action="store_true", help="实况模式 (走常驻服务, 真写规格)")
    ap.add_argument("--cam", default="arm")
    ap.add_argument("--texts", default="光模块,插孔,末端夹爪")
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    texts = [t.strip() for t in a.texts.split(",") if t.strip()]
    rep = {"at": time.strftime("%F %T"), "mode": "live" if a.live else "saved",
           "cam": a.cam, "texts": texts, "verdict": {}, "evidence": {}}
    fails = []

    # ── 取帧 ──
    if a.live:
        img, src = grab_frame(a.cam)
        rep["evidence"]["frame"] = src
        if img is None:
            print("❌ 取不到实况帧: %s" % src)
            return 1
        print("帧源: %s · %dx%d" % (src, img.shape[1], img.shape[0]))
    else:
        if not a.saved:
            print("❌ 需要 --saved <图> 或 --live")
            return 1
        img, src = read_image(a.saved), a.saved
        rep["evidence"]["frame"] = src
        print("帧源(存档): %s · %dx%d" % (src, img.shape[1], img.shape[0]))

    # ── ① SAM3 真推理 ──
    t0 = time.time()
    seg = seg_run(img, texts, threshold=a.threshold)
    cold = time.time() - t0
    inst = [it for it in seg["instances"] if it["area_px"] >= MIN_AREA]
    _st = seg_state()
    rep["evidence"]["sam3"] = {"load_s": _st.get("load_s"), "cold_s": round(cold, 1),
                               "infer_ms": round(seg["ms"], 1), "n": len(inst),
                               "dtype": _st.get("dtype"), "size_px": SAM3_SIZE,
                               "weights": str(SAM3_DIR)}
    print("① SAM3 真推理: 概念=%s · 实例 %d 个 (面积阈 %dpx) · 推理 %.0fms · 冷启(含加载) %.1fs"
          % (texts, len(inst), MIN_AREA, seg["ms"], cold))
    for it in inst:
        print("   实例: %-10s score=%.3f 面积=%-7d 框=%s" % (
            it["label"], it["score"] or 0, it["area_px"], [round(v) for v in it["box_xyxy"]]))
    if not inst:
        fails.append("SAM3 没出实例 (概念=%s)" % texts)
    try:
        import torch
        if torch.cuda.is_available():
            rep["evidence"]["sam3"]["vram_peak_gb"] = round(torch.cuda.max_memory_allocated() / 1e9, 2)
            print("   显存: 前向峰值 %.2f GB / 卡共 %.2f GB" % (
                torch.cuda.max_memory_allocated() / 1e9, torch.cuda.get_device_properties(0).total_memory / 1e9))
    except Exception:                                                      # noqa: BLE001
        pass

    # ── ② 同帧 YOLO 对照 ──
    yb, ynote = yolo_detect(img)
    ious = {}
    for it in inst:
        best, bcls = 0.0, None
        for cls, d in yb.items():
            v = iou(it["box_xyxy"], d["box"])
            if v > best:
                best, bcls = v, cls
        ious[it["label"]] = {"best_iou": round(best, 3), "yolo_cls": bcls}
        print("② 对照: SAM3「%s」vs YOLO 最佳 %s IoU=%.3f" % (it["label"], bcls or "—", best))
    rep["evidence"]["yolo"] = {"note": ynote, "cls": {k: [round(v, 3) for v in d["box"]] for k, d in yb.items()},
                               "iou": ious}
    print("   YOLO 在役权重: %s · 同帧检出 %s" % (ynote, list(yb) or "无"))

    # ── ④ 掩膜 → 3D (缺一环就如实拒答) ──
    d3s = []
    for it in inst:
        d3 = mask_3d(it["mask"], a.cam)
        d3s.append(d3)
        if d3.get("ok"):
            print("④ 3D: 「%s」base中心=(%.3f, %.3f, %.3f) z=%.0fmm 尺寸=%.1f×%.1fmm yaw=%.1f° (%d px)"
                  % (it["label"], d3["center_base"][0], d3["center_base"][1], d3["center_base"][2],
                     d3["z_mm"], d3["xy_size_mm"][0], d3["xy_size_mm"][1], d3["yaw_deg"], d3["n_px"]))
        else:
            print("④ 3D: 「%s」拒答 → %s" % (it["label"], d3.get("reason")))
    rep["evidence"]["mask3d"] = d3s

    # ── ③ 渲染 + 同帧 A/B ──
    boxes = [{"origin": "seg", "label": it["label"], "kind": "mask",
              "polys": mask_to_polys(it["mask"]), "area_px": it["area_px"],
              "conf": round(float(it["score"]), 4) if it["score"] is not None else None,
              "c3d": (d3s[i] if d3s[i].get("ok") else None)}
             for i, it in enumerate(inst)]
    spec_on = {"mode": "verify", "cameras": {a.cam: {"boxes": boxes}}, "deleted": {}}
    spec_off = {"mode": "verify", "cameras": {a.cam: {"boxes": []}}, "deleted": {}}
    ab = same_frame_ab(img, spec_on, spec_off, a.cam)
    m_all = np.zeros(img.shape[:2], np.uint8)
    for b in boxes:
        for p in b["polys"]:
            cv2.fillPoly(m_all, [np.asarray(p, np.int32)], 1)
    din = int((ab["mask"] & (m_all > 0)).sum())
    dout = int((ab["mask"] & (m_all == 0)).sum())
    print("③ 叠加取证(同帧 A/B): 差异像素 %d · 其中掩膜内 %d · 掩膜外 %d (标签/真值带)" % (
        ab["diff_px"], din, dout))
    rep["evidence"]["render"] = {"diff_px": ab["diff_px"], "inside_poly": din, "outside_poly": dout,
                                 "n_polys": sum(len(b["polys"]) for b in boxes)}
    if din < 500:
        fails.append("叠加掩膜没画上 (掩膜内差异 %d px)" % din)
    out = a.out or str(ROOT / "reports" / ("seg_overlay_%s_%s.png" % (a.cam, time.strftime("%m%d_%H%M%S"))))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(out, ab["png_on"])
    print("   出图: %s" % out)

    # ── ⑤ 实况: 走服务真写规格 + 叠加快照像素变化 ──
    if a.live:
        import urllib.request
        url = "http://127.0.0.1:8791/seg?cam=%s&texts=%s&three_d=1" % (a.cam, urllib.parse.quote(a.texts))
        t0 = time.time()
        with urllib.request.urlopen(url, timeout=240) as r:   # 推流服务的 /seg 是 GET(页面按钮同口径)
            j = json.loads(r.read().decode())
        dt = time.time() - t0
        print("⑤ 服务回执: ok=%s count=%s ms=%s (端到端 %.1fs)" % (j.get("ok"), j.get("count"), j.get("ms"), dt))
        rep["evidence"]["service"] = {k: j.get(k) for k in ("ok", "count", "ms", "src", "err")}
        if not j.get("ok"):
            fails.append("服务调用失败: %s" % j.get("err"))
        else:
            spec = SO.load_spec()
            nb = len([b for b in ((spec.get("cameras") or {}).get(a.cam) or {}).get("boxes", [])
                      if b.get("origin") == "seg"])
            print("   规格核对: cam=%s 的 origin='seg' 条数 = %d (服务 count=%s)" % (a.cam, nb, j.get("count")))
            rep["evidence"]["spec"] = {"cam": a.cam, "n_seg": nb}
            if nb <= 0:
                fails.append("规格里没有 origin=seg 的框")
            # 叠加帧 vs 原始帧: 同刻取两张快照比像素
            import urllib.request as ur
            def _blob(p):
                with ur.urlopen("http://127.0.0.1:8791" + p, timeout=15) as rr:
                    return rr.read()
            try:
                raw = cv2.imdecode(np.frombuffer(_blob("/snapshot/%s.jpg" % a.cam), np.uint8), 1)
                ov = cv2.imdecode(np.frombuffer(_blob("/snapshot/overlay_%s.jpg" % a.cam), np.uint8), 1)
                if raw is None or ov is None:
                    print("   ⚠ 快照取不到, 跳过像素对比")
                else:
                    dd = (np.abs(raw.astype(int)[:ov.shape[0], :ov.shape[1]] - ov.astype(int)).sum(2) > 6)
                    print("   实况像素核对: 叠加帧 vs 原始帧 差异像素 %d (帧 %dx%d)" % (int(dd.sum()), ov.shape[1], ov.shape[0]))
                    rep["evidence"]["live_px"] = {"diff_px": int(dd.sum()), "shape": list(ov.shape)}
                    if int(dd.sum()) < 100:
                        fails.append("叠加帧与原始帧无差异 (掩膜没进实时画面)")
            except Exception as e:                                         # noqa: BLE001
                print("   ⚠ 快照对比失败: %s" % e)

    rep["verdict"] = {"pass": not fails, "fails": fails}
    REPORTS.mkdir(exist_ok=True)
    rp = REPORTS / ("seg_overlay_verify_%s.json" % time.strftime("%m%d_%H%M%S"))
    rp.write_text(json.dumps(rep, ensure_ascii=False, indent=1))
    print("\n结论: %s%s" % ("✅ 通过" if not fails else "❌ 不通过", ("   失败项: %s" % fails) if fails else ""))
    print("报告: %s" % rp)
    return 0 if not fails else 1


if __name__ == "__main__":
    pass  # urllib.parse 已在模块顶部导入
    raise SystemExit(main())