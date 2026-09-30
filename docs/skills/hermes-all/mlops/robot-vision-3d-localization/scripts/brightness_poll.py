#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""brightness_poll.py — 相机身份判定 / 链路活性判定 (60s 亮度+md5+帧龄扫描)

用途 (两条, 都实测有效):
  ① **相机身份**: 让操作员用手遮住"他认为装着的那台相机" 20s。
     亮度 **明显掉下去**(实测 107.9 → 7.4) 再松开后回到原值 ⇒ 我们取图的**就是那台**;
     亮度基本不变 ⇒ 图来自**另一台相机**(现场常有多台: 法兰 D405 / 产线 UVC) ⇒ 换方案。
  ② **帧率/活性**: 每行打印 帧龄 + md5 + 亮度 ⇒ 一眼看出真实 fps(实测 ~0.53fps ≈ 2s 一张新图)
     与"文件在刷但内容不变"(md5 重复) 的情况。

用法:
  python3 brightness_poll.py [图片绝对路径] [扫描秒数]
默认图片: ~/zmax_ss_remote/cam_rs.png (Z-MAX 真机旁路帧)
依赖: opencv-python (cv2), 标准库
"""
import hashlib
import os
import sys
import time

import cv2

p = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else "~/zmax_ss_remote/cam_rs.png")
dur = float(sys.argv[2]) if len(sys.argv) > 2 else 60.0

print(f"扫描 {p}  ({dur:.0f}s)")
t0 = time.time()
rows = []
while time.time() - t0 < dur:
    try:
        b = open(p, "rb").read()
        h = hashlib.md5(b).hexdigest()[:8]
        a = cv2.imread(p, 0)
        lum = float(a.mean()) if a is not None else -1.0
        age = time.time() - os.path.getmtime(p)
        rows.append((time.time() - t0, lum, h, age))
        print("%5.1fs 亮度 %6.1f md5 %s 帧龄 %4.2f" % (rows[-1][0], lum, h, age), flush=True)
    except Exception as e:                                                     # noqa: BLE001
        print("%5.1fs 读失败 %s" % (time.time() - t0, e), flush=True)
    time.sleep(1.0)

if rows:
    lums = [r[1] for r in rows]
    hs = {r[2] for r in rows}
    print("\n小结: 亮度 min %.1f / max %.1f (差 %.1f) · 不同帧 %d 张 / %.0fs = %.2f fps"
          % (min(lums), max(lums), max(lums) - min(lums), len(hs), dur, len(hs) / dur))
    print("  亮度骤降再回升 ⇒ 遮的就是我们用的那台相机 ✓")
    print("  亮度基本不变 ⇒ 我们用的是另一台相机 ⇒ 靶标/方案要换")
    print("  不同帧数/秒 ≈ 真实 fps (慢相机别用时间判据配对, 用数值/内容一致性)")
