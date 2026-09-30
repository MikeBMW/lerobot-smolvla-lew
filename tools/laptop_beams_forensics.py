#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""笔记本摄像头: 找横梁边线(水平/竖直族) + 内部空间候选边界 —— 像素取证, 不靠模型口头。"""
import cv2, json, math, sys
import numpy as np

SRC = sys.argv[1] if len(sys.argv) > 1 else "/tmp/local_raw.jpg"
raw = open(SRC, "rb").read()
im = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
H, W = im.shape[:2]
g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
print("   帧 %dx%d 亮度均值 %.1f σ %.1f" % (W, H, g.mean(), g.std()))

# ① 行/列梯度能量 ⇒ 水平边 / 竖直边的强度剖面
gy = np.abs(cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)).mean(1)   # 行方向变化 ⇒ 水平边
gx = np.abs(cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)).mean(0)   # 列方向变化 ⇒ 竖直边
def peaks(v, name, k=12, min_gap=12):
    idx = np.argsort(v)[::-1]
    out = []
    for i in idx:
        if all(abs(i - j) >= min_gap for j, _ in out):
            out.append((int(i), round(float(v[i]), 2)))
        if len(out) >= k:
            break
    out.sort()
    print("   %s 强边(位置:能量) = %s" % (name, out))
    return out
hp = peaks(gy, "水平边 y")
vp = peaks(gx, "竖直边 x")

# ② Hough 拿线族角度分布(判断"横梁互相垂直"在画面里是否 90°)
edges = cv2.Canny(g, 40, 120)
ls = cv2.HoughLinesP(edges, 1, np.pi / 180.0, threshold=55, minLineLength=70, maxLineGap=6)
bins = {}
segs = []
if ls is not None:
    for a in ls.reshape(-1, 4):
        x1, y1, x2, y2 = [int(t) for t in a]
        ang = math.degrees(math.atan2(y2 - y1, x2 - x1)) % 180.0
        L = math.hypot(x2 - x1, y2 - y1)
        b = int(round(ang / 10.0) * 10) % 180
        bins[b] = bins.get(b, 0) + 1
        segs.append((round(ang, 1), round(L, 1), x1, y1, x2, y2))
tot = sum(bins.values()) or 1
print("   线族角度分布(每 10°): %s" % sorted([(k, "%d%%" % (100 * v / tot)) for k, v in bins.items()], key=lambda t: -t[0]))
# 找"最接近水平"和"最接近竖直"的族, 看它们的夹角是否≈90°
hz = max([s for s in segs if s[0] < 20 or s[0] > 160], key=lambda s: s[1], default=None)
vt = max([s for s in segs if 70 <= s[0] <= 110], key=lambda s: s[1], default=None)
if hz and vt:
    d = abs(hz[0] - vt[0])
    print("   ★ 最长近水平线 %.1f° vs 最长近竖直线 %.1f° ⇒ 夹角 %.1f° (现场说横梁互相垂直=90°)" % (hz[0], vt[0], min(d, 180 - d)))

# ③ 内部空间候选: 画面中部的"暗腔"连通域(横梁围出的空间通常是暗背景)
hsv = cv2.cvtColor(im, cv2.COLOR_BGR2HSV)
dark = (g < max(60, int(g.mean() * 0.65))).astype(np.uint8)
dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
n, lab, st, cent = cv2.connectedComponentsWithStats(dark, 8)
regs = []
for i in range(1, n):
    x, y, w, h, a = st[i]
    if a < 0.01 * W * H:
        continue
    regs.append({"bbox": [int(x), int(y), int(x + w), int(y + h)], "area": int(a),
                 "fill": round(a / float(w * h), 2), "cx": int(cent[i][0]), "cy": int(cent[i][1])})
regs.sort(key=lambda r: -r["area"])
print("   大暗区(前5): %s" % json.dumps(regs[:5], ensure_ascii=False))
# ④ 中部那条水平带的最暗行(内部空间的"地面/深处"参考)
band = g[:, int(0.15 * W):int(0.85 * W)].mean(1)
y_dark = int(np.argmin(band))
print("   中部横带最暗行 y=%d (亮度 %.1f) ⇒ 常是腔内深处/缝隙" % (y_dark, band[y_dark]))
print("   中位亮度 y=%.1f" % (H / 2))

# ⑤ 生成候选线对比图: 把 top-k 水平边画上去
vis = im.copy()
for y, e in hp:
    cv2.line(vis, (0, y), (W - 1, y), (0, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(vis, "y%d e%.0f" % (y, e), (6, max(12, y - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 255, 255), 1, cv2.LINE_AA)
for x, e in vp:
    cv2.line(vis, (x, 0), (x, H - 1), (255, 128, 0), 1, cv2.LINE_AA)
    cv2.putText(vis, "x%d" % x, (max(2, x + 2), 12), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 128, 0), 1, cv2.LINE_AA)
cv2.imwrite("/tmp/laptop_edges.jpg", vis, [int(cv2.IMWRITE_JPEG_QUALITY), 94])
json.dump({"size": [W, H], "h_edges": hp, "v_edges": vp, "dark_regions": regs[:5], "y_dark_band": y_dark},
          open("/tmp/laptop_forensics.json", "w"), indent=1)
print("   写出 /tmp/laptop_forensics.json 与 /tmp/laptop_edges.jpg")
