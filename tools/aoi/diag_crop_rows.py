"""看清 v4 当前裁剪图的"纵向成分": 逐行 金覆盖/亮度/梯度/周期性, 判定哪几行是"金手指"、哪几行是"厚边沿"
并给出两个候选切法 (只留焊盘排 / 焊盘排+实心带) 的行界
"""
import cv2
import numpy as np
import sys

sys.path.insert(0, "/home/ubuntu/aoi_v4")
from gf_template import build_template
from gf_metric import gold_mask
from gf_crop import GoldFingerCropper

REF = "/home/ubuntu/aoi_v4/imgs/Finger_Image_W2448_H2048_No_8.png"
tpl, meta = build_template(REF, verbose=False)
cr = GoldFingerCropper(tpl, canonical_w=1600, canonical_h=220, margin_x=0.03, margin_y=0.04,
                       preserve_aspect=True)
im = cv2.imread(REF)
crop, info = cr.crop(im)
print(f"当前裁剪 {crop.shape[1]}x{crop.shape[0]}  条={info['strip']}  角度={info['angle']}")
g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
m = cv2.inRange(hsv, np.array([8, 60, 50]), np.array([45, 255, 255])) > 0
gx = np.abs(cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3))
gy = np.abs(cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3))
print(f"\n{'row':>4}{'金覆盖%':>9}{'中间列金%':>10}{'亮度均':>8}{'亮度p95':>8}{'|gx|':>7}{'|gy|':>7}  判读")
for y in range(0, crop.shape[0], 1):
    cov = m[y].mean() * 100
    mid = m[y, 200:1400].mean() * 100 if crop.shape[1] > 1400 else cov
    lum = g[y].mean(); p95 = np.percentile(g[y], 95)
    tag = ""
    if lum > 100:
        tag = "← 亮(本体反光?)"
    elif cov > 85:
        tag = "← 实心金带?"
    elif 25 < cov < 90 and gx[y].mean() > 18:
        tag = "← 焊盘(离散, 边缘多)?"
    if y % 2 == 0 or tag:
        print(f"{y:>4}{cov:>9.1f}{mid:>10.1f}{lum:>8.1f}{p95:>8.1f}{gx[y].mean():>7.1f}{gy[y].mean():>7.1f}  {tag}")
