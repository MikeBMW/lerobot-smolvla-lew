#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QMenu 渲染二分探针 — 定位"右键菜单全黑/黑屏无字"问题在渲染层还是显示层。

方法 (2026-08-30 实测有效):
  ① menu.grab()      = Qt 离屏渲染结果 (绕过 X server, 只测 Qt 自己能不能画)
  ② grabWindow 截屏   = X 屏幕实际显示 (含合成/重绘/时序问题)
  两者对比: ①正常②黑 → 显示层问题 (合成器/时序/窗口栈); ①②都黑 → Qt 渲染问题 (QSS/字体/palette)。
  附屏幕时序: show 后 0.15s / 0.5s / 1.5s 三次截屏, 区分"弹出瞬间黑一下"vs"永久黑"。

用法 (真实 DISPLAY, 不要 offscreen — 显示层问题 offscreen 测不出来):
    DISPLAY=:0 python3 scripts/menu_render_probe.py

参考: simulink 画布右键 QMenu 2026-08-12 曾因深色 QSS 在 VcXsrv 黑屏无字 → 去 QSS 用系统默认;
2026-08-30 系统默认菜单在 3200x2000 Xorg 实测 0.5s 内正常上屏, 渲染层三样式全正常。
"""
import os
import sys
import time

os.environ.setdefault("DISPLAY", ":0")
from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtWidgets import QApplication, QMenu  # noqa: E402

for attr in ("AA_UseSoftwareOpenGL", "AA_DisableWindowManagerEffects"):
    try:
        QApplication.setAttribute(getattr(Qt, attr), True)
    except Exception:
        pass  # 与 studio.py 一致: 不可用属性被吞

app = QApplication(sys.argv)

ITEMS = ["查看/编辑节点逻辑", "节点参数", "打开源代码", "运行节点", "导出 Excel (全部任务)"]
STYLES = {
    "A_default": None,
    "B_dark": ("QMenu { background:#161b22; color:#e6edf3; border:1px solid #30363d; } "
               "QMenu::item { color:#e6edf3; padding:6px 22px; } "
               "QMenu::item:selected { background:#1f6feb; color:#ffffff; }"),
    "C_light": ("QMenu { background:#ffffff; color:#1f2328; border:1px solid #8b949e; } "
                "QMenu::item { color:#1f2328; padding:6px 22px; } "
                "QMenu::item:selected { background:#0969da; color:#ffffff; }"),
}


def analyze(pm, label):
    img = pm.toImage()
    w, h = img.width(), img.height()
    if w == 0 or h == 0:
        print(f"[{label}] 空图! (grab 失败)")
        return None
    n = 0
    rsum = gsum = bsum = 0
    dark = light = 0
    for yy in range(0, h, 2):
        for xx in range(0, w, 2):
            c = img.pixelColor(xx, yy)
            r, g, b = c.red(), c.green(), c.blue()
            n += 1
            rsum += r
            gsum += g
            bsum += b
            if (r + g + b) / 3 < 25:
                dark += 1
            elif (r + g + b) / 3 > 150:
                light += 1
    print(f"[{label}] {w}x{h} avgRGB=({rsum/n:.0f},{gsum/n:.0f},{bsum/n:.0f}) "
          f"暗{dark/n*100:.0f}% 亮{light/n*100:.0f}%")
    return dark / n


from PyQt5.QtGui import QGuiApplication  # noqa: E402

scr = QGuiApplication.primaryScreen()

print("=== ① Qt 离屏渲染 vs ② X 屏幕显示 ===")
for name, qss in STYLES.items():
    m = QMenu()
    if qss:
        m.setStyleSheet(qss)
    for t in ITEMS:
        m.addAction(t)
    m.show()
    for _ in range(8):
        app.processEvents()
    p_qt = m.grab()
    geo = m.frameGeometry()
    p_scr = scr.grabWindow(0, geo.x(), geo.y(), geo.width(), geo.height())
    m.hide()
    for _ in range(5):
        app.processEvents()
    d_qt = analyze(p_qt, f"{name}_qt_grab")
    d_scr = analyze(p_scr, f"{name}_screen")
    p_qt.save(f"/tmp/menu_probe_{name}_qt.png")
    verdict = "显示层问题" if (d_qt is not None and d_qt < 0.5 and d_scr is not None and d_scr > 0.8) else \
              ("Qt 渲染问题" if d_qt is not None and d_qt > 0.8 else "正常")
    print(f"    → {name}: {verdict}")

print("=== ③ 屏幕时序 (深色菜单 show 后 0.15/0.5/1.5s) ===")
m = QMenu()
m.setStyleSheet(STYLES["B_dark"])
for t in ITEMS:
    m.addAction(t)
m.move(600, 400)
m.show()
for t in (0.15, 0.5, 1.5):
    time.sleep(t)
    app.processEvents()
    pm = scr.grabWindow(0, 590, 390, 320, 260)
    analyze(pm, f"t={t}s")
m.hide()
print("结论: ①②全正常 = 渲染层无问题, 怀疑场景/时序; ①黑 = QSS/字体问题; ②黑 = X 显示层问题")
