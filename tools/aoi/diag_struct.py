"""金手指区结构放大: 看"上排离散焊盘"和"下部实心金带"到底各是什么 (决定裁剪该含哪些行)"""
import cv2
import numpy as np
import sys

P = sys.argv[1] if len(sys.argv) > 1 else "/home/ubuntu/aoi_v4/imgs/Finger_Image_W2448_H2048_No_8.png"
X0, X1, Y0, Y1 = int(sys.argv[2]) if len(sys.argv) > 2 else 880, int(sys.argv[3]) if len(sys.argv) > 3 else 1420, 1075, 1285
im = cv2.imread(P)
sub = im[Y0:Y1, X0:X1]
g = cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY)
hsv = cv2.cvtColor(sub, cv2.COLOR_BGR2HSV)
m = cv2.inRange(hsv, np.array([8, 60, 50]), np.array([45, 255, 255]))

def amap(a, cols=110, rows=42, thresh=None, label=""):
    s = cv2.resize(a.astype(np.float32), (cols, rows), interpolation=cv2.INTER_AREA)
    lo, hi = float(s.min()), float(s.max())
    print(f"\n--- {label} | 原区 x[{X0},{X1}] y[{Y0},{Y1}] = {X1-X0}x{Y1-Y0}px → {cols}x{rows} 格 "
          f"(1格≈{int((X1-X0)/cols)}x{int((Y1-Y0)/rows)}px) 值域 {lo:.0f}..{hi:.0f} ---")
    print("      " + "".join(str((X0 + i * (X1 - X0) // cols) // 100 % 10) for i in range(cols)))
    RAMP = " .:-=+*#%@"
    for r in range(rows):
        y = Y0 + int(r * (Y1 - Y0) / rows)
        row = ""
        for c in range(cols):
            v = (s[r, c] - lo) / max(hi - lo, 1e-6)
            if thresh is not None and s[r, c] < thresh:
                row += " "
            else:
                row += RAMP[min(9, int(v * 9))]
        print(f"{y:5d} {row}")

amap(g, label="亮度")
amap(m, label="金色掩膜(>50 才画)", thresh=50)
# 每列金像素数 → 看是否周期性(焊盘)还是实心
col = (m > 0).sum(axis=0)
print("\n金像素列剖面(每32列一个数, 看周期性):")
for x in range(0, len(col), 32):
    print(f"  x={X0+x:5d} {int(col[x:x+32].mean()):4d} {'#'*int(col[x:x+32].mean()/2)}")
