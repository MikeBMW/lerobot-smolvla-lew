#!/usr/bin/env python3
"""🏷 验证 3D 文字标注是否真的显示在屏幕上 (GLTextItem 用 QPainter 画在控件表面,
grabFramebuffer 抓不到 → 必须抓真实 X11 窗口)

用法: DISPLAY=:0 gui-venv311/bin/python tools/probe_text_labels.py
做法: 窗口移到 (0,0) 置顶 → 全屏截图裁窗口区 → 对比"有标注文本"vs"清空文本"的绿色像素差
"""
import os
import subprocess
import sys
import time

import numpy as np

os.environ.setdefault("DISPLAY", ":0")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))

from PyQt5.QtWidgets import QApplication  # noqa: E402
from PyQt5.QtCore import Qt  # noqa: E402

app = QApplication(sys.argv)
import ss_dreamview as sdv  # noqa: E402

tr, meta = sdv.load_episode()
dv = sdv.DreamView3D(tr)
dv.setWindowFlag(Qt.WindowStaysOnTopHint, True)
dv.resize(1180, 820)
dv.move(0, 0)
dv.show()
dv.raise_()
dv.activateWindow()
for _ in range(12):
    app.processEvents()
time.sleep(1.0)
dv._update_frame(1300)
for k, _n, _o, _t in dv._layers_def:
    dv._toggle_layer(k, False)
dv._toggle_layer("uff", True)
for _ in range(6):
    app.processEvents()
time.sleep(0.6)

W, H = dv.width(), dv.height()
SHOT = "/tmp/label_shot.png"


def shot(tag):
    for _ in range(4):
        app.processEvents()
    time.sleep(0.5)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "x11grab",
                    "-video_size", "3200x2000", "-i", ":0", "-frames:v", "1", SHOT], check=True)
    from PIL import Image
    a = np.asarray(Image.open(SHOT).convert("RGB").crop((0, 0, W, H))).astype(int)
    grn = int(((a[:, :, 1] > 110) & (a[:, :, 0] < a[:, :, 1] - 45) & (a[:, :, 2] < a[:, :, 1] - 45)).sum())
    nb = int(((a > 45).any(axis=2)).sum())
    print(f"  {tag:<18} 绿色 {grn:6d} px   非背景 {nb:7d} px")
    return grn


txt = dv._gl_items["uff_lab"].text
print(f"标注文本: {txt!r}\n窗口 {W}x{H}")
g_on = shot("有标注文本")
dv._gl_items["uff_lab"].setData(text="")
g_off = shot("清空标注文本")
dv._gl_items["uff_lab"].setData(text=txt)
g_back = shot("恢复标注文本")
d = g_on - g_off
print(f"\n标注文本贡献绿色像素: {d} px (恢复后 {g_back - g_off} px)")
print(f"→ 3D 文字标注{'✅ 真的显示在屏幕上' if d > 100 else '❌ 没有渲染 (需换实现)'}")
dv.close()
app.quit()
