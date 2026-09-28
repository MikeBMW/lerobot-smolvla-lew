#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""l5_corner_slots_annotate.py — 四角光模块 + 14 槽位 的 L5 视觉标注(复用既有大模型通道)

老倪 (2026-09-28): 手动把四个光模块摆到治具四个角上, 要求 ①标记四个光模块 ②标记中间 14 个槽位
③在总览页(/overlay)上看得见 ④进数据闭环

本脚本只做「大模型复核」那一步:
  · 取最新实帧(默认 8792 直连 + 8791 snapshot 双路互证, 见 skill zmax-live-video-stream 坑#7)
  · 用 gen_overlay_from_vlm.call_vlm (max_tokens=MAXTOK=9000, 严格 JSON, 左上原点像素口径)
  · 提示词要求逐条报: 治具整体框 / 四角光模块(4) / 14 个槽位逐个(row+col+bbox+conf)
  · 原图 + 标注图 + JSON 落盘
判据/红线:
  · 不检出就写「未检出」, 绝不补假框; 低置信(<0.5)一律保留并标出
  · 只取图/推理/落盘, 不连 Orin 下发任何动作

用法:
  python3 tools/l5_corner_slots_annotate.py                 # 自动取帧
  python3 tools/l5_corner_slots_annotate.py --img /path.jpg
输出目录: ~/zmax_data/l5_corners/<ts>/{arm_raw.jpg, vlm_slots.json, arm_vlm_ann.jpg, log.txt}
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import gen_overlay_from_vlm as G                                        # noqa: E402
import cv2                                                              # noqa: E402
import numpy as np                                                      # noqa: E402

ORIN = os.environ.get("ZMAX_ARM_URL", "http://192.168.23.66:8792/frame.jpg")
LOCAL = os.environ.get("ZMAX_STREAM", "http://127.0.0.1:8791")
OUTROOT = Path(os.path.expanduser("~/zmax_data/l5_corners"))

PROMPT = """你是 Z-MAX 具身智能平台的 L5 视觉理解层。这是**臂上相机(Intel RealSense D405)对真实工位的实拍帧**, 尺寸 {W}x{H} 像素。

画面里是一块**黑色塑料治具(托盘)**, 治具上有两排**矩形凹槽(槽位)**, 中间是空的。有人**手动把 4 个光模块(长的白色/银色本体 + 绿色卡扣/拉环)摆在了治具的四个角上**。

请你**只依据画面里真实看得见的东西**回答, 逐条报, 不要推测、不要为了凑数编框。坐标一律用**左上角为原点**的像素, [x_min, y_min, x_max, y_max], 且 x_max>x_min, y_max>y_min。

输出**一个 JSON 对象**(不要 markdown 代码块、不要多余文字), 字段:
{{
 "scene": "一句话描述你看到什么(中文)",
 "fixture": {{"bbox": [x1,y1,x2,y2], "conf": 0.0-1.0}},
 "corner_modules": [
   {{"id": "TL", "bbox": [x1,y1,x2,y2], "conf": 0.0-1.0, "green_part_bbox": [x1,y1,x2,y2], "note": "看得见/被遮挡"}},
   {{"id": "TR", "bbox": [...], "conf": 0.0-1.0, "green_part_bbox": [...], "note": ""}},
   {{"id": "BL", "bbox": [...], "conf": 0.0-1.0, "green_part_bbox": [...], "note": ""}},
   {{"id": "BR", "bbox": [...], "conf": 0.0-1.0, "green_part_bbox": [...], "note": ""}}
 ],
 "slot_rows": <你数到的凹槽排数>,
 "slots": [
   {{"id": "slot_01", "row": "上排", "col": 1, "bbox": [x1,y1,x2,y2], "conf": 0.0-1.0, "occluded": false, "why": "短说明"}},
   ... 逐个列出, 一共要尽力列到 14 个(slot_01 ... slot_14)
 ],
 "slots_not_detected": ["slot_05", "..."],
 "count_note": "你实际看清了几个槽位; 哪几个被模块挡住或看不出来; 你的总体把握(高/中/低)"
}}

要求:
1. 上排凹槽从治具左端到右端**逐个**报, 再报下排, 左右顺序不要乱。
2. 被 4 个光模块**挡住**的槽位, 也要报出你**估计**的位置并置 "occluded": true, conf 给真实把握(可以 <0.5)。
3. 每一条 bbox 必须**紧贴**凹槽的矩形边沿(不要比凹槽大一圈, 也不要只框住凹槽内部一小块)。
4. conf < 0.5 的条目**必须保留**, 不要删掉。
5. 如果某排你只能看清 5 个, 就只报 5 个, 其余写进 slots_not_detected, **不要凑数**。
"""


def fetch(url: str, timeout: int = 15) -> bytes:
    req = urllib.request.Request(url + ("&" if "?" in url else "?") + "_=%d" % int(time.time() * 1000))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def grab_arm(path: str = "") -> tuple[bytes, dict]:
    """取最新实帧; 两条独立来路互证(Orin 直连 8792 / 本机推流 8791)"""
    ev = {"sources": []}
    if path:
        raw = Path(path).read_bytes()
        ev["sources"].append({"src": path, "bytes": len(raw)})
        return raw, ev
    got = []
    for name, url in (("orin:8792", ORIN), ("local:8791", LOCAL + "/snapshot/arm.jpg")):
        try:
            b = fetch(url)
            if len(b) < 2000:
                raise ValueError("too small %dB" % len(b))
            got.append((name, url, b))
        except Exception as e:                                          # noqa: BLE001
            ev["sources"].append({"src": name, "err": "%s: %s" % (type(e).__name__, str(e)[:80])})
    if not got:
        raise RuntimeError("两路取帧都失败: %s" % ev["sources"])
    # 主用 Orin 直连(相机原生 30fps), 没有就用本机
    primary = next((g for g in got if g[0].startswith("orin")), got[0])
    for name, url, b in got:
        img = cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR)
        ev["sources"].append({"src": name, "url": url, "bytes": len(b),
                              "md5": hashlib.md5(b).hexdigest()[:12],
                              "shape": None if img is None else list(img.shape),
                              "mean": None if img is None else round(float(img.mean()), 1)})
    ev["primary"] = primary[0]
    return primary[2], ev


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--img", default="", help="用本地图片而不是取实时帧")
    ap.add_argument("--send-w", type=int, default=1024, help="送模型前最长边(默认 1024)")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--tag", default="")
    a = ap.parse_args()

    ts = time.strftime("%m%d_%H%M%S") + (("_" + a.tag) if a.tag else "")
    outdir = OUTROOT / ts
    outdir.mkdir(parents=True, exist_ok=True)
    log = open(outdir / "log.txt", "w", encoding="utf-8")

    def p(*xs):
        s = " ".join(str(x) for x in xs)
        print(s)
        log.write(s + "\n")
        log.flush()

    t0 = time.time()
    raw, ev = grab_arm(a.img)
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        p("✗ 帧解码失败")
        return 2
    H, W = img.shape[:2]
    mt = time.time()
    cv2.imwrite(str(outdir / "arm_raw.jpg"), img)
    p("[取帧] %s · %dx%d · %dB · %s" % (time.strftime("%F %T"), W, H, len(raw), json.dumps(ev, ensure_ascii=False)))

    k = min(1.0, float(a.send_w) / max(W, H))
    sm = cv2.resize(img, (int(W * k), int(H * k)), interpolation=cv2.INTER_AREA) if k < 1.0 else img
    h2, w2 = sm.shape[:2]
    ok, enc = cv2.imencode(".jpg", sm, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    p("[送模型] %dx%d · %dB · model=%s · max_tokens=%d" % (w2, h2, len(enc.tobytes()), G.MODEL, G.MAXTOK))
    r = G.call_vlm(enc.tobytes(), w2, h2, timeout=a.timeout, prompt=PROMPT.format(W=w2, H=h2))
    txt = (r.get("txt") or "").strip()
    rec = {"ts": time.strftime("%F %T"), "img": str(outdir / "arm_raw.jpg"), "wh": [W, H],
           "sent_wh": [w2, h2], "scale": round(k, 4), "model": r.get("model"),
           "latency_s": round(float(r.get("latency_s") or 0), 1), "usage": r.get("usage"),
           "grab_evidence": ev, "prompt_sha16": hashlib.sha256(PROMPT.encode()).hexdigest()[:16],
           "raw_txt": txt}
    if not txt:
        rec["err"] = "大模型 content 空"
        rec["reasoning_head"] = (r.get("reasoning") or "")[:500]
        (outdir / "vlm_slots.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        p("✗ 大模型 content 空 · 推理 %.0fs" % (r.get("latency_s") or 0))
        return 3

    d = G.parse_json(txt)
    def fix(b):
        if not (isinstance(b, (list, tuple)) and len(b) == 4):
            return None
        x1, y1, x2, y2 = [float(v) / k for v in b]
        x1, x2 = sorted((max(0.0, min(W - 1, x1)), max(0.0, min(W - 1, x2))))
        y1, y2 = sorted((max(0.0, min(H - 1, y1)), max(0.0, min(H - 1, y2))))
        if (x2 - x1) < 3 or (y2 - y1) < 3:
            return None
        return [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)]

    mods = []
    for o in (d.get("corner_modules") or []):
        b = fix(o.get("bbox"))
        if b:
            mods.append({"id": str(o.get("id") or "?")[:4], "bbox": b, "conf": o.get("conf"),
                         "green": fix(o.get("green_part_bbox")), "note": str(o.get("note") or "")[:60]})
    slots = []
    for o in (d.get("slots") or []):
        b = fix(o.get("bbox"))
        if b:
            slots.append({"id": str(o.get("id") or "?")[:12], "row": str(o.get("row") or "")[:6],
                          "col": o.get("col"), "bbox": b, "conf": o.get("conf"),
                          "occluded": bool(o.get("occluded")), "why": str(o.get("why") or "")[:60]})
    rec.update({"scene": str(d.get("scene") or "")[:300], "fixture": fix(((d.get("fixture") or {}) or {}).get("bbox")),
                "corner_modules": mods, "n_modules": len(mods),
                "slots": slots, "n_slots": len(slots), "slot_rows": d.get("slot_rows"),
                "slots_not_detected": d.get("slots_not_detected"), "count_note": str(d.get("count_note") or "")[:300]})
    (outdir / "vlm_slots.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")

    out = img.copy()
    if rec["fixture"]:
        x1, y1, x2, y2 = [int(v) for v in rec["fixture"]]
        cv2.rectangle(out, (x1, y1), (x2, y2), (255, 255, 255), 2)
    for m in mods:
        x1, y1, x2, y2 = [int(v) for v in m["bbox"]]
        cv2.rectangle(out, (x1, y1), (x2, y2), (0, 0, 255), 2)
        cv2.putText(out, "MOD_%s" % m["id"], (x1 + 2, y1 + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1)
    for s in slots:
        x1, y1, x2, y2 = [int(v) for v in s["bbox"]]
        c = (0, 255, 255) if (s["conf"] or 0) >= 0.5 else (0, 140, 255)      # <0.5 用橙色, 一眼看出低置信
        cv2.rectangle(out, (x1, y1), (x2, y2), c, 1)
        cv2.putText(out, s["id"].replace("slot_", "S"), (x1 + 1, y1 + 12), cv2.FONT_HERSHEY_SIMPLEX, 0.38, c, 1)
    cv2.imwrite(str(outdir / "arm_vlm_ann.jpg"), out)
    p("[大模型] %.0fs · scene=%s" % (rec["latency_s"], rec["scene"]))
    p("[大模型] 治具框=%s · 模块 %d 个 · 槽位 %d 个 · 排数=%s" % (rec["fixture"], len(mods), len(slots), rec["slot_rows"]))
    for s in slots:
        p("   %-8s %-4s col=%-3s bbox=%-28s conf=%s%s" % (s["id"], s["row"], s["col"], s["bbox"], s["conf"],
                                                          "  ⚠被遮挡" if s["occluded"] else ""))
    p("[低置信<0.5] %s" % ([s["id"] for s in slots if (s["conf"] or 0) < 0.5] or "无"))
    p("[未检出] %s" % (rec["slots_not_detected"],))
    p("outdir=%s" % outdir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
