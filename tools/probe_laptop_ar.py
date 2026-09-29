#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""笔记本相机(local) 能不能做 AR 底图: 机械臂可见吗? 绿锚存在吗? —— 纯实测取证, 不动任何东西。
做法: 连抓 N 帧 (间隔 0.6s), 逐帧两两做差 → 运动区域 = 机械臂所在; 同时统计高饱和绿像素。
"""
import time
import urllib.request

import cv2
import numpy as np

URL = "http://127.0.0.1:8791/snapshot/local.jpg"
N = 6


def grab():
    req = urllib.request.Request(URL + "?_=%f" % time.time())
    with urllib.request.urlopen(req, timeout=10) as r:
        b = r.read()
    a = np.frombuffer(b, np.uint8)
    return cv2.imdecode(a, cv2.IMREAD_COLOR)


frames = []
t0 = time.time()
for i in range(N):
    f = grab()
    frames.append(f)
    time.sleep(0.6)
print("抓帧 %d 张, 用时 %.1fs, shape=%s" % (len(frames), time.time() - t0, frames[0].shape))

# ① 帧间运动: 与第一帧比, 差>18 的像素
base = frames[0].astype(np.int16)
for i in range(1, len(frames)):
    d = np.abs(frames[i].astype(np.int16) - base).max(2)
    m = (d > 18).astype(np.uint8)
    n = int(m.sum())
    ys, xs = np.nonzero(m)
    bbox = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())) if n else None
    # 去掉零散噪点: 形态学开运算后的最大连通域
    k = np.ones((5, 5), np.uint8)
    mm = cv2.morphologyEx(m * 255, cv2.MORPH_OPEN, k)
    nl, lab, stats, cent = cv2.connectedComponentsWithStats(mm, 8)
    big = sorted(range(1, nl), key=lambda i: -stats[i, 4])[:3]
    cores = [("area=%d" % stats[i, 4], "bbox=%s" % list(stats[i, :4]), "cent=(%.0f,%.0f)" % tuple(cent[i])) for i in big]
    print("帧%d vs 帧0: 差异像素 %d (%.2f%%) bbox=%s | 最大连通域: %s" % (
        i, n, 100.0 * n / m.size, bbox, cores))

# ② 高饱和绿锚 (技能里的 绿拉环: G-R>25 且 G-B>20)
f = frames[-1]
b, g, r = f[:, :, 0].astype(np.int16), f[:, :, 1].astype(np.int16), f[:, :, 2].astype(np.int16)
green = ((g - r) > 25) & ((g - b) > 20) & (g > 60)
print("末帧高饱和绿像素: %d 个 (占比 %.3f%%)" % (int(green.sum()), 100.0 * green.sum() / green.size))
if green.sum():
    ys, xs = np.nonzero(green)
    print("   绿像素 bbox=(%d,%d,%d,%d)" % (xs.min(), ys.min(), xs.max(), ys.max()))

# ③ 亮/暗结构概览 (判断是不是能看到台面/治具)
gray = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
print("末帧灰度: mean=%.1f std=%.1f 最亮=%d 最暗=%d" % (gray.mean(), gray.std(), gray.max(), gray.min()))
h, w = gray.shape
for name, sub in (("上1/3", gray[:h // 3]), ("中1/3", gray[h // 3:2 * h // 3]), ("下1/3", gray[2 * h // 3:])):
    print("   %s mean=%.1f std=%.1f" % (name, sub.mean(), sub.std()))
cv2.imwrite("/tmp/laptop_ar_probe_last.jpg", f)
print("末帧存 /tmp/laptop_ar_probe_last.jpg")
