#!/usr/bin/env python3
"""笔记本内置摄像头 驱动/取帧 自检 (老倪: "内置摄像头能驱动起来么")

做四件事 (全部留证据):
  ① 枚举 /dev/video* 的 v4l2 格式能力 (ffmpeg -list_formats)
  ② 逐个设备抓 1 帧 → 存 /tmp/cam_videoN.jpg, 报尺寸/均值/是否全黑
  ③ 抓 3 秒视频 → /tmp/cam_videoN.mp4, 报实际帧数/fps
  ④ 画面变化检测: 连抓 4 帧比差值 (>0 = 真在出画面, 不是冻结帧)
用法: python3 tools/webcam_selftest.py
"""
import os
import subprocess
import sys
import time

import numpy as np

try:
    import cv2
except Exception as e:                                                  # noqa: BLE001
    print(f"需要 cv2: {e}")
    sys.exit(1)

DEVS = [f"/dev/video{i}" for i in range(4)]
print("=== ① 设备格式能力 (ffmpeg -list_formats) ===")
for d in DEVS:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-f", "v4l2", "-list_formats", "all", "-i", d],
                       capture_output=True, text=True)
    out = (r.stdout + r.stderr).splitlines()
    print(f"\n--- {d} ---")
    for ln in out:
        if "Raw" in ln or "Compressed" in ln or "Cannot" in ln or "No such" in ln or "error" in ln.lower():
            print("   ", ln.strip()[:150])

print("\n=== ② 逐设备抓 1 帧 ===")
works = []
for d in DEVS:
    jpg = f"/tmp/cam_{os.path.basename(d)}.jpg"
    if os.path.exists(jpg):
        os.remove(jpg)
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "v4l2",
                        "-i", d, "-frames:v", "1", "-y", jpg],
                       capture_output=True, text=True, timeout=30)
    if not os.path.exists(jpg):
        print(f"  {d}: ❌ 取帧失败 ({r.stderr.strip().splitlines()[-1][:90] if r.stderr.strip() else '无输出'})")
        continue
    img = cv2.imread(jpg)
    if img is None:
        print(f"  {d}: ❌ 文件读不了")
        continue
    h, w = img.shape[:2]
    mean = float(img.mean())
    std = float(img.std())
    ok = mean > 3 and std > 2
    print(f"  {d}: ✅ {w}x{h} 均值 {mean:.1f} 方差 {std:.1f} → {'有画面' if ok else '⚠️ 全黑/无画面'}"
          f"  存 {jpg}")
    if ok:
        works.append(d)

if not works:
    print("\n没有可用设备")
    sys.exit(1)

dev = works[0]
print(f"\n=== ③ 用 {dev} 抓 3 秒视频 ===")
mp4 = "/tmp/cam_test.mp4"
subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "v4l2", "-i", dev,
                "-t", "3", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-y", mp4], capture_output=True, text=True, timeout=60)
if os.path.exists(mp4):
    cap = cv2.VideoCapture(mp4)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    print(f"  {mp4}: {n} 帧 · {fps:.1f} fps · {w}x{h}")
else:
    print("  视频抓取失败")

print("\n=== ④ 画面变化检测 (连抓 4 帧) ===")
cap = cv2.VideoCapture(dev)
if not cap.isOpened():
    print("  ❌ cv2 打不开设备")
    sys.exit(1)
frames = []
t0 = time.time()
for _ in range(40):
    ok, f = cap.read()
    if ok:
        frames.append(f)
    if len(frames) >= 8 and time.time() - t0 > 2.0:
        break
cap.release()
print(f"  cv2 取到 {len(frames)} 帧 / {time.time() - t0:.1f}s")
if len(frames) >= 2:
    ds = [float(np.abs(frames[i].astype(int) - frames[i + 1].astype(int)).mean())
          for i in range(min(4, len(frames) - 1))]
    print(f"  相邻帧平均差 {[round(x, 2) for x in ds]} → "
          f"{'✅ 实时出画面' if max(ds) > 0.2 else '⚠️ 画面几乎不变(可能是静态场景/被遮挡)'}")
    cv2.imwrite("/tmp/cam_cv2_frame.png", frames[-1])
    print(f"  cv2 最新帧存 /tmp/cam_cv2_frame.png ({frames[-1].shape[1]}x{frames[-1].shape[0]})")
print("\n可用设备:", works)
