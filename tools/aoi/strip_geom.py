"""5 张真图: 金手指条(合并后)的定向矩形 + 倾角 + 尺寸一致性 → 决定模板与规范化尺寸
另外: 用长条形结构元把金手指焊盘"连成一条", 再取 minAreaRect (这才是金手指条的真几何)
"""
import cv2
import numpy as np
import glob
import os

D = "/home/ubuntu/aoi_v4/imgs"

def strip_rect(im, kx=61, ky=5, th=(8, 60, 50)):
    hsv = cv2.cvtColor(im, cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv, np.array(th[0:3]) * 0 + np.array([8, 60, 50]), np.array([45, 255, 255]))
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (kx, ky))
    mc = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k)
    cnts, _ = cv2.findContours(mc, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None, m, mc
    c = max(cnts, key=cv2.contourArea)
    rect = cv2.minAreaRect(c)
    (cx, cy), (w, h), ang = rect
    return ((cx, cy), (w, h), ang, cv2.contourArea(c), c), m, mc

print("=" * 100)
print("金手指条 (横向结构元合并后) 的几何 — 判据: 长边/短边/相对水平的倾角")
print("=" * 100)
rows = []
for p in sorted(glob.glob(os.path.join(D, "Finger_Image_*.png"))):
    im = cv2.imread(p)
    r, m, mc = strip_rect(im)
    name = os.path.basename(p)[-10:-4]
    if r is None:
        print(f"{name}: 无金块")
        continue
    (cx, cy), (w, h), ang, area, c = r
    # minAreaRect: angle∈[0,90); 长边 = max(w,h); 判断长边方向与水平的夹角
    long_side, short_side = (w, h) if w >= h else (h, w)
    # 若 w>=h: 长边沿 rect 的"宽"方向, 该方向相对水平转了 ang 度(顺时针为正, OpenCV 里为图像坐标)
    tilt = ang if w >= h else ang - 90.0
    tilt = ((tilt + 45) % 90) - 45          # 归一到 [-45,45)
    print(f"{name}: 中心=({cx:6.0f},{cy:6.0f}) 长边={long_side:6.0f} 短边={short_side:5.0f} "
          f"长宽比={long_side/max(short_side,1):5.2f} 相对水平倾角={tilt:6.2f}° 面积={area:8.0f} 金占比={m.mean()/255*100:5.2f}%")
    rows.append((name, cx, cy, long_side, short_side, tilt, area))

print()
print("=" * 100)
print("一致性统计 (决定: 模板法 + 规范化输出尺寸)")
print("=" * 100)
if rows:
    a = np.array([(r[1], r[2], r[3], r[4], r[5]) for r in rows])
    print(f"中心 x: 均值 {a[:,0].mean():7.1f} std {a[:,0].std():6.1f} | 中心 y: 均值 {a[:,1].mean():7.1f} std {a[:,1].std():6.1f}")
    print(f"长边:   均值 {a[:,2].mean():7.1f} std {a[:,2].std():6.1f} | 短边:   均值 {a[:,3].mean():7.1f} std {a[:,3].std():6.1f}")
    print(f"倾角:   均值 {a[:,4].mean():7.2f}° std {a[:,4].std():6.2f}°  范围 {a[:,4].min():.2f}..{a[:,4].max():.2f}°")
    print(f"→ 金手指条典型尺寸 ≈ {a[:,2].mean():.0f} x {a[:,3].mean():.0f} px (比例 {a[:,2].mean()/a[:,3].mean():.2f}:1)")
