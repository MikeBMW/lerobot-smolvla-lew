#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""auto_annotate.py — 6 路实拍 → L5 视觉语言理解 → **自动标注**(场景描述 + 边界框 + 标注图)

老倪 (2026-09-27): 「你现在已经有了 3 个摄像头, 1 个深度双目, 两个 OPT 相机; 你现在调用大模型层,
用视觉语言, 开始理解这个场景, 开始自动标注; 我现在到飞书端与你人机交互」

复用既有件(不另造一套):
  · 取帧  : 视频流 8791 `/snapshot/<cam>.jpg` (三相机 / 深度 / 两路 OPT 判据图)
  · 大模型: `gen_overlay_from_vlm.call_vlm`  —— L5 视觉档(默认 deepseek-v4-flash),
            严格 JSON + 左上原点像素口径, 复用它**已固化的坑**: max_tokens 给足(否则 content 空)
  · 画框  : cv2 矩形 + PIL 中文标签(缺 CJK 字体自动降级为编号)
输出(每批一个目录):
  ~/zmax_data/auto_annotate/<批次>/
      <cam>.jpg / <cam>_ann.jpg / <cam>.json    每路的原图 / 标注图 / 标注数据
      annotations.jsonl                         追加式数据集(自动标注的成品)
      summary.json                              本批汇总(路数/物体数/耗时/模型)

用法:
  python3 tools/auto_annotate.py                    # 跑一批(默认 6 路全跑)
  python3 tools/auto_annotate.py --cams arm,aoi_gold
  python3 tools/auto_annotate.py --watch 300        # 常驻: 每 300s 一批(自动标注流水线)
  python3 tools/auto_annotate.py --push-overlay     # 额外把 arm 那路的框写进场景叠加规格
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
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

STREAM = os.environ.get("ZMAX_STREAM", "http://127.0.0.1:8791")
OUTROOT = Path(os.path.expanduser("~/zmax_data/auto_annotate"))
CAMS = ["arm", "local", "local2", "depth", "aoi_gold", "aoi_surface"]
LABELS = {"arm": "🤖 臂上相机", "local": "💻 笔记本内置", "local2": "📺 MAXHUB 顶视",
          "depth": "🟠 深度双目", "aoi_gold": "🟡 OPT金手指", "aoi_surface": "⚪ OPT表面"}
SEND_W = 1024          # 送模型前缩放的最长边(省 token/时延); 框坐标再按比例映回原图
_FONT = None


def _font(sz=17):
    """找一个能显示中文的字体(PIL); 找不到返回 None ⇒ 标签降级为编号"""
    global _FONT
    if _FONT is None:
        from PIL import ImageFont
        for p in ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
                  "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                  "/usr/share/fonts/truetype/arphic/uming.ttc",
                  "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
            if os.path.isfile(p):
                try:
                    _FONT = ImageFont.truetype(p, sz)
                    break
                except Exception:                                       # noqa: BLE001
                    continue
        if _FONT is None:
            _FONT = False
    return _FONT or None


def grab(cam: str) -> bytes:
    url = "%s/snapshot/%s.jpg?_=%d" % (STREAM, cam, int(time.time()))
    with urllib.request.urlopen(url, timeout=15) as r:
        return r.read()


def annotate(cam: str, outdir: Path, send_w: int = SEND_W) -> dict:
    """一路: 取帧 → 缩放到 send_w → L5 理解 → 框按比例映回原图 → 落盘"""
    rec = {"cam": cam, "label": LABELS.get(cam, cam), "ts": time.strftime("%F %T"), "ok": False}
    try:
        raw = grab(cam)
        img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            rec["err"] = "取到的不是图片(%dB)" % len(raw)
            return rec
        H, W = img.shape[:2]
        k = min(1.0, float(send_w) / max(W, H))
        sm = cv2.resize(img, (int(W * k), int(H * k)), interpolation=cv2.INTER_AREA) if k < 1.0 else img
        h2, w2 = sm.shape[:2]
        ok, enc = cv2.imencode(".jpg", sm, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
        r = G.call_vlm(enc.tobytes(), w2, h2, timeout=300)
        txt = (r.get("txt") or "").strip()
        if not txt:
            rec["err"] = "大模型 content 空(推理额度吃满?) · model=%s · %.0fs" % (r.get("model"), r.get("latency_s") or 0)
            rec["reasoning_head"] = (r.get("reasoning") or "")[:300]
            return rec
        d = G.parse_json(txt)
        objs = []
        for o in (d.get("objects") or []):
            b = o.get("bbox")
            if not (isinstance(b, (list, tuple)) and len(b) == 4):
                continue
            x1, y1, x2, y2 = [float(v) / k for v in b]                  # 映回原图
            x1, x2 = sorted((max(0.0, min(W - 1, x1)), max(0.0, min(W - 1, x2))))
            y1, y2 = sorted((max(0.0, min(H - 1, y1)), max(0.0, min(H - 1, y2))))
            if (x2 - x1) < 4 or (y2 - y1) < 4:
                continue
            objs.append({"label": str(o.get("label") or "?")[:20],
                         "bbox": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
                         "conf": o.get("conf"), "why": str(o.get("why") or "")[:40]})
        rec.update({"ok": True, "w": W, "h": H, "scene": str(d.get("scene") or "")[:200],
                    "objects": objs, "n_obj": len(objs),
                    "model": r.get("model"), "latency_s": round(float(r.get("latency_s") or 0), 1),
                    "sent_wh": [w2, h2], "scale": round(k, 4), "usage": r.get("usage"),
                    "raw_txt": txt[:1200]})
        cv2.imwrite(str(outdir / ("%s.jpg" % cam)), img)                 # 原图留档
        cv2.imwrite(str(outdir / ("%s_ann.jpg" % cam)), draw(img, objs))
        (outdir / ("%s.json" % cam)).write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:                                              # noqa: BLE001
        rec["err"] = "%s: %s" % (type(e).__name__, str(e)[:180])
    return rec


def draw(img, objs):
    """画框 + 标签(中文用 PIL, 没字体就退化成编号)"""
    out = img.copy()
    colors = [(0, 255, 0), (0, 200, 255), (255, 160, 0), (255, 0, 200), (120, 255, 120), (255, 255, 0)]
    for i, o in enumerate(objs):
        x1, y1, x2, y2 = [int(v) for v in o["bbox"]]
        c = colors[i % len(colors)]
        cv2.rectangle(out, (x1, y1), (x2, y2), c, 2)
        tag = "%s %s" % (o["label"], ("" if o.get("conf") is None else "%.2f" % float(o["conf"])))
        f = _font(18)
        if f is not None:
            from PIL import Image, ImageDraw
            pim = Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB))
            dr = ImageDraw.Draw(pim)
            dr.rectangle([x1, max(0, y1 - 22), x1 + 11 * len(tag) + 8, y1], fill=(0, 0, 0))
            dr.text((x1 + 4, max(0, y1 - 21)), tag, font=f, fill=(0, 255, 0))
            out = cv2.cvtColor(np.array(pim), cv2.COLOR_RGB2BGR)
        else:
            cv2.putText(out, "#%d" % (i + 1), (x1 + 3, y1 + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, c, 2)
    return out


def run_batch(cams, push_overlay=False, send_w=SEND_W) -> dict:
    stamp = time.strftime("%m%d_%H%M%S")
    outdir = OUTROOT / ("batch_" + stamp)
    outdir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=max(1, len(cams))) as ex:      # 6 路并行(网络等待型)
        recs = list(ex.map(lambda c: annotate(c, outdir, send_w), cams))
    dt = time.time() - t0
    summ = {"batch": stamp, "dir": str(outdir), "ts": time.strftime("%F %T"),
            "n_cams": len(cams), "ok": sum(1 for r in recs if r.get("ok")),
            "n_objects": sum(r.get("n_obj") or 0 for r in recs),
            "elapsed_s": round(dt, 1), "model": (recs[0].get("model") if recs else None),
            "cams": [{"cam": r["cam"], "ok": r.get("ok"), "scene": r.get("scene"),
                      "n_obj": r.get("n_obj"), "latency_s": r.get("latency_s"), "err": r.get("err")}
                     for r in recs]}
    (outdir / "summary.json").write_text(json.dumps(summ, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(OUTROOT / "annotations.jsonl", "a", encoding="utf-8") as f:  # 追加式数据集
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    if push_overlay:
        _push_overlay(recs)
    print(json.dumps(summ, ensure_ascii=False, indent=1))
    return summ


def _push_overlay(recs):
    """把某一路的框写进场景叠加规格(origin=vlm) —— 复用既有 scene_overlay 规格, 不覆盖仿真/检测框"""
    try:
        import scene_overlay as SO
        r = next((x for x in recs if x["cam"] == "arm" and x.get("ok")), None)
        if not r:
            return
        spec = SO.load_spec()
        boxes = [{"label": o["label"], "bbox": o["bbox"], "conf": o.get("conf"), "origin": "vlm"}
                 for o in r["objects"]]
        spec["vlm"] = {"cam": "arm", "ts": r["ts"], "boxes": boxes, "scene": r.get("scene")}
        SO.save_spec(spec)
        print("  ✅ 已写场景叠加规格(vlm 类, %d 框)" % len(boxes))
    except Exception as e:                                              # noqa: BLE001
        print("  ⚠️ 写叠加规格失败: %s: %s" % (type(e).__name__, str(e)[:120]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cams", default=",".join(CAMS), help="逗号分隔; 默认 6 路全跑")
    ap.add_argument("--watch", type=int, default=0, help="秒; >0 则常驻每 N 秒一批")
    ap.add_argument("--push-overlay", action="store_true")
    ap.add_argument("--send-w", type=int, default=SEND_W)
    a = ap.parse_args()
    cams = [c.strip() for c in a.cams.split(",") if c.strip()]
    if a.watch > 0:
        print("🤖 自动标注常驻: 每 %ds 一批(%s)" % (a.watch, ",".join(cams)), flush=True)
        while True:
            try:
                run_batch(cams, a.push_overlay, a.send_w)
            except Exception as e:                                      # noqa: BLE001
                print("批次失败: %s: %s" % (type(e).__name__, str(e)[:160]), flush=True)
            time.sleep(a.watch)
    run_batch(cams, a.push_overlay, a.send_w)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
