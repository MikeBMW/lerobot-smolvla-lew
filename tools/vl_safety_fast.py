#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""vl_safety_fast.py — ⚡ 快反射层: 本地视觉安全检查 (老倪 2026-09-27: 「安全反馈要快点」)

为什么要这层: 慢层(DeepSeek VL)单次 7~45s ⇒ 挡得住"持续危害", 挡不住"手突然伸进来"。
本层是**本地纯 CV、无网络**, 5Hz 轮询臂上相机(该相机 1.8Hz ⇒ 实际响应 ≈ 0.6s), 判"镜头被挡":
  · 画面大面积同质(遮挡/贴脸) —— 手/物体怼到镜头前
  · 纹理塌陷(Laplacian 方差极低) —— 失焦/被糊住
  · 整幅过暗/过曝且同质 —— 被盖死
任一成立 ⇒ 写 vl_safety_fast.json: safe=false (带指标与时刻); 否则 safe=true。
执行层读它(保鲜 4s, fail-closed): 快层不安全 / 快层没在跑 ⇒ 一律拒发。

用法:
  ./gui-venv311/bin/python tools/vl_safety_fast.py            # 常驻 5Hz
  ./gui-venv311/bin/python tools/vl_safety_fast.py --once     # 单次(取证)
  ./gui-venv311/bin/python tools/vl_safety_fast.py --hz 5 --show   # 打印指标
输出: ~/zmax_data/vl_safety_fast.json · 事件图 ~/zmax_data/vl_safety_fast_evt/<时刻>.jpg
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np

STREAM = os.environ.get("ZMAX_STREAM", "http://127.0.0.1:8791")
OUT = Path(os.path.expanduser("~/zmax_data/vl_safety_fast.json"))
EVT = Path(os.path.expanduser("~/zmax_data/vl_safety_fast_evt"))
CAMS = ("arm", "local")          # 臂上(看工具/工件) + 笔记本(全局)
MAX_FRAME_AGE = 3.0              # 帧太旧就没意义

# 判据阈值(保守起步, 现场按实测调)
UNIFORM_BLOCK = 0.80             # 同质像素占比 > 此值 ⇒ 判被挡
LAP_MIN = 30.0                   # Laplacian 方差 < 此值 ⇒ 判纹理塌陷
DARK_MEAN, BRIGHT_MEAN = 32.0, 228.0


def _grab(name: str, timeout=3.0):
    try:
        with urllib.request.urlopen("%s/snapshot/%s.jpg?_=%d" % (STREAM, name, int(time.time())),
                                    timeout=timeout) as r:
            return r.read()
    except Exception:                                                   # noqa: BLE001
        return None


def _ages() -> dict:
    try:
        with urllib.request.urlopen("%s/stats" % STREAM, timeout=2) as r:
            d = json.loads(r.read().decode())
        fr = d.get("frames") or d
        return {k: (fr.get(k) or {}).get("age_s") for k in CAMS}
    except Exception:                                                   # noqa: BLE001
        return {}


def judge(im: np.ndarray) -> dict:
    """单帧判"镜头是否被挡" —— 只输出客观指标, 不做语义猜测"""
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    med = float(np.median(g))
    uniform = float(np.mean(np.abs(g.astype(np.int16) - med) < 14))
    lap = float(cv2.Laplacian(g, cv2.CV_64F).var())
    mean = float(g.mean())
    dark = bool(mean < DARK_MEAN and uniform > 0.6)
    bright = bool(mean > BRIGHT_MEAN and uniform > 0.6)
    blocked = bool(uniform > UNIFORM_BLOCK and lap < LAP_MIN)
    return {"mean": round(mean, 1), "median": round(med, 1), "uniform_frac": round(uniform, 3),
            "lap_var": round(lap, 1), "blocked": blocked, "dark": dark, "bright": bright,
            "unsafe": bool(blocked or dark or bright)}


def run_once(show=False, save_evt=True) -> dict:
    ages = _ages()
    per, unsafe, reasons = {}, [], []
    frames = {}
    for c in CAMS:
        b = _grab(c)
        if not b:
            per[c] = {"err": "无帧"}
            reasons.append("%s 取帧失败" % c)
            unsafe.append(c)
            continue
        im = cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR)
        if im is None:
            per[c] = {"err": "解码失败"}
            unsafe.append(c)
            continue
        frames[c] = im
        j = judge(im)
        a = ages.get(c)
        j["age_s"] = a
        if a is None or float(a) > MAX_FRAME_AGE:
            j["stale"] = True
        per[c] = j
        if j["unsafe"]:
            unsafe.append(c)
            reasons.append("%s: 遮挡/糊化(uniform=%.2f lap=%.0f mean=%.0f)" % (c, j["uniform_frac"], j["lap_var"], j["mean"]))
        if show:
            print("   %-6s %s" % (c, json.dumps(j, ensure_ascii=False)))
    rec = {"ts": time.time(), "ts_str": time.strftime("%F %T"), "per_cam": per,
           "safe": len(unsafe) == 0, "unsafe_cams": unsafe,
           "why": "；".join(reasons) if reasons else "臂上/笔记本画面纹理正常、无遮挡"}
    OUT.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    if not rec["safe"] and save_evt and frames:
        EVT.mkdir(parents=True, exist_ok=True)
        if "arm" in frames:
            cv2.imwrite(str(EVT / (time.strftime("%Y%m%d_%H%M%S") + "_arm.jpg")), frames["arm"])
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--hz", type=float, default=5.0)
    ap.add_argument("--show", action="store_true")
    a = ap.parse_args()
    if a.once:
        r = run_once(a.show)
        print(json.dumps({k: r[k] for k in ("ts_str", "safe", "why", "unsafe_cams")}, ensure_ascii=False))
        return 0
    period = max(0.05, 1.0 / max(0.5, a.hz))
    print("⚡ 快反射层常驻: %.0fHz · 判『镜头被挡』(同质>%.2f 且 纹理<%.0f) · 输出 %s"
          % (a.hz, UNIFORM_BLOCK, LAP_MIN, OUT), flush=True)
    last = True
    while True:
        try:
            r = run_once(show=a.show)
            if r["safe"] != last:                                    # 只在翻转时报, 不刷屏
                print("[%s] %s %s" % (r["ts_str"], "✅ 恢复安全" if r["safe"] else "🚨 判不安全", r["why"]), flush=True)
                last = r["safe"]
        except Exception as e:                                       # noqa: BLE001
            print("轮次异常: %s: %s" % (type(e).__name__, str(e)[:140]), flush=True)
        time.sleep(period)


if __name__ == "__main__":
    raise SystemExit(main())
