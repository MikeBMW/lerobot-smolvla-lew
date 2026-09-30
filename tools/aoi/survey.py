"""v4 设计前的地形勘察: 看真图里金手指在哪、歪多少、v3 固定矩形截出来的长什么样"""
import cv2
import numpy as np
import glob
import os

D = "/home/ubuntu/aoi_v4/imgs"

def gold_mask(bgr):
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv, np.array([10, 80, 60]), np.array([40, 255, 255]))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15)))
    return m

print("=" * 70)
print("A) 原始图 (Finger_Image_*): 尺寸 + 金手指掩膜几何 + 倾角")
print("=" * 70)
for p in sorted(glob.glob(os.path.join(D, "Finger_Image_*.png"))):
    im = cv2.imread(p)
    h, w = im.shape[:2]
    gray = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    m = gold_mask(im)
    frac = m.mean() / 255.0
    line = f"{os.path.basename(p)[-12:]} {w}x{h} mean_lum={gray.mean():6.1f} 金掩膜占比={frac*100:5.2f}%"
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if cnts:
        c = max(cnts, key=cv2.contourArea)
        rect = cv2.minAreaRect(c)
        (cx, cy), (rw, rh), ang = rect
        area = cv2.contourArea(c)
        line += f" | 最大块 area={area:8.0f} 中心=({cx:6.0f},{cy:6.0f}) 尺寸=({rw:5.0f}x{rh:5.0f}) 倾角={ang:6.2f}°"
    print(line)

print()
print("=" * 70)
print("B) v3 的 TopView 文件: 名字说 1600x220, 实际内容是什么")
print("=" * 70)
for p in sorted(glob.glob(os.path.join(D, "Finger_TopView_*.png"))):
    im = cv2.imread(p)
    if im is None:
        print(os.path.basename(p), "读不出")
        continue
    h, w = im.shape[:2]
    gray = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    m = gold_mask(im)
    # 找金区外接矩形(不旋转) → 判断是否轴对齐
    ys, xs = np.where(m > 0)
    bb = "无金像素"
    if len(xs):
        bb = f"金区外接矩形 x[{xs.min()},{xs.max()}] y[{ys.min()},{ys.max()}] 宽{xs.max()-xs.min()} 高{ys.max()-ys.min()}"
    print(f"{os.path.basename(p)[:28]} 实际={w}x{h} lum={gray.mean():6.1f} 金占比={m.mean()/255*100:5.2f}% {bb}")

print()
print("=" * 70)
print("C) v3 固定透视源矩形 [400,1000]-[2000,1250] 在真图里的位置/内容")
print("=" * 70)
for p in sorted(glob.glob(os.path.join(D, "Finger_Image_*.png")))[:3]:
    im = cv2.imread(p)
    crop = im[1000:1250, 400:2000]
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    m = gold_mask(crop)
    print(f"{os.path.basename(p)[-12:]} 固定窗 1600x250: lum={g.mean():6.1f} 金占比={m.mean()/255*100:5.2f}% "
          f"边缘列均值 std={g[:, :50].mean():.0f}/{g[:, -50:].mean():.0f}")
