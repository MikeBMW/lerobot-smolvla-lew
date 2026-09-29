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

★ 出框之前，必须先在 topology 字段里做**拓扑 + 投影**推理（这是硬要求，不许跳过）:
1) 拓扑: 料盘/托盘的槽位在画面里会形成**线族**（同一槽的两条长边、相邻槽的边，方向一致）。
   说明目标物体**嵌在哪个槽位**（slot 编号/描述），并指出该槽边线的**方向**。
2) 投影: 世界系里互相平行的线，在图像里**交于同一消失点**。
   因此「嵌在槽里的模块，其长轴必然与所在槽的长轴平行」⇒ 图像上模块长轴的角度应当**与该槽边线角度一致**（都指向同一消失点）。
3) 自检修角: 算出 `axis_dev_deg = 模块长轴角度 − 槽边线角度`；
   **若 |axis_dev_deg| > 3°，先把框的角度修正到与槽边线一致，再输出**。
   槽位边线之间也互相平行，可用这条规律交叉验证，不要相信单条局部边缘。

只输出一个 JSON（不要 markdown 代码块，不要任何解释文字），格式:
{{"topology":"槽位结构与平行边族的描述(30字内)","slot":"目标所在的槽位","slot_angle_deg":槽边线角度,"objects":[{{"label":"光模块","bbox":[x1,y1,x2,y2],"conf":0.85,"obj_axis_deg":物体长轴角度,"axis_dev_deg":与槽边线偏差,"why":"依据(10字内)"}}],"scene":"一句话描述当前场景"}}

可用的 label: 光模块、扫码枪、插槽/托盘槽位、夹爪、标定板、托盘、线缆、手、其它
视角提示: 相机装在机械臂末端，画面可能是倒置的（装反了），物体朝画面中心。
"""


def call_vlm(jpg_bytes: bytes, w: int, h: int, timeout: int = 300,
             prompt: str | None = None) -> dict:
    """调一次视觉语言大模型。
    prompt=None ⇒ 用模块自带的场景理解词(PROMPT, 含 {W}/{H} 占位);
    传入自定义 prompt ⇒ 原样使用(不 format, 免得 JSON 花括号被吃掉)。
    """
    b64 = base64.b64encode(jpg_bytes).decode()
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": PROMPT.format(W=w, H=h) if prompt is None else prompt},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}},
        ]}],
        "max_tokens": MAXTOK, "temperature": 0.2,
    }
    req = urllib.request.Request(API, data=json.dumps(body).encode(),
                                 headers={"Authorization": "Bearer " + key(),
                                          "Content-Type": "application/json"}, method="POST")
    t0 = time.time()
    # 🐛 2026-09-29 修 (L5 闭环 ①annotate 阶段实测 4/6 路整路丢失):
    #   实测 summary: 6 路里 4 路 err="HTTPError: HTTP Error 503: Service Unavailable"
    #   → 同一批标注只剩 2 路有效 → 监督数据缺口 → 下游 L2/L3/L4 训练数据不完整。
    #   根因: 云端视觉档会**瞬时限流/过载** (503/429), 原来一次不成就整路放弃。
    #   现按"可重试传输错误"重试 (5xx/429/超时/URLError), 指数退避 + 抖动;
    #   非可重试的 4xx (如 400 请求体错/401 鉴权) 立即抛出, 不掩盖真错。
    #   次数可用 ZMAX_VLM_RETRY 覆盖 (默认 4 次); 0 或 1 = 关掉重试 (回到旧行为)。
    import random as _rnd
    from urllib.error import HTTPError as _HTTPError, URLError as _URLError
    _tries = max(1, int(os.environ.get("ZMAX_VLM_RETRY", "4") or 4))
    _last = None
    for _i in range(_tries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read().decode() or "{}")
            msg = ((d.get("choices") or [{}])[0].get("message") or {})
            txt = (msg.get("content") or "").strip()
            # 200 但 content 空 = 已知瞬态 (与 max_tokens 不足同症状) → 也重试
            if not txt and _i < _tries - 1:
                _last = RuntimeError("content 空 (200)")
                time.sleep(min(30.0, 5.0 * (2 ** _i)) + _rnd.uniform(0, 2))
                continue
            return {"txt": txt, "reasoning": msg.get("reasoning_content") or "",
                    "model": d.get("model"), "usage": d.get("usage"), "latency_s": time.time() - t0,
                    "attempts": _i + 1}
        except _HTTPError as _e:
            _code = int(getattr(_e, "code", 0) or 0)
            _last = _e
            if _code and not (_code >= 500 or _code == 429):
                raise                                  # 4xx (非限流) = 真错, 不重试不掩盖
        except (_URLError, TimeoutError, OSError) as _e:
            _last = _e
        if _i < _tries - 1:
            time.sleep(min(30.0, 5.0 * (2 ** _i)) + _rnd.uniform(0, 2))
    raise _last if _last is not None else RuntimeError("call_vlm 失败")


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


def build_prompt(w: int, h: int, hint: str = "", negatives=None, keep=None) -> str:
    """场景理解词 + 操作者现场指示 (老倪 2026-09-28: 「我可以通过提示词跟你互动, 指导你标注的方向」)。

    · hint: 操作者用自然语言给的标注方向(最高优先级), 原样进提示词, 不做解释替换
    · negatives: 已被操作者删除的 label ⇒ 明确要求不要重复给(否则删了又冒出来)
    · keep: 操作者认为对的 label ⇒ 保持同一套口径
    """
    p = PROMPT.format(W=w, H=h)
    extra = []
    if (hint or "").strip():
        extra.append("【操作者现场指示（最高优先级，必须遵守；与上面默认口径冲突时以本节为准）】\n"
                     + hint.strip())
    if negatives:
        extra.append("【操作者已删除、判定为错的标注 —— 不要再给出这些】：" + "、".join(sorted(set(negatives))))
    if keep:
        extra.append("【操作者保留、认为正确的标注 —— 请沿用同样口径】：" + "、".join(sorted(set(keep))))
    if extra:
        p = p + "\n" + "\n".join(extra) + "\n"
    return p


def main_cli(cam: str = "arm", path: str = "", dry: bool = False,
             hint: str = "", negatives=None, keep=None) -> str:
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

    prompt = build_prompt(W, H, hint=hint, negatives=negatives, keep=keep)
    r = call_vlm(raw, W, H, prompt=prompt)
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
        "usage": r["usage"], "at": time.strftime("%H:%M:%S"), "cam": cam,
        # 互动可追溯: 这一轮用的现场指示与被排除项都记下来(页面上直接显示)
        "hint": (hint or "").strip()[:300], "negatives": sorted(set(negatives or [])),
        "keep": sorted(set(keep or []))})
    spec["source"] = "L5 大模型理解 (%s)" % r["model"]
    spec["scene"] = (d.get("scene") or "")[:200]
    SO.save_spec(spec)
    return ("L5 大模型: %d 框 (原文 %d 个) · %.0fs%s · %s"
            % (len(boxes), len(objs), r["latency_s"],
               (" · 带指示「%s…」" % (hint or "").strip()[:20]) if (hint or "").strip() else "",
               spec.get("scene", "")[:60]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cam", default="arm", choices=["arm", "local", "local2"])  # 🎥 2026-09-27 三相机
    ap.add_argument("--frame", default="", help="用指定图（缺省取视频流实帧）")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--hint", default="", help="操作者现场指示(自然语言), 进提示词最高优先级段")
    ap.add_argument("--negatives", default="", help="要排除的 label(逗号分隔), 来自操作者删除的框")
    a = ap.parse_args()
    print("  " + main_cli(a.cam, a.frame, a.dry, hint=a.hint,
                          negatives=[s for s in (a.negatives or "").split(",") if s.strip()]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
