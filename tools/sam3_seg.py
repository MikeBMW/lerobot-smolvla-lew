#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""🧩 开放词汇分割 (SAM3 · 分割 anything) —— **调用方**(CLI + 常驻服务 + 叠加规格 + 取证图)

算法内核在包里: `src/lerobot/policies/sam3_seg/` (与 policies/yolo_3d 同级 —— 感知前端统一在 policies/ 下,
策略(动作) 与 感知(状态输入) 同层级; 老倪 2026-09-29 纠正后归位)。
本文件只做四件"调用方"的事:
  ① CLI: 单图/单帧分割 · 能力体检(--bench 报实测显存与延迟) ② 常驻服务(--serve, 独立进程 ⇒ 显存独占)
  ③ 写叠加规格(--write-spec → origin='seg', 与 sim/vlm/det 并存) ④ 取证图(掩膜+轮廓+真值带)

分层口径 (别越层):
  · **L2 能力**: 一帧图 + 概念提示词(文本/框/点) → 该概念的**所有实例掩膜**(像素级) + 框 + 分数。
  · **L5 意图**: 概念短语由 L5(VLM/人/工单)给 —— 本件不自己编概念。
  · **不进 L3/L4**: 不产动作、不编排技能序列、不预测不规划。

用法:
  python tools/sam3_seg.py --cam local --text "光模块" --out reports/seg_local.png
  python tools/sam3_seg.py --image /path/frame.jpg --text "screwdriver" --text "cable"
  python tools/sam3_seg.py --cam arm --text "光模块" --write-spec --cam-name arm
  python tools/sam3_seg.py --bench 5 --text "光模块"
  python tools/sam3_seg.py --serve --port 8796
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))

from lerobot.policies.sam3_seg import (                             # noqa: E402
    MIN_AREA_PX, SAM3_DIR, SAM3_SIZE, grab_frame, mask_3d, mask_to_polys, read_image,
)
from lerobot.policies.sam3_seg.segmenter import DEFAULT as SEG      # 单例(懒加载)

SPEC_PATH = ROOT / "data" / "scene" / "overlay_spec.json"
SAM3_DTYPE = SEG.dtype_name


def load_model(verbose: bool = True):
    """兼容旧调用: 返回 (model, proc)"""
    SEG.ensure(verbose=verbose)
    return SEG.model, SEG.proc


def unload_model():
    return SEG.unload()


def segment(img_bgr, texts, threshold: float = 0.5, mask_threshold: float = 0.5,
            boxes=None, box_labels=None):
    return SEG.segment(img_bgr, texts, threshold, mask_threshold, boxes, box_labels)


# ──────────────────────────────────────────────────────────────────────────
# 叠加规格写入 (origin='seg' · kind='mask' · 按 origin 合并, 不动别家)
# ──────────────────────────────────────────────────────────────────────────
def write_spec_boxes(instances: list, cam: str, img_wh, texts: list, ms: float, meta_note: str = "") -> dict:
    from scene_overlay import load_spec, merge_origin, save_spec
    boxes = []
    for it in instances:
        polys = it.get("polys") or []
        if not polys:
            continue
        b = {"origin": "seg", "label": it.get("label", "?"), "kind": "mask",
             "polys": polys, "area_px": it.get("area_px"),
             "conf": round(float(it["score"]), 4) if it.get("score") is not None else None,
             "img_wh": list(img_wh)}
        if it.get("box3d"):
            b["box3d"] = it["box3d"]
        if it.get("c3d"):
            b["c3d"] = it["c3d"]
        boxes.append(b)
    spec = load_spec()
    spec = merge_origin(spec, cam, "seg", boxes, meta={
        "model": "facebook/sam3 (镜像权重, transformers Sam3Model)",
        "texts": texts, "n": len(boxes), "ms": round(ms, 1),
        "at": time.strftime("%Y-%m-%d %H:%M:%S"), "note": meta_note,
        "src": "src/lerobot/policies/sam3_seg (调用方 tools/sam3_seg.py)"})
    save_spec(spec)
    return {"n_written": len(boxes), "cam": cam, "spec": str(SPEC_PATH)}


# ──────────────────────────────────────────────────────────────────────────
# 取证图 (掩膜+轮廓+标签+真值带, 与叠加页同一套配色语义)
# ──────────────────────────────────────────────────────────────────────────
def render(img_bgr: np.ndarray, seg: dict, alpha: float = 0.35) -> np.ndarray:
    """取证图: 概念配色 + 质心序号 + 图例块 + 真值带。

    2026-09-29 目检复核(像素级)抓到 4 处硬伤, 这里逐条修:
      ① 真值带最后画 ⇒ 把顶排标签的上半截抹掉(实测只剩 5/14 行墨迹) ⇒ 真值带改为**先画**, 标签另起一层
      ② 浮动标签互相叠(1c 叠 2 处 / 3c 叠 4 处+, 6 倍放大仍读不出分数) ⇒ 改为「质心序号 + 图例块」,
         结构上不可能叠: 掩膜上只画小序号, 文字全部收进左侧图例
      ③ 配色按**实例序号**取(同图所有概念都落在同族蓝, 分不出 green connector 与 slot) ⇒ 按**概念**取色
      ④ slot 出现 15581px 实例(占画幅 57%, 把整个托盘圈进去)却和 617px 的单槽实例同列, 一格自相矛盾
         ⇒ 超过画幅 20% 的实例画**点线**并在图例标 "⚠ 面积过大(疑似过分割)"
    """
    import cv2
    out = img_bgr.copy()
    H, W = out.shape[0], out.shape[1]
    PALETTE = [(255, 80, 80), (80, 255, 120), (80, 170, 255), (255, 200, 60),
               (210, 90, 255), (60, 230, 230), (255, 140, 0), (150, 255, 80)]
    # 名实一致(2026-09-29 目检: "green connector" 被画成蓝色 ⇒ 一眼就被质疑):
    # 概念名里写了颜色词, 就用那个颜色; 否则按出现顺序取调色板。
    NAMED = [("green", (80, 220, 80)), ("red", (80, 80, 255)), ("blue", (255, 120, 60)),
             ("yellow", (60, 220, 240)), ("orange", (40, 150, 255)), ("purple", (230, 90, 200)),
             ("gray", (170, 170, 170)), ("grey", (170, 170, 170)), ("black", (60, 60, 60)),
             ("white", (235, 235, 235))]
    concepts: list = []
    for _it in seg["instances"]:
        _c = _it.get("label") or "?"
        if _c not in concepts:
            concepts.append(_c)
    ccol, _used = {}, []
    for i, c in enumerate(concepts):
        col = next((v for k, v in NAMED if k in c.lower()), None)
        if col is None or col in _used:
            col = next((x for x in PALETTE[i:] + PALETTE[:i] if x not in _used), PALETTE[i % len(PALETTE)])
        _used.append(col)
        ccol[c] = col
    MAX_AREA_PCT = 0.03          # 3%(640x480=9216px)。20% 这个阈值在这张画幅上**永远不会触发**(目检指出)
    big_idx = set()
    _allm = np.zeros((H, W), bool)          # 掩膜联合位图(选图例位置时判"遮了多少真目标")
    lay = out.copy()
    for i, it in enumerate(seg["instances"]):
        col = ccol[it.get("label") or "?"]
        _allm |= it["mask"].astype(bool)
        lay[it["mask"]] = col
        _big = it["area_px"] > MAX_AREA_PCT * (H * W)
        if _big:
            big_idx.add(i)
            for p in mask_to_polys(it["mask"]):            # 点线: 一眼看出"这块可疑"
                pts = np.asarray(p, np.int32)
                for a, b in zip(pts, np.roll(pts, -1, axis=0)):
                    if int(a[0] + a[1]) % 9 < 5:
                        cv2.line(out, tuple(int(v) for v in a), tuple(int(v) for v in b), col, 2, cv2.LINE_AA)
        else:
            for p in mask_to_polys(it["mask"]):
                cv2.polylines(out, [np.asarray(p, np.int32)], True, col, 2, cv2.LINE_AA)
        lay[it["mask"]] = col
        for p in mask_to_polys(it["mask"]):
            cv2.polylines(out, [np.asarray(p, np.int32)], True, col, 2)
    out = cv2.addWeighted(lay, alpha, out, 1 - alpha, 0)
    # ① 真值带**先画**(老倪会把画面当结果 ⇒ 状态必须标在画面上; 后画会压掉标签)
    bar = "SAM3 %s · %.0fms · %d 实例 · 概念=%s · %s" % (
        SEG.dtype_name, seg["ms"], len(seg["instances"]),
        ",".join(seg["texts"]) or "(无文本提示)", time.strftime("%H:%M:%S"))
    cv2.rectangle(out, (0, 0), (W, 26), (18, 18, 18), -1)
    cv2.putText(out, bar, (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (120, 255, 160), 1, cv2.LINE_AA)

    # ② 图例几何(先算): 文字全部收进左侧图例块 ⇒ 不再有浮动标签互相压字
    show = sorted(range(len(seg["instances"])), key=lambda i: -seg["instances"][i]["area_px"])[:12]
    lines = []
    for i in sorted(show):
        it = seg["instances"][i]
        flag = "  ⚠ 面积%d%%(疑似过分割)" % round(100.0 * it["area_px"] / (H * W)) if i in big_idx else ""
        lines.append((ccol[it.get("label") or "?"], "%2d %-16s %.2f %5dpx%s"
                      % (i + 1, (it.get("label") or "?"), it["score"] or 0, it["area_px"], flag)))
    if len(seg["instances"]) > len(show):
        lines.append(((200, 200, 200), "   …共 %d 个实例(只列面积最大的 12 个)" % len(seg["instances"])))
    wid = hei = 0
    if lines:
        wid = min(max(cv2.getTextSize(t, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)[0][0] for _c, t in lines) + 14, W - 8)
        hei = 6 + 16 * len(lines) + 4
    # 图例放"掩膜最少"的那个角(遮得最少), 而不是一律左上
    _LG = None
    if lines:
        _cand = [(4, 30), (max(4, W - wid - 4), 30),
                 (4, max(30, H - hei - 4)), (max(4, W - wid - 4), max(30, H - hei - 4))]
        _ov = {}
        _tot = float(H * W)
        for (gx, gy) in _cand:
            sub = _allm[gy:gy + hei, gx:gx + wid]
            n = int(sub.sum()) if sub.size else int(_tot)
            _ov[(gx, gy)] = n
        gx, gy = min(_ov, key=_ov.get)
        _LG = (gx, gy, gx + wid, gy + hei)

    # ③ 质心序号徽标(结构上不可能叠: 掩膜上只有一个小圆+数字; 且避让图例块 + 彼此不贴)
    _placed: list = []
    for i, it in enumerate(seg["instances"]):
        col = ccol[it.get("label") or "?"]
        m = it["mask"].astype(np.uint8)
        mm = cv2.moments(m, binaryImage=True)
        if mm["m00"] > 0:
            cx, cy = int(mm["m10"] / mm["m00"]), int(mm["m01"] / mm["m00"])
        else:
            x0, y0, x1, y1 = [int(v) for v in it["box_xyxy"]]
            cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        cx, cy = min(max(12, cx), W - 12), min(max(34, cy), H - 12)
        if _LG and _LG[0] - 6 <= cx <= _LG[2] + 6 and _LG[1] - 6 <= cy <= _LG[3] + 6:
            cx = min(_LG[2] + 16, W - 12)
        for _k in range(24):            # 与已放徽标保持 >= 24px(直径 20 + 间隙), 挤不下就下移一行
            if all((cx - px) ** 2 + (cy - py) ** 2 >= 24 ** 2 for px, py in _placed):
                break
            cy = cy + 26 if cy + 26 <= H - 12 else max(34, cy - 26)
            if _LG and _LG[0] - 6 <= cx <= _LG[2] + 6:      # 下移后可能又落进图例, 往右让开
                cx = min(_LG[2] + 16, W - 12)
        _placed.append((cx, cy))
        cv2.circle(out, (cx, cy), 10, (12, 12, 12), -1)
        cv2.circle(out, (cx, cy), 10, col, 2, cv2.LINE_AA)
        _n = str(i + 1)
        (nw, nh), _ = cv2.getTextSize(_n, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        cv2.putText(out, _n, (cx - nw // 2, cy + nh // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.45, col, 1, cv2.LINE_AA)

    # ④ 画图例块
    if lines:
        # 图例半透明(0.72) —— 目检: 不透明块把掩膜切掉、实例 7 完全看不见 ⇒ 取证不完整
        x0g, y0g = _LG[0], _LG[1]
        roi = out[y0g:_LG[3], x0g:_LG[2]]
        if roi.size:
            roi[:] = (roi * 0.28 + np.array([12, 12, 12], dtype=roi.dtype) * 0.72).astype(roi.dtype)
        cv2.rectangle(out, (x0g, y0g), (_LG[2], _LG[3]), (90, 90, 90), 1)
        for k, (col, t) in enumerate(lines):
            cv2.putText(out, t, (_LG[0] + 8, _LG[1] + 16 * (k + 1)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, col, 1, cv2.LINE_AA)
    return out


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────
def cmd_bench(n: int, texts: list[str], cam: str) -> int:
    import torch
    img, src = grab_frame(cam)
    if img is None:
        print("❌ %s" % src)
        return 1
    print("帧源: %s" % src)
    t0 = time.time()
    seg = segment(img, texts)
    cold = time.time() - t0
    print("冷启动(含加载): %.1fs   其中模型加载 %.1fs" % (cold, SEG.load_s or -1))
    ts = []
    last = seg
    for _ in range(n):
        last = segment(img, texts)
        ts.append(last["ms"])
    ts = np.asarray(ts)
    print("热推理 %d 次: 中位 %.0fms · 最小 %.0f · 最大 %.0f · 实例数 %d" % (
        n, np.median(ts), ts.min(), ts.max(), len(last["instances"])))
    if SEG.device == "cuda":
        print("显存: 前向峰值 %.2f GB / 卡共 %.2f GB" % (
            torch.cuda.max_memory_allocated() / 1e9, torch.cuda.get_device_properties(0).total_memory / 1e9))
    for it in last["instances"]:
        print("   实例: %-14s score=%.3f area=%dpx box=%s polys=%d" % (
            it["label"], it["score"] or 0, it["area_px"], [round(v) for v in it["box_xyxy"]],
            len(mask_to_polys(it["mask"]))))
    return 0


def cmd_segment(a) -> int:
    if a.image:
        img, src = read_image(a.image), a.image
    else:
        img, src = grab_frame(a.cam, a.port, a.path or "")
    if img is None:
        print("❌ %s" % src)
        return 1
    print("帧源: %s" % src)
    seg = segment(img, a.text, threshold=a.threshold, mask_threshold=a.mask_threshold)
    print("SAM3: %.0fms · 实例 %d 个 · 概念=%s" % (seg["ms"], len(seg["instances"]), a.text))

    out_inst = []
    for it in seg["instances"]:
        polys = mask_to_polys(it["mask"])
        rec = {"label": it["label"], "score": it["score"], "area_px": it["area_px"],
               "box_xyxy": it["box_xyxy"], "polys": polys, "n_polys": len(polys)}
        if a.three_d:
            d3 = mask_3d(it["mask"], a.cam)
            rec["c3d"] = d3
            print("   %-12s score=%.3f area=%-6d 3D=%s" % (
                it["label"], it["score"] or 0, it["area_px"],
                ("中心 base=(%.3f, %.3f, %.3f) z=%.0fmm 尺寸=%.1fx%.1fmm yaw=%.1f°" % (
                    d3["center_base"][0], d3["center_base"][1], d3["center_base"][2],
                    d3["z_mm"], d3["xy_size_mm"][0], d3["xy_size_mm"][1], d3["yaw_deg"]))
                if d3.get("ok") else "拒答: %s" % d3.get("reason")))
        else:
            print("   %-12s score=%.3f area=%-6d polys=%d" % (it["label"], it["score"] or 0, it["area_px"], len(polys)))
        out_inst.append(rec)

    if a.out:
        import cv2
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(a.out, render(img, seg))
        print("已存分割图: %s" % a.out)
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps({
            "src": src, "texts": a.text, "ms": seg["ms"], "size": seg["size"],
            "model_dir": SAM3_DIR, "dtype": SEG.dtype_name, "instances": out_inst},
            ensure_ascii=False, indent=1))
        print("已存 JSON: %s" % a.json)
    if a.write_spec:
        r = write_spec_boxes([dict(it, polys=mask_to_polys(it["mask"])) for it in seg["instances"]],
                             a.cam_name or a.cam, seg["size"], a.text, seg["ms"], a.note or "")
        print("已写入叠加规格: origin=seg · %d 个掩膜元素 → %s" % (r["n_written"], r["spec"]))
    return 0


def cmd_serve(a) -> int:
    """常驻分割服务 (stdlib http.server; 独立进程 ⇒ 显存独占, 与推流/GUI 解耦)"""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    if a.lazy:
        # --lazy: 常驻但不预载 —— 起来时显存 0, 第一次 POST /seg 才加载(1.3s)。
        # 理由: 系统里模型按需加载(老倪: GPU 不许空转), 但服务要 24h 在(画布节点/页面按钮随时可用)
        print("[sam3] --lazy: 暂不预载权重, 首次调用时加载 (显存 0 起步)")
    else:
        load_model(verbose=True)

    # ── GET /status/all 支撑 (状态聚合; 逻辑在 src/lerobot/engineering/status_hub.py) ──
    SERVED = {"n": 0, "last_ts": 0.0}                 # /seg 真实调用计数 (供 /health 与 inferring 探针读)
    _hub: dict = {"mod": None}

    def _status_hub():
        if _hub["mod"] is None:
            from lerobot.engineering import status_hub as _sh
            _sh.start()                                  # 后台 1s 刷新快照 ⇒ 请求只读缓存
            _hub["mod"] = _sh
        return _hub["mod"]

    def _status_fallback(e):
        """status_hub 不可用时的降级契约 (字段齐全, 绝不 500)。"""
        return {"ts": time.time(),
                "hw": {"gpu": {"util": 0, "mem_used_mb": 0, "mem_total_mb": 0, "temp_c": 0, "name": "unknown"},
                       "cpu": {"util": 0, "cores": 0, "load1": 0.0},
                       "mem": {"used_gb": 0.0, "total_gb": 0.0},
                       "disk": {"used_gb": 0, "total_gb": 0, "pct": 0}},
                "models": [], "training": {"active": False, "layer": "", "name": "", "version": "",
                                           "step": 0, "total": 0, "pct": 0, "eta_s": 0,
                                           "speed_s_per_step": 0.0},
                "assets": [], "err": "status_hub: %s: %s" % (type(e).__name__, str(e)[:160])}

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _send(self, code: int, obj):
            b = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def log_message(self, *args):                                        # 静音(别刷屏)
            pass

        def do_GET(self):
            if self.path.startswith("/status/all"):
                # 状态聚合 (硬件/模型/训练/3DGS 资产) —— 只读快照(<50ms), 不碰分割链路
                try:
                    self._send(200, _status_hub().snapshot())
                except Exception as e:                                       # noqa: BLE001
                    self._send(200, _status_fallback(e))                     # 降级也必须 200, 绝不 500
                return
            import torch
            if self.path.startswith("/health"):
                vram = (torch.cuda.memory_allocated() / 1e9) if torch.cuda.is_available() else 0
                self._send(200, {"ok": True, "model_dir": SAM3_DIR, "loaded": SEG.model is not None,
                                 "dtype": SEG.dtype_name, "size": SAM3_SIZE, "vram_gb": round(vram, 2),
                                 "load_s": SEG.load_s, "min_area_px": MIN_AREA_PX,
                                 "served": SERVED["n"], "last_serve_ts": SERVED["last_ts"]})
            else:
                self._send(404, {"ok": False, "err": "只有 GET /health, GET /status/all 与 POST /seg"})

        def do_POST(self):
            if not self.path.startswith("/seg"):
                self._send(404, {"ok": False, "err": "unknown"})
                return
            n = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(n) or b"{}")
            try:
                if req.get("image_path"):
                    img, src = read_image(req["image_path"]), req["image_path"]
                elif req.get("image_b64"):
                    import base64 as _b64
                    import cv2
                    raw = _b64.b64decode(req["image_b64"])
                    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
                    src = "b64(%dB)" % len(raw)
                else:
                    img, src = grab_frame(req.get("cam", "local"), int(req.get("port", 8791)))
                if img is None:
                    self._send(503, {"ok": False, "err": src})
                    return
                cam = req.get("cam", "local")
                seg = segment(img, req.get("texts") or [], threshold=float(req.get("threshold", 0.5)),
                              mask_threshold=float(req.get("mask_threshold", 0.5)),
                              boxes=req.get("boxes"), box_labels=req.get("box_labels"))
                SERVED["n"] += 1                     # 真实分割调用计数 (inferring 探针的真源)
                SERVED["last_ts"] = time.time()
                out = []
                for it in seg["instances"]:
                    d3 = mask_3d(it["mask"], cam) if req.get("three_d") and cam == "arm" else None
                    out.append({"label": it["label"], "score": it["score"], "area_px": it["area_px"],
                                "box_xyxy": it["box_xyxy"], "polys": mask_to_polys(it["mask"]), "c3d": d3})
                if req.get("write_spec"):
                    write_spec_boxes(out, req.get("cam_name") or req.get("cam", "arm"), seg["size"],
                                     req.get("texts") or [], seg["ms"], req.get("note", ""))
                self._send(200, {"ok": True, "src": src, "ms": round(seg["ms"], 1), "count": len(out),
                                 "instances": out, "size": seg["size"]})
            except Exception as e:                                            # noqa: BLE001
                import traceback
                self._send(500, {"ok": False, "err": "%s: %s" % (type(e).__name__, str(e)[:200]),
                                 "tb": traceback.format_exc()[-800:]})

    srv = ThreadingHTTPServer(("127.0.0.1", a.port), H)
    try:                                                       # 预热状态聚合缓存 (首个 /status/all 也 <50ms)
        _status_hub()
    except Exception as e:                                     # noqa: BLE001
        print("[sam3] status_hub 预热失败(不影响 /health /seg): %s: %s" % (type(e).__name__, e))
    print("[sam3] 分割服务已起: http://127.0.0.1:%d  (GET /health · GET /status/all · POST /seg {cam|image_path|image_b64, texts[]})" % a.port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[sam3] 退出")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="SAM3 开放词汇分割 (L2 感知原语; 算法在 src/lerobot/policies/sam3_seg)")
    ap.add_argument("--image", default="", help="图片路径(不给就 --cam 从推流服务抓帧)")
    ap.add_argument("--cam", default="local", help="相机源 arm|local|local2")
    ap.add_argument("--cam-name", default="", help="写规格时用的相机名(默认同 --cam)")
    ap.add_argument("--path", default="", help="自定义取帧端点(默认 snapshot/<cam>.jpg)")
    ap.add_argument("--port", type=int, default=8791, help="推流服务端口")
    ap.add_argument("--text", action="append", default=[], help="概念提示词(可多次; 中文/英文)")
    ap.add_argument("--threshold", type=float, default=0.5, help="实例分数阈")
    ap.add_argument("--mask-threshold", type=float, default=0.5, help="掩膜二值阈")
    ap.add_argument("--three-d", action="store_true", help="掩膜→base 3D(仅臂上相机; 缺深度/手眼/TCP 就如实拒答)")
    ap.add_argument("--out", default="", help="分割图输出路径")
    ap.add_argument("--json", default="", help="结果 JSON 输出路径")
    ap.add_argument("--write-spec", action="store_true", help="写入 overlay_spec.json(origin=seg)")
    ap.add_argument("--note", default="", help="规格 meta 备注")
    ap.add_argument("--bench", type=int, default=0, help="跑 N 次热推理并报实测(显存/延迟)")
    ap.add_argument("--serve", action="store_true", help="起常驻服务")
    ap.add_argument("--lazy", action="store_true", help="配合 --serve: 不预载权重(显存 0), 首次调用才加载")
    a = ap.parse_args()
    if a.serve:
        return cmd_serve(a)
    if a.bench:
        return cmd_bench(a.bench, a.text, a.cam)
    if not a.text and not a.image:
        ap.print_help()
        return 0
    return cmd_segment(a)


if __name__ == "__main__":
    raise SystemExit(main())