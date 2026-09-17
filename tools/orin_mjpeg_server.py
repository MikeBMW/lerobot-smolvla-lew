#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""orin_mjpeg_server.py — Orin 侧 MJPEG 转发 (给人眼实时看真机相机画面)

场景 (老倪 2026-09-17): 「右键 YOLO 目标检测节点 → 打开输入图像, 我要实时看到当前接入的
原始视频流, 确认现在是否能拿到 RealSense 相机的图像」。

为什么需要: D405 物理接在 **Orin** 上, 控制台跑在 4060 → 4060 本地拿不到像素;
ROS 侧又没有驱动 (realsense2_camera 未装, /realsense/* Publisher=0) → 只能走 **UVC 直读 + 转发**。

纪律 (与 Orin 红线一致):
  · **临时进程, 不常驻/不自启**: 由控制台右键菜单按需拉起, 客户端断开或超时(默认 900s)自动退出;
  · 只读相机, 不发布 ROS 话题, 不碰机器人栈; 只在本机 0.0.0.0:<port> 提供 MJPEG (局域网内网段)。
  · 启动时打印设备身份 (sysfs: 内核名/VID:PID/序列号) → 界面上能看到"这确实是那台 D405"。

用法 (在 Orin 上):
  python3 orin_mjpeg_server.py --device 2 --port 8791 --max-seconds 900
客户端: GET http://<orin-ip>:8791/stream  (multipart/x-mixed-replace JPEG) · /?stop=1 立即停
"""
import argparse
import os
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np

STOP = threading.Event()
LAST_CLIENT = time.time()
STATS = {"frames": 0, "fps": 0.0, "w": 0, "h": 0, "device": "?"}


def device_identity(dev: int) -> dict:
    info = {}
    try:
        info["kernel_name"] = open(f"/sys/class/video4linux/video{dev}/name").read().strip()
    except Exception:                                                      # noqa: BLE001
        info["kernel_name"] = "?"
    cur = os.path.realpath(f"/sys/class/video4linux/video{dev}")
    for _ in range(12):
        up = os.path.dirname(cur)
        if up in ("", "/"):
            break
        cur = up
        if os.path.isfile(os.path.join(cur, "idVendor")):
            for k in ("idVendor", "idProduct", "serial", "product"):
                f = os.path.join(cur, k)
                if os.path.isfile(f):
                    try:
                        info[k] = open(f).read().strip()
                    except Exception:                                      # noqa: BLE001
                        pass
            break
    return info


class Cam:
    def __init__(self, dev: int, w: int, h: int, fps: float):
        self.cap = cv2.VideoCapture(dev, cv2.CAP_V4L2)
        if not self.cap.isOpened():
            raise RuntimeError(f"/dev/video{dev} 打不开 (被占用?)")
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
        self.cap.set(cv2.CAP_PROP_FPS, fps)
        self.period = 1.0 / max(1.0, fps)
        self.jpeg = None
        self.lock = threading.Lock()
        self._stop = False
        for _ in range(3):
            self.cap.read()

    def loop(self):
        t_prev, n = time.time(), 0
        while not self._stop and not STOP.is_set():
            t0 = time.time()
            ok, fr = self.cap.read()
            if ok:
                STATS["w"], STATS["h"] = fr.shape[1], fr.shape[0]
                ok_j, buf = cv2.imencode(".jpg", fr, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                if ok_j:
                    with self.lock:
                        self.jpeg = buf.tobytes()
                    STATS["frames"] += 1
                    n += 1
            if n and time.time() - t_prev >= 1.0:
                STATS["fps"] = round(n / (time.time() - t_prev), 1)
                n, t_prev = 0, time.time()
            dt = self.period - (time.time() - t0)
            if dt > 0:
                time.sleep(dt)
        try:
            self.cap.release()
        except Exception:                                                  # noqa: BLE001
            pass

    def frame(self):
        with self.lock:
            return self.jpeg


class Handler(BaseHTTPRequestHandler):
    cam: Cam = None

    def log_message(self, *a):                                              # 静音
        pass

    def do_GET(self):                                                       # noqa: N802
        global LAST_CLIENT
        LAST_CLIENT = time.time()
        if "stop=1" in self.path:
            STOP.set()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"stopping\n")
            return
        if self.path.startswith("/status"):
            body = (f"device={STATS['device']} {STATS['w']}x{STATS['h']} "
                    f"fps={STATS['fps']} frames={STATS['frames']}").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()
        while not STOP.is_set():
            j = self.cam.frame()
            if j is None:
                time.sleep(0.02)
                continue
            try:
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                 + str(len(j)).encode() + b"\r\n\r\n" + j + b"\r\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return                    # 客户端关窗 → 结束这次流 (进程按 idle 规则退出)
            LAST_CLIENT = time.time()
            time.sleep(0.02)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", type=int, default=2)
    ap.add_argument("--port", type=int, default=8791)
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--fps", type=float, default=15.0)
    ap.add_argument("--max-seconds", type=float, default=900.0, help="兜底自毁时间 (默认 900s)")
    ap.add_argument("--idle-seconds", type=float, default=15.0, help="无客户端多久后自动退出")
    a = ap.parse_args()
    ident = device_identity(a.device)
    STATS["device"] = f"/dev/video{a.device} {ident.get('kernel_name','?')} " \
                      f"{ident.get('idVendor','?')}:{ident.get('idProduct','?')} sn={ident.get('serial','?')}"
    print("[orin-mjpeg] 设备:", STATS["device"], flush=True)
    cam = Cam(a.device, a.width, a.height, a.fps)
    Handler.cam = cam
    threading.Thread(target=cam.loop, daemon=True).start()
    srv = ThreadingHTTPServer(("0.0.0.0", a.port), Handler)
    host = socket.gethostname()
    print(f"[orin-mjpeg] 就绪: http://{host}:{a.port}/stream  (status=/status, 停止=/?stop=1)", flush=True)
    t0 = time.time()
    while not STOP.is_set():
        if time.time() - t0 > a.max_seconds:
            print(f"[orin-mjpeg] 到达兜底时限 {a.max_seconds:.0f}s → 退出", flush=True)
            break
        if time.time() - LAST_CLIENT > a.idle_seconds:
            print(f"[orin-mjpeg] 无客户端 {a.idle_seconds:.0f}s → 退出 (临时进程不常驻)", flush=True)
            break
        time.sleep(0.5)
    STOP.set()
    threading.Thread(target=srv.shutdown, daemon=True).start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
