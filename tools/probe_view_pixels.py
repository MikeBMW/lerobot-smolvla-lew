#!/usr/bin/env python3
"""🖼 3D 视图画面成分分析 — 屏幕上到底是什么在画点 (DISPLAY=:0 读 framebuffer)

输出: 各元素像素数占比 + 60x26 文字色块图 (给看不到图的场景用)
用法: DISPLAY=:0 gui-venv311/bin/python tools/probe_view_pixels.py [帧号]
"""
import os
import sys

import numpy as np

os.environ.setdefault("DISPLAY", ":0")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))

from PyQt5.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
import ss_dreamview as sdv  # noqa: E402

tr, meta = sdv.load_episode()
if tr is None:
    print("❌ 无同源 trace")
    sys.exit(1)
dv = sdv.DreamView3D(tr)
dv.resize(1180, 820)
dv.show()
for _ in range(8):
    app.processEvents()
idx = int(sys.argv[1]) if len(sys.argv) > 1 else len(tr["x"]) // 2
dv._update_frame(idx)
for _ in range(5):
    app.processEvents()
q = dv.view.grabFramebuffer()
W, H = q.width(), q.height()
ptr = q.bits()
ptr.setsize(q.byteCount())
arr = np.frombuffer(ptr, np.uint8).reshape(H, q.bytesPerLine() // 4, 4)[:, :W, :3][:, :, ::-1]
a = arr.astype(int)
stage = tr["stage"][idx].replace("阶段 ", "")
print(f"帧 {idx}/{len(tr['x']) - 1}  阶段 {stage}   画布 {W}x{H}")

CLASSES = [
    ("背景 #0d1117", (13, 17, 23), 18),
    ("台面(深灰蓝)", (41, 46, 56), 22),
    ("带孔盒(红)", (242, 56, 36), 60),
    ("光模块(金)", (242, 184, 26), 55),
    ("机械臂(橙红)", (217, 76, 46), 55),
    ("关节(灰)", (102, 107, 117), 30),
    ("夹爪(青)", (51, 217, 230), 60),
    ("末端轨迹(蓝)", (89, 166, 255), 40),
    ("融合指令u(金黄)", (255, 199, 31), 30),
    ("前馈u_ff(绿)", (51, 217, 89), 60),
    ("限幅u_sat(红)", (255, 77, 77), 45),
    ("状态估计x̂(紫)", (217, 115, 242), 55),
    ("接触球(橙)", (255, 102, 0), 45),
    ("YOLO peg(青绿)", (0, 212, 168), 50),
    ("YOLO hole(橙黄)", (255, 166, 0), 45),
]
tot = H * W
print(f"\n{'元素':<20} {'像素':>8} {'占比':>8}  位置")
print("-" * 62)
for name, (r, g, b), tol in CLASSES:
    m = (np.abs(a[:, :, 0] - r) < tol) & (np.abs(a[:, :, 1] - g) < tol) & (np.abs(a[:, :, 2] - b) < tol)
    n = int(m.sum())
    if n == 0:
        print(f"{name:<20} {0:>8} {'-':>8}  (未出现/图层关闭)")
        continue
    ys, xs = np.nonzero(m)
    print(f"{name:<20} {n:>8} {100 * n / tot:7.3f}%  质心({xs.mean():4.0f},{ys.mean():4.0f}) "
          f"x{xs.min()}-{xs.max()} y{ys.min()}-{ys.max()}")

# 文字色块图
gw, gh = 60, 26
from PIL import Image  # noqa: E402
small = np.asarray(Image.fromarray(arr).resize((gw, gh), Image.BOX)).astype(int)


def sym(px):
    r, g, b = px
    if r < 45 and g < 50 and b < 60:
        return "."
    if r > 140 and 120 < g < 230 and b < 90:
        return "G"      # 金/金黄
    if r > 140 and g < 120 and b < 90:
        return "R"      # 红/橙红
    if b > 140 and r < 140 and g > 100:
        return "B"      # 蓝
    if r > 140 and b > 140:
        return "P"      # 紫
    if g > 140 and b > 140 and r < 140:
        return "C"      # 青
    if g > 130 and r < 130 and b < 130:
        return "g"      # 绿
    if r > 100 and g > 100 and b > 100:
        return "W"      # 灰
    return "-"


print("\n" + "   " + "".join(str(i // 10) for i in range(gw)))
for y in range(gh):
    print("%2d " % y + "".join(sym(small[y, x]) for x in range(gw)))
print("\n图例: . 背景 | G 金(光模块/融合指令) | R 红(带孔盒/机械臂) | B 蓝(轨迹) | "
      "P 紫(状态估计) | C 青(夹爪) | g 绿(前馈) | W 灰(关节/台面)")
dv.close()
app.quit()
