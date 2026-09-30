"""金手指条"纵向边界"精细剖面 —— 修 framing(上面少/下面多一条大边沿)用
逐行给出: 金像素数(宽阈值/严阈值) · 平均亮度 · 梯度能量 · 左右两端的分位宽度
"""
import cv2
import numpy as np
import sys

P = sys.argv[1] if len(sys.argv) > 1 else "/home/ubuntu/aoi_v4/imgs/Finger_Image_W2448_H2048_No_8.png"
Y0, Y1 = 1060, 1330
im = cv2.imread(P)[Y0:Y1]
hsv = cv2.cvtColor(im, cv2.COLOR_BGR2HSV)
wide = cv2.inRange(hsv, np.array([8, 60, 50]), np.array([45, 255, 255])) > 0
tight = cv2.inRange(hsv, np.array([12, 110, 110]), np.array([40, 255, 255])) > 0
g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
grad = cv2.magnitude(gx, gy)

print(f"图: {P.split('/')[-1]}  行区间 y={Y0}..{Y1}  (图宽 {im.shape[1]})")
print(f"{'y':>6}{'金宽阈':>8}{'金严阈':>8}{'亮度':>7}{'梯度':>7}   剖面 (金宽阈/亮度, 每行一根)")
for i in range(0, im.shape[0], 4):
    y = Y0 + i
    band = slice(i, min(i + 4, im.shape[0]))
    wc = int(wide[band].sum())
    tc = int(tight[band].sum())
    lum = float(g[band].mean())
    gr = float(grad[band].mean())
    bar_w = "#" * int(wc / (im.shape[1] * 4) * 120)
    bar_l = "=" * int(max(0, lum - 20) / 235 * 60)
    print(f"{y:>6}{wc:>8}{tc:>8}{lum:>7.1f}{gr:>7.1f}   {bar_w}|{bar_l}")

print("\n=== 关键拐点判读 (逐行细看 1180..1320) ===")
print(f"{'y':>6}{'金宽阈':>8}{'亮度':>7}{'梯度':>7}")
for y in range(max(0, 1180 - Y0), min(im.shape[0], 1320 - Y0), 6):
    print(f"{Y0+y:>6}{int(wide[y].sum()):>8}{g[y].mean():>7.1f}{grad[y].mean():>7.1f}")
