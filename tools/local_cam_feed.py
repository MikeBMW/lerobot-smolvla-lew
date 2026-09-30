#!/usr/bin/env python3
"""local_cam_feed.py — 本机工位相机(备用视角)取图小进程

背景: 产线 RealSense 未出帧时 (Orin 相机节点未跑), L2 YOLO 节点无输入图 → 面板空。
     本进程把本机 USB 相机 (video0) 的最新帧原子落盘为 `cam_local.png` + `cam_local.json`,
     由 ss_yolo_on_real.py 作为**明确标注的兜底源** (source_kind=bench_cam) 读取。

诚实纪律 (老倪: 面板禁假值 / 画面自身要标状态):
  · 落盘 JSON 写明 source/ts/res/mean/std, 供面板显示"来源 + 帧龄";
  · 绝不写进 cam_rs.png (那是产线 RealSense 的通道, 不许混源);
  · 产线帧一回来, ss_yolo_on_real 优先用 RealSense (CAND 顺序在前)。

用法: gui-venv311/bin/python tools/local_cam_feed.py [--interval 0.5] [--index 0] [--w 1280] [--h 720]
"""
from __future__ import annotations

import argparse
import json
import os
import time

OUT = os.path.expanduser("~/zmax_ss_remote")
PNG = os.path.join(OUT, "cam_local.png")
JSN = os.path.join(OUT, "cam_local.json")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", type=int, default=0)
    ap.add_argument("--interval", type=float, default=0.5)
    ap.add_argument("--w", type=int, default=1280)
    ap.add_argument("--h", type=int, default=720)
    ap.add_argument("--frames", type=int, default=0, help="0=无限循环")
    a = ap.parse_args()

    import cv2

    os.makedirs(OUT, exist_ok=True)
    cap = cv2.VideoCapture(a.index, cv2.CAP_V4L2)
    if not cap.isOpened():
        print(f"❌ 打不开相机 video{a.index}", flush=True)
        return 2
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, a.w)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, a.h)
    n = 0
    while True:
        ok, f = cap.read()
        if not ok or f is None:
            print("⚠️ 取帧失败, 重试", flush=True)
            time.sleep(1.0)
            continue
        tmp = PNG + f".tmp{os.getpid()}.png"     # ⚠️ 扩展名必须是图片格式: cv2 按扩展名猜编码器
        cv2.imwrite(tmp, f)
        os.replace(tmp, PNG)                      # 原子替换 (读者不会读到半张)
        json.dump({"source": f"bench_cam_video{a.index}", "path": PNG, "ts": time.time(),
                   "res": [int(f.shape[1]), int(f.shape[0])],
                   "mean": round(float(f.mean()), 1), "std": round(float(f.std()), 1),
                   "note": "本机工位相机(备用视角) — 非产线 RealSense"},
                  open(JSN, "w"), ensure_ascii=False)
        n += 1
        if n % 20 == 1:
            print(f"[feed] {n} 帧 · {f.shape} · mean={f.mean():.1f} std={f.std():.1f}", flush=True)
        if a.frames and n >= a.frames:
            break
        time.sleep(max(0.05, a.interval))
    cap.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
