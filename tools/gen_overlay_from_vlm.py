#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_overlay_from_vlm.py — L5 大模型理解真实画面 → 边界框规格
════════════════════════════════════════════════════════
老倪需求: 「边界框的位置，需要大语言模型理解后，告诉渲染引擎叠加」

链路: 取当前实帧 → 送 L5 视觉大模型理解 → 按像素坐标回 JSON 框 → 写入规格
     (origin="vlm"，只替换 vlm 那一类，仿真/检测的框原样保留)

坑（已固化）:
  · DeepSeek 是**推理型**模型 → max_tokens 给不足时 content 为空（reasoning 吃光额度）
  · 必须要求**严格 JSON**，且明确像素口径/原点在左上，否则坐标量纲会漂
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scene_overlay as SO   # noqa: E402

ENV = os.path.expanduser("~/.hermes/.env")
API = "https://api.deepseek.com/chat/completions"
MODEL = os.environ.get("ZMAX_L5_VLM", "deepseek-v4-flash")   # 视觉档
MAXTOK = 9000


def key() -> str:
    k = os.environ.get("DEEPSEEK_API_KEY")
    if k:
        return k
    try:
        for ln in open(ENV, encoding="utf-8"):
            if ln.strip().startswith("DEEPSEEK_API_KEY="):
                return ln.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


PROMPT = """你是 Z-MAX 具身智能平台的 L5 视觉理解层。图是**真实机器人工作场景的一帧实拍**。

请理解这张图，找出场景里**可操作的目标物体**，给出它们的像素边界框，用于叠加到实时视频流上。

坐标系（必须严格遵守）:
· 图像尺寸 {W}×{H} 像素
· 原点在**左上角**，x 向右增大，y 向下增大
· bbox = [x1, y1, x2, y2]，全部是 0~{W} / 0~{H} 范围内的**整数**
· 只框你**确实看见**的物体；看不清就不要猜

只输出一个 JSON（不要 markdown 代码块，不要任何解释文字），格式:
{{"objects":[{{"label":"光模块","bbox":[x1,y1,x2,y2],"conf":0.85,"why":"依据(10字内)"}}],"scene":"一句话描述当前场景"}}

可用的 label: 光模块、扫码枪、插槽/托盘槽位、夹爪、标定板、托盘、线缆、手、其它
视角提示: 相机装在机械臂末端，画面可能是倒置的（装反了），物体朝画面中心。
"""


def call_vlm(jpg_bytes: bytes, w: int, h: int, timeout: int = 300) -> dict:
    b64 = base64.b64encode(jpg_bytes).decode()
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": PROMPT.format(W=w, H=h)},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}},
        ]}],
        "max_tokens": MAXTOK, "temperature": 0.2,
    }
    req = urllib.request.Request(API, data=json.dumps(body).encode(),
                                 headers={"Authorization": "Bearer " + key(),
                                          "Content-Type": "application/json"}, method="POST")
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode() or "{}")
    msg = ((d.get("choices") or [{}])[0].get("message") or {})
    txt = (msg.get("content") or "").strip()
    return {"txt": txt, "reasoning": msg.get("reasoning_content") or "",
            "model": d.get("model"), "usage": d.get("usage"), "latency_s": time.time() - t0}


def parse_json(txt: str) -> dict:
    """容错解析: 直接 json → 去代码块 → 抓第一个 {...}"""
    t = (txt or "").strip()
    cands = [t, re.sub(r"```(?:json)?", "", t).strip()]
    m = re.search(r"\{.*\}", t, re.S)
    if m:
        cands.append(m.group(0))
    for cand in cands:
        if not cand:
            continue
        try:
            d = json.loads(cand)
            if isinstance(d, dict):
                return d
        except Exception:
            continue
    return {}


def main_cli(cam: str = "arm", path: str = "", dry: bool = False) -> str:
    raw = SO.fetch_frame(cam, path=path)
    if not raw:
        return "✗ 取不到 %s 的实帧（视频流在跑吗？curl :8791/stats）" % cam
    import cv2
    import numpy as np
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return "✗ 帧解码失败"
    H, W = img.shape[:2]
    if dry:
        return "dry-run: 帧 %dx%d %d B · 模型 %s" % (W, H, len(raw), MODEL)

    r = call_vlm(raw, W, H)
    txt = r["txt"] or r["reasoning"]
    if not r["txt"]:
        return "✗ 大模型 content 为空（推理额度吃满）· model=%s · 用时%.0fs" % (r["model"], r["latency_s"])
    d = parse_json(txt)
    objs = d.get("objects") or []
    boxes = []
    for o in objs:
        b = o.get("bbox")
        if not (isinstance(b, (list, tuple)) and len(b) == 4):
            continue
        x1, y1, x2, y2 = [float(v) for v in b]
        # 强制落回画面内（大模型偶有越界/量纲漂移，明确拒绝而不是画到画外）
        x1, x2 = sorted((max(0.0, min(W - 1, x1)), max(0.0, min(W - 1, x2))))
        y1, y2 = sorted((max(0.0, min(H - 1, y1)), max(0.0, min(H - 1, y2))))
        if x2 - x1 < 3 or y2 - y1 < 3:
            continue
        boxes.append({"label": o.get("label", "?"), "origin": "vlm", "xyxy": [x1, y1, x2, y2],
                      "conf": o.get("conf"), "why": o.get("why", "")})
    spec = SO.load_spec()
    SO.merge_origin(spec, cam, "vlm", boxes, meta={
        "model": r["model"], "latency_s": round(r["latency_s"], 1), "n": len(boxes),
        "usage": r["usage"], "at": time.strftime("%H:%M:%S"), "cam": cam})
    spec["source"] = "L5 大模型理解 (%s)" % r["model"]
    spec["scene"] = (d.get("scene") or "")[:200]
    SO.save_spec(spec)
    return ("L5 大模型: %d 框 (原文 %d 个) · %.0fs · %s"
            % (len(boxes), len(objs), r["latency_s"], spec.get("scene", "")[:60]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cam", default="arm", choices=["arm", "local"])
    ap.add_argument("--frame", default="", help="用指定图（缺省取视频流实帧）")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    print("  " + main_cli(a.cam, a.frame, a.dry))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
