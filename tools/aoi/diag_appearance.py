"""看清金手指区的真实外观: 亮度/金色掩膜 高分辨 ASCII + 像素统计 (决定模板用什么通道)"""
import cv2
import numpy as np

P = "/home/ubuntu/aoi_v4/imgs/Finger_Image_W2448_H2048_No_8.png"
im = cv2.imread(P)
X0, X1, Y0, Y1 = 380, 2020, 1080, 1340
sub = im[Y0:Y1, X0:X1]
g = cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY)
hsv = cv2.cvtColor(sub, cv2.COLOR_BGR2HSV)
m = cv2.inRange(hsv, np.array([8, 60, 50]), np.array([45, 255, 255]))
RAMP = " .:-=+*#%@"

def amap(a, cols=82, rows=26, label=""):
    s = cv2.resize(a.astype(np.float32), (cols, rows), interpolation=cv2.INTER_AREA)
    lo, hi = float(s.min()), float(s.max())
    print(f"\n--- {label} (x {X0}..{X1}, y {Y0}..{Y1}; 每格 {int((X1-X0)/cols)}x{int((Y1-Y0)/rows)}px; {lo:.0f}..{hi:.0f}) ---")
    for r in range(rows):
        y = Y0 + int(r * (Y1 - Y0) / rows)
        print(f"{y:5d} " + "".join(RAMP[min(9, int((s[r, c] - lo) / max(hi - lo, 1e-6) * 9))] for c in range(cols)))

amap(g, label="亮度")
amap(m, label="金色掩膜")
# 梯度(结构) —— 看焊盘在梯度图上是否清晰(用于模板匹配)
grad = cv2.magnitude(cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3))
amap(grad, label="梯度幅值 |∇|")

print("\n=== 像素统计 ===")
band = np.zeros(g.shape, np.uint8)
band[100:190, :] = 1     # y≈1180..1270 → 条
print(f"条带内 (y{Y0+100}..{Y0+190}): 亮度 均值{g[band>0].mean():.1f} std{g[band>0].std():.1f} | "
      f"金掩膜像素占比 {m[band>0].mean()/255*100:.1f}% | BGR均值 {sub[band>0].mean(axis=0)}")
out = band == 0
print(f"条带外:                     亮度 均值{g[out].mean():.1f} std{g[out].std():.1f} | "
      f"金掩膜像素占比 {m[out].mean()/255*100:.1f}% | BGR均值 {sub[out].mean(axis=0)}")
print(f"梯度能量: 条带内 {grad[band>0].mean():7.1f} | 条带外 {grad[out].mean():7.1f}")
