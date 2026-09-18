#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ss_yolo_on_real.py — 真机图像 → L2 YOLO (光模块/夹爪/孔) 旁路检测 · 只出可视化, 零下行

老倪 2026-09-16: 「把 metaworld 的数据, 切换到真机的 realsense 图像数据, 调整接口, 对齐输入,
让当前的 L2 功能的 yolo 可以处理光模块。输出只能是旁路的可视化显示节点」

口径 (与 L2 现有链路对齐, 不另造一套):
  · 模型 = L2 已训权重 runs/detect/outputs/yolo_peg/peg_v1/weights/best.pt (classes: hand / peg / hole,
    **peg = 光模块**; imgsz=480, 训练域 = 仿真渲染图)
  · 输入对齐: 真机帧 (PNG, RGB) → **BGR** (ultralytics 内部用 BGR — 直接喂 RGB 会检不到, 2026-08-07 实测坑)
    → ultralytics 内部 letterbox 到 480 (尺寸/归一化不用手写)
  · 输出: 仅 ① 标注图 yolo_annotated.png ② detections JSON ③ 终端/心跳 —— **不发布任何 ROS 话题, 不调任何服务**
            供状态空间「旁路实时可视化」节点显示 = 唯一出口

用法:
  ~/lerobot-smolvla-lew/gui-venv311/bin/python tools/ss_yolo_on_real.py --auto          # 取最新真机帧
  ... --image data/yolo_peg/images/ep000_s000.png --source-kind sim                      # 指定图 (自检)
  ... --loop --interval 0.5                                                              # 常驻 (可视化跟帧)
"""
import argparse
import json
import os
import time

import numpy as np
from PIL import Image, ImageDraw

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REMOTE = os.environ.get("SS_REMOTE_DIR", os.path.expanduser("~/zmax_ss_remote"))
OUTDIR = os.environ.get("SS_BYPASS_DIR", os.path.expanduser("~/zmax_data/ss_bypass"))
WEIGHTS = os.environ.get("SS_YOLO_WEIGHTS") or next(
    (p for p in (os.path.join(REPO, "models/yolo_peg_live.pt"),                                  # 🎯 真机在役权重 (指针, 升级只改它)
                 os.path.join(REPO, "runs/detect/outputs/yolo_peg/peg_v1/weights/best.pt"))      # 旧仿真域权重 (兜底)
     if os.path.exists(p)),
    os.path.join(REPO, "runs/detect/outputs/yolo_peg/peg_v1/weights/best.pt"))
IMGSZ = int(os.environ.get("SS_YOLO_IMGSZ", "640"))
CONF = float(os.environ.get("SS_YOLO_CONF", "0.4"))
FRESH_S = float(os.environ.get("SS_IMG_FRESH_S", "5.0"))     # 真机帧新鲜窗口
CAND = ("cam_rs.png", "cam_fp.png", "cam_latest.png", "srv_cam.png", "srv_cam.jpg")   # RealSense 优先


def pick_frame():
    """最新真机帧 (RealSense 彩色优先); 返回 (path, age_s, kind)

    🩹 2026-09-18: 帧龄钳到非负 —— NTP 回拨导致 mtime 在未来时, age 为负会让
    "新鲜"判据恒真 (旧帧冒充实时). 帧仍是最新可比的一张, 故只钳龄 + 标 clock_skew.
    """
    best = None
    for i, name in enumerate(CAND):
        p = os.path.join(REMOTE, name)
        if os.path.exists(p):
            age = time.time() - os.path.getmtime(p)
            if age < -1.0:                       # 时钟回拨: 不按"新鲜"采信, 只标号
                age = 0.0
            if best is None or (i < best[2] and age <= FRESH_S * 4) or age < best[1] - 0.5:
                if age <= FRESH_S * 4:
                    best = (p, age, i)
    if best is None:
        return None, None, None
    return best[0], best[1], ("real" if best[1] <= FRESH_S else "stale")


_MODEL = None


def _model():
    """模型只加载一次 (2026-09-17 修: 原来每帧 YOLO(WEIGHTS) 重建 → 内存/显存抖动 + CPU 尖峰)"""
    global _MODEL
    if _MODEL is None:
        from ultralytics import YOLO
        _MODEL = YOLO(WEIGHTS)
        _MODEL.predict(np.zeros((IMGSZ, IMGSZ, 3), dtype=np.uint8), imgsz=IMGSZ, verbose=False)  # 预热
    return _MODEL


def run(image_path, source_kind="real", age=None, save=True):
    im = Image.open(image_path).convert("RGB")
    rgb = np.asarray(im)
    bgr = np.ascontiguousarray(rgb[:, :, ::-1])          # ⚠️ ultralytics 用 BGR
    res = _model().predict(bgr, imgsz=IMGSZ, conf=CONF, verbose=False)[0]
    names = res.names if isinstance(res.names, dict) else {i: n for i, n in enumerate(res.names)}
    dets = []
    for b in res.boxes:
        cls = int(b.cls[0])
        dets.append({"cls": names.get(cls, str(cls)), "conf": round(float(b.conf[0]), 3),
                     "xyxy": [round(float(v), 1) for v in b.xyxy[0].tolist()]})
    dets.sort(key=lambda d: -d["conf"])
    rec = {"t": time.time(), "image": os.path.basename(image_path), "source_kind": source_kind,
           "frame_age_s": (round(age, 2) if age is not None else None),
           "size": [im.width, im.height], "imgsz": IMGSZ, "conf_th": CONF, "weights": WEIGHTS,
           "detections": dets,
           "peg_optical_module": next((d for d in dets if d["cls"] == "peg"), None),
           "n": len(dets), "ros_publishers": 0, "scope": "bypass-visualization-only"}
    if save:
        dr = ImageDraw.Draw(im)
        for d in dets:
            x1, y1, x2, y2 = d["xyxy"]
            col = {"peg": (0, 255, 128), "hole": (255, 200, 0), "hand": (0, 160, 255)}.get(d["cls"], (255, 80, 80))
            dr.rectangle([x1, y1, x2, y2], outline=col, width=3)
            dr.text((x1 + 3, max(0, y1 - 14)), f"{d['cls']} {d['conf']:.2f}", fill=col)
        os.makedirs(OUTDIR, exist_ok=True)
        # 🛠 2026-09-18: 原子写 (tmp + os.replace) —— 读者 (面板/我/取证脚本) 可能正好撞上半张 PNG;
        #   与 Docker tap 落盘同一纪律 (实测: 复制时报 0 字节 = 正好读到截断瞬间)。
        _tmp = os.path.join(OUTDIR, f"yolo_annotated.png.tmp{os.getpid()}")
        im.save(_tmp, format="PNG")          # ⚠️ 必须显式给 format: PIL 按扩展名猜 → .tmp 会报 unknown file extension
        os.replace(_tmp, os.path.join(OUTDIR, "yolo_annotated.png"))
        json.dump(rec, open(os.path.join(OUTDIR, "yolo_detections.json"), "w"), ensure_ascii=False, indent=1)
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image")
    ap.add_argument("--auto", action="store_true", help="取最新真机帧")
    ap.add_argument("--source-kind", default="real", choices=["real", "stale", "sim", "test"])
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--interval", type=float, default=0.5)
    a = ap.parse_args()
    os.makedirs(OUTDIR, exist_ok=True)
    while True:
        img, age, kind = (a.image, None, a.source_kind) if a.image else pick_frame()
        if img is None:
            print("⚠️ 无真机图像帧 (RealSense 彩色话题发布者 0 / FoundationPose 空闲无帧) — "
                  "无法跑 L2 YOLO; 现场相机节点起来后本循环会自动出结果", flush=True)
            if not a.loop:
                return 2
            time.sleep(max(1.0, a.interval))
            continue
        try:
            rec = run(img, source_kind=(kind if not a.image else a.source_kind), age=age)
        except Exception as e:
            print(f"❌ YOLO 失败: {type(e).__name__}: {e}", flush=True)
            if not a.loop:
                return 3
            time.sleep(max(1.0, a.interval))
            continue
        peg = rec["peg_optical_module"]
        print(f"📷 {rec['image']} ({rec['source_kind']}, age={rec['frame_age_s']}s) {rec['size']} → "
              f"检出 {rec['n']}: " + (" · ".join(f"{d['cls']}={d['conf']}" for d in rec["detections"]) or "无")
              + (f"  ✅ 光模块(peg) conf={peg['conf']} box={peg['xyxy']}" if peg else "  ⚠️ 未检出光模块(peg)"),
              flush=True)
        if not a.loop:
            return 0
        time.sleep(max(0.05, a.interval))


if __name__ == "__main__":
    raise SystemExit(main())
