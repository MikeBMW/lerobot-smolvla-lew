# -*- coding: utf-8 -*-
"""sim→real 域差取证: 仿真训练的 YOLO 权重直接在真机 D405 帧上跑, 看还能不能检出。

对照: 同权重在**训练分布内**(metaworld 渲染帧)的表现 (control)。
真机帧 = Orin D405 UVC 直读 (/dev/video2, /dev/video4), 自然朝向。
测试 4 种 rot90 (训练数据是 rot90(k=2), 真机朝向未知 → 逐个试, 用检出数说话)。

用法: DISPLAY=:0 gui-venv311/bin/python <本文件>
"""
import glob
import os

import cv2
import numpy as np
from ultralytics import YOLO

ROOT = "/home/ubuntu/lerobot-smolvla-lew"
W = os.path.join(ROOT, "runs/detect/outputs/yolo_peg/peg_v1/weights/best.pt")
DW = os.path.join(ROOT, "outputs/yolo_peg_depth/peg_depth_v1-2/weights/best.pt")
REAL = sorted(glob.glob("/home/ubuntu/zmax_data/real_cam/orin_d405/*.jpg"))
SIM = sorted(glob.glob(os.path.join(ROOT, "data/yolo_peg_depth/images/*.png")))[:4]

print(f"权重: {os.path.basename(W)} ({os.path.getsize(W)/1e6:.1f}MB)")
m = YOLO(W)
print("类别:", m.model.names)


def run(img_rgb, tag, rots=(0, 1, 2, 3)):
    out = {}
    for k in rots:
        im = np.rot90(img_rgb, k=k) if k else img_rgb
        bgr = cv2.cvtColor(np.ascontiguousarray(im), cv2.COLOR_RGB2BGR)
        r = m.predict(bgr, conf=0.25, verbose=False)[0]
        cls = [r.names[int(b.cls)] for b in r.boxes]
        conf = [float(b.conf[0]) for b in r.boxes]
        out[k] = (len(cls), dict(zip(cls, [round(c, 2) for c in conf])))
    best = max(out.items(), key=lambda kv: (kv[1][0], max(kv[1][1].values()) if kv[1][1] else 0))
    print(f"{tag:34s} " + " | ".join(f"rot{k*90}°:{v[0]}框{v[1] if v[1] else ''}" for k, v in out.items())
          + f"  → 最佳 rot{best[0]*90}°")
    return out


print("\n── 对照组: 训练分布内 (metaworld 渲染, 已 rot90 存盘) ──")
for p in SIM:
    a = np.asarray(cv2.cvtColor(cv2.imread(p), cv2.COLOR_BGR2RGB))
    run(a, f"SIM {os.path.basename(p)}", rots=(0,))

print("\n── 真机 D405 (Orin UVC) ──")
tot = 0
for p in REAL:
    a = np.asarray(cv2.cvtColor(cv2.imread(p), cv2.COLOR_BGR2RGB))
    o = run(a, f"REAL {os.path.basename(p)}")
    tot += max(v[0] for v in o.values())
print(f"\n真机帧 {len(REAL)} 张, 最佳朝向检出总数 = {tot} (对照组说明模型本身没坏)")

# 存一张标注图 (最佳朝向下) 供目检
for p in REAL[:2]:
    a = np.asarray(cv2.cvtColor(cv2.imread(p), cv2.COLOR_BGR2RGB))
    r = m.predict(cv2.cvtColor(np.ascontiguousarray(a), cv2.COLOR_RGB2BGR), conf=0.15, verbose=False)[0]
    outp = f"/home/ubuntu/zmax_data/real_cam/orin_d405/annot_{os.path.basename(p)}"
    cv2.imwrite(outp, r.plot())
    print(f"标注图 (conf0.15): {outp}")
