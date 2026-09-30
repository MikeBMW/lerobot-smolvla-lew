"""金手指场景地形图 — 用 ASCII 图看清: 模块在哪、金手指条在哪、背景是什么"""
import cv2
import numpy as np
import sys

P = sys.argv[1] if len(sys.argv) > 1 else "/home/ubuntu/aoi_v4/imgs/Finger_Image_W2448_H2048_No_7.png"
im = cv2.imread(P)
h, w = im.shape[:2]
gray = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
hsv = cv2.cvtColor(im, cv2.COLOR_BGR2HSV)
print(f"图: {P.split('/')[-1]}  {w}x{h}")

RAMP = " .:-=+*#%@"

def amap(arr, cols=61, rows=30, lo=None, hi=None, label=""):
    """把图像降采样成 ASCII 图, 每格取均值"""
    small = cv2.resize(arr.astype(np.float32), (cols, rows), interpolation=cv2.INTER_AREA)
    lo = small.min() if lo is None else lo
    hi = small.max() if hi is None else hi
    span = max(hi - lo, 1e-6)
    print(f"\n--- {label} (x 0..{w}, y 0..{h}; 每格 {w//cols}x{h//rows}px; 范围 {lo:.0f}..{hi:.0f}) ---")
    print("    " + "".join(str((i * (w // cols) // 200) % 10) for i in range(cols)))
    for r in range(rows):
        line = "".join(RAMP[min(len(RAMP) - 1, int((small[r, c] - lo) / span * (len(RAMP) - 1)))] for c in range(cols))
        print(f"{int(r*rows and r*h/rows):4d}{line}")

amap(gray, label="亮度")

# 金色掩膜 (放宽阈值看全部金像素)
m = cv2.inRange(hsv, np.array([8, 60, 50]), np.array([45, 255, 255]))
print(f"\n金像素总数 {int(m.sum()/255)} = 全图 {m.mean()/255*100:.2f}%")
amap(m, label="金色掩膜")

# 所有够大的金块
cnts, _ = cv2.findContours(cv2.morphologyEx(m, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
cnts = sorted(cnts, key=cv2.contourArea, reverse=True)
print(f"\n金块数(面积>300): {sum(1 for c in cnts if cv2.contourArea(c) > 300)}")
for i, c in enumerate(cnts[:8]):
    a = cv2.contourArea(c)
    if a < 300:
        break
    (cx, cy), (rw, rh), ang = cv2.minAreaRect(c)
    x, y, bw, bh = cv2.boundingRect(c)
    print(f"  #{i+1} area={a:8.0f} 旋转框中心=({cx:6.0f},{cy:6.0f}) 尺寸=({rw:5.0f}x{rh:5.0f}) 角={ang:6.2f} | 轴对齐框 x[{x},{x+bw}] y[{y},{y+bh}]")

# 亮度最高的区域(可能是金手指受光面 / 白纸 / 光源)
th = np.percentile(gray, 99.5)
bm = (gray >= th).astype(np.uint8) * 255
amap(bm, label=f"最亮 0.5% 像素 (>{th:.0f})")
