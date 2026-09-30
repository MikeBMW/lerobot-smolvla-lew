"""定位"金手指"到底是哪一段: 焊盘排 vs 下方实心金带 —— 逐行成分 + 分run分析 + 各run的x范围
(现场口径: 只保留金手指本身, 下方厚边沿不要; 金手指纵向太短要拉长给 YOLO)
"""
import cv2
import numpy as np
import sys

P = "/home/ubuntu/aoi_v4/imgs/Finger_Image_W2448_H2048_No_8.png"
im = cv2.imread(P)
g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
hsv = cv2.cvtColor(im, cv2.COLOR_BGR2HSV)
m = cv2.inRange(hsv, np.array([8, 60, 50]), np.array([45, 255, 255])) > 0
m = cv2.morphologyEx(m.astype(np.uint8) * 255, cv2.MORPH_CLOSE,
                     cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))) > 0

# 主列段 (最大金连通域)
n, lab, stats, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), 8)
i = 1 + int(np.argmax(stats[1:, 4]))
x0, x1 = int(stats[i, 0]), int(stats[i, 0] + stats[i, 2] - 1)
sub = m[:, x0:x1 + 1]
rows = sub.sum(axis=1)
thr = max(25, 0.05 * rows.max())
print(f"主列段 x[{x0},{x1}] 宽{x1-x0+1} · 行密度峰 {rows.max()} · 阈值 {thr:.0f}")

dense = rows > thr
# 分 run (空隙 <=6 行合并)
runs, s = [], None
for y in range(len(dense)):
    if dense[y] and s is None:
        s = y
    elif not dense[y] and s is not None:
        # 允许 <=6 行空隙
        if y + 6 < len(dense) and any(dense[y:y + 7]):
            continue
        runs.append((s, y - 1)); s = None
if s is not None:
    runs.append((s, len(dense) - 1))
gx = np.abs(cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3))
print(f"\n{'run':<14}{'高':>5}{'金覆盖%':>9}{'|gx|均':>8}{'亮度均':>8}{'x范围':>18}{'行密度CV':>9}  判读")
for (a, b) in runs:
    if b - a < 8:
        continue
    cov = sub[a:b + 1].mean() * 100
    gg = gx[a:b + 1, x0:x1 + 1].mean()
    lum = g[a:b + 1, x0:x1 + 1].mean()
    cols = sub[a:b + 1].sum(axis=0)
    cidx = np.where(cols > 0)[0]
    xr = (x0 + cidx.min(), x0 + cidx.max()) if len(cidx) else (0, 0)
    cvv = rows[a:b + 1].std() / max(rows[a:b + 1].mean(), 1e-6)
    tag = "焊盘排(边缘多=离散)" if gg > 25 else ("实心带(边缘少)" if cov > 50 else "?")
    print(f"[{a},{b}]{'':<6}{b-a+1:>5}{cov:>9.1f}{gg:>8.1f}{lum:>8.1f}"
          f"{f'[{xr[0]},{xr[1]}]':>18}{cvv:>9.2f}  {tag}")

# 只看最上面那个 run 的逐列剖面 → 金手指左右端 & 焊盘周期性(间距)
print("\n逐列剖面 (最上面的 run, 每48列一个数; #=金像素数/列, 看焊盘周期性):")
a, b = next(((a, b) for (a, b) in runs if b - a >= 8))
cols = sub[a:b + 1].sum(axis=0)
for x in range(0, len(cols), 48):
    v = int(cols[x:x + 48].mean())
    print(f"   x={x0+x:5d} {v:4d} {'#'*int(v/3)}")
