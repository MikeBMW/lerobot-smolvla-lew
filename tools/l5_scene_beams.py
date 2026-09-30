#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
l5_scene_beams.py — L5(DeepSeek 视觉) 理解工位画面, 定位"横梁围成的内部空间"的像素边界。
老倪 2026-09-30: 「工位总览的笔记本摄像头, L5视觉语言大模型, 你先理解场景。在桌面上, 横梁与横梁是垂直的,
                 我需要定位桌子上面、横梁内部的空间位置, 给我画几条辅助水平线, 叠加到笔记本摄像头的画面上」

⚠ 实测教训 (2026-09-30): **长提示词 + 大 JSON 输出 ⇒ 思考链把 max_tokens(4000/8000) 全吃光** ⇒ 连续
   `finish=length` + 空 content。稳定口径 = 提示词 ~250 字 + 只输出 4 个数字的小 JSON + 走
   `gen_overlay_from_vlm.call_vlm`(与 vl_safety_monitor 同一条成熟通路, 含 5xx/429/超时重试)。
⚠ 口径: 模型给**语义 + 粗坐标**(当假设); 真正的线位置由像素取证 tools/laptop_beams_forensics.py 定。
用法: gui-venv311/bin/python tools/l5_scene_beams.py --img /tmp/local_raw.jpg --out /tmp/l5_beams.json
"""
import argparse, json, os, sys, time
import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gen_overlay_from_vlm as G        # noqa: E402  成熟封装: MODEL / MAXTOK / 重试 / parse_json

PROMPT = """这是产线工位的**笔记本相机**画面(全局固定视角, 看整个工位)。
现场事实: 桌面上方的**铝型材横梁彼此垂直**(竖直立柱与水平横梁成 90°)。
请定位"**桌子上面、由横梁围成的内部作业空间**"在**像素**上的边界。
只输出 JSON, 不要任何多余文字:
{"top_y": <int, 上方横梁下沿的 y>, "bottom_y": <int, 台面的 y>,
 "left_x": <int, 左侧立柱内沿 x>, "right_x": <int, 右侧立柱内沿 x>,
 "beams": "<一句话: 画面里哪几根是横梁, 哪根竖直哪根水平>", "confidence": "high|mid|low"}"""


def ask(jpg: bytes, w: int, h: int, tries: int = 3) -> dict:
    """走成熟封装; 空 content 时重试(语义=本次未给出结论, 不是'画面没东西')。"""
    last = None
    for i in range(tries):
        r = G.call_vlm(jpg, w, h, prompt=PROMPT, timeout=300)
        txt = (r.get("txt") or "").strip()
        print("[第%d次] %.1fs model=%s txt=%d字" % (i + 1, float(r.get("latency_s") or 0), r.get("model"), len(txt)), flush=True)
        if txt:
            return {"txt": txt, "model": r.get("model"), "latency_s": r.get("latency_s")}
        last = "空 content(API 侧偶发 / 思考链吃光)"
        print("       %s · raw=%s" % (last, str(r)[:160]), flush=True)
        time.sleep(2)
    return {"txt": "", "error": last}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--img", default="/tmp/local_raw.jpg")
    ap.add_argument("--out", default="/tmp/l5_beams.json")
    a = ap.parse_args()
    raw = open(a.img, "rb").read()
    im = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if im is None:
        raise SystemExit("✗ 读不出图 %s" % a.img)
    h, w = im.shape[:2]
    print("→ 送检 %s (%dx%d, %d B) · 提示词 %d 字 · max_tokens=%s" % (
        a.img, w, h, len(raw), len(PROMPT), getattr(G, "MAXTOK", "?")), flush=True)
    r = ask(raw, w, h)
    txt = r.get("txt", "")
    print("← %s" % (txt or "(空)"), flush=True)
    obj = G.parse_json(txt) if txt else None
    if obj:
        print("   解析: top_y=%s bottom_y=%s left_x=%s right_x=%s conf=%s" % (
            obj.get("top_y"), obj.get("bottom_y"), obj.get("left_x"), obj.get("right_x"), obj.get("confidence")))
        print("   beams: %s" % obj.get("beams"))
    json.dump({"raw_text": txt, "json": obj, "img": [w, h],
               "meta": {k: r.get(k) for k in ("model", "latency_s", "error")}},
              open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("已写出 %s" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
