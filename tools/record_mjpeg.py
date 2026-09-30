#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
录 MJPEG 流 → MP4（按实测帧率写入，播放速度=真实速度）
用法: record_mjpeg.py <url> <out.mp4> <秒数>
"""
import signal
import sys
import time
import urllib.request

import cv2
import numpy as np

BOUNDARY = b"--zmaxframe"
_STOP = {"v": False}


def _on_sig(signum, frame):
    """收到停止信号 → 结束采集循环，让文件正常写完（否则 pkill 会丢掉整个视频）"""
    _STOP["v"] = True


signal.signal(signal.SIGTERM, _on_sig)
signal.signal(signal.SIGINT, _on_sig)


def frames_from_mjpeg(url: str, seconds: float):
    """解析 multipart/x-mixed-replace，按 Content-Length 切 JPEG 帧"""
    req = urllib.request.Request(url, headers={"User-Agent": "zmax-rec"})
    resp = urllib.request.urlopen(req, timeout=15)
    buf = b""
    t0 = time.time()
    while time.time() - t0 < seconds and not _STOP["v"]:
        chunk = resp.read(8192)
        if not chunk:
            break
        buf += chunk
        while True:
            i = buf.find(BOUNDARY)
            if i < 0:
                break
            j = buf.find(b"\r\n\r\n", i)
            if j < 0:
                break
            head = buf[i:j].decode("latin-1", "replace")
            clen = None
            for line in head.split("\r\n"):
                if line.lower().startswith("content-length:"):
                    clen = int(line.split(":", 1)[1].strip())
            if clen is None:
                buf = buf[j + 4:]
                continue
            start = j + 4
            end = start + clen
            if len(buf) < end:
                break
            jpg = buf[start:end]
            buf = buf[end:]
            img = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
            if img is not None:
                yield img, time.time()
    try:
        resp.close()
    except Exception:
        pass


def main():
    url, out, secs = sys.argv[1], sys.argv[2], float(sys.argv[3])
    label = sys.argv[4] if len(sys.argv) > 4 else "CAM"
    print(f"录制 {url} → {out} ({secs}s) …", flush=True)
    imgs, ts = [], []
    for img, t in frames_from_mjpeg(url, secs):
        imgs.append(img)
        ts.append(t)
    n = len(imgs)
    if n < 2:
        print(f"  ❌ 只收到 {n} 帧，录不成", flush=True)
        return 1
    span = ts[-1] - ts[0]
    fps = (n - 1) / span if span > 0 else 1.0
    fps = max(0.5, min(fps, 60.0))
    t_end = ts[-1]
    h, w = imgs[0].shape[:2]
    # 标注：相机名 / 采集时刻 / 帧龄 / 分辨率 · 帧率
    for i, im in enumerate(imgs):
        if im.shape[:2] != (h, w):
            im = cv2.resize(im, (w, h))
        bar = np.full((46, w, 3), 22, np.uint8)
        im = np.vstack([bar, im])
        cv2.putText(im, f"{label}  {w}x{h}  {fps:.2f}fps", (8, 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (120, 255, 160), 1, cv2.LINE_AA)
        cv2.putText(im,
                    time.strftime("%H:%M:%S", time.localtime(ts[i]))
                    + f".{int((ts[i] % 1) * 10)}  帧龄{max(0.0, t_end - ts[i]):.2f}s",
                    (8, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (160, 160, 175), 1, cv2.LINE_AA)
        imgs[i] = im
    h, w = imgs[0].shape[:2]
    vw = cv2.VideoWriter(out, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    for im in imgs:
        vw.write(im)
    vw.release()
    # 取证：平均亮度/对比度（判黑帧）
    g = cv2.cvtColor(imgs[len(imgs) // 2], cv2.COLOR_BGR2GRAY)
    import os
    print(f"  ✅ {n} 帧 · 实测 {fps:.2f} fps · {w}x{h} · {os.path.getsize(out)/1024:.0f}KB "
          f"· 中帧 std={g.std():.1f} 均值={g.mean():.1f}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
