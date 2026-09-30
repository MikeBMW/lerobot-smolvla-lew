"""诊断 No_8: 金手指条的掩膜几何到底是多少 (逐行/逐列剖面, 别再用"最大轮廓"糊弄)"""
import cv2
import numpy as np

P = "/home/ubuntu/aoi_v4/imgs/Finger_Image_W2448_H2048_No_8.png"
im = cv2.imread(P)
hsv = cv2.cvtColor(im, cv2.COLOR_BGR2HSV)

for lo, hi, name in [((8, 60, 50), (45, 255, 255), "宽阈值(8,60,50)-(45,255,255)"),
                     ((15, 120, 120), (35, 255, 255), "严阈值(金更纯)")]:
    m = cv2.inRange(hsv, np.array(lo), np.array(hi))
    print(f"\n=== {name}: 金像素 {int(m.sum()/255)} ===")
    for k in [(1, 1), (41, 5), (61, 5), (61, 15)]:
        mc = cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, k))
        cnts, _ = cv2.findContours(mc, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            print(f"   核{k}: 无轮廓")
            continue
        c = max(cnts, key=cv2.contourArea)
        x, y, w, hh = cv2.boundingRect(c)
        tot = cv2.boundingRect(cv2.findNonZero(mc)) if cv2.countNonZero(mc) else None
        print(f"   核{k}: 最大轮廓 bbox x[{x},{x+w}] y[{y},{y+hh}] = {w}x{hh} | 全掩膜bbox={tot}")

# 逐行剖面 (y 方向金像素数) —— 看条的真实上下边界
m = cv2.inRange(hsv, np.array([8, 60, 50]), np.array([45, 255, 255]))
rowc = (m > 0).sum(axis=1)
colc = (m > 0).sum(axis=0)
print("\n=== y 方向剖面 (每 16 行的金像素数, 只印有值的段) ===")
for y in range(0, m.shape[0], 16):
    v = rowc[y:y + 16].sum()
    if v > 200:
        bar = "#" * min(60, int(v / 200))
        print(f"  y={y:5d} {v:7d} {bar}")
print("\n=== x 方向剖面 (每 32 列的金像素数, 只印有值的段) ===")
for x in range(0, m.shape[1], 32):
    v = colc[x:x + 32].sum()
    if v > 200:
        print(f"  x={x:5d} {v:7d} {'#' * min(60, int(v / 300))}")
