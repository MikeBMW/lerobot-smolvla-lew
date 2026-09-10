#!/usr/bin/env python3
"""🔍 simulink UI 尺寸实测探针 (离屏, 不弹窗) — 工具栏按钮 + 模块库宽度

用法:
  QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/probe_ui_metrics.py [宽 ...]

实测内容 (全部读真实 Qt 控件几何, 非估算):
  1. 工具栏每个按钮: 宽/高/字号px/文字所需宽 → 判定是否"字挤在一起"(余量<12px)
  2. 多窗口宽度下工具栏行数 (FlowLayout 自动换行, 窄窗口不压扁按钮)
  3. 模块库: 434 个模块按钮里有多少条文字被面板宽度切掉 (含不同面板宽度对照表)
  4. 深色主题切换后字号是否仍然保持 (switch_theme 只换颜色不能改字号)
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "gui"))

from PyQt5.QtWidgets import QApplication, QPushButton, QToolButton  # noqa: E402
from PyQt5.QtGui import QFontMetrics  # noqa: E402

WIDTHS = [int(a) for a in sys.argv[1:]] or [3068, 2400, 1800, 1200]

app = QApplication(sys.argv)
import simulink_module as sm  # noqa: E402

m = sm.SimulinkModule()
m.resize(WIDTHS[0], 1862)
m.show()
for _ in range(6):
    app.processEvents()
tb = m.btn_run.parentWidget()


def toolbar_stats(width):
    m.resize(width, 1862)
    for _ in range(4):
        app.processEvents()
    tb.layout().activate()
    app.processEvents()
    btns = [b for b in tb.findChildren(QPushButton) if not b.isHidden()]
    rows = sorted(set(b.y() for b in btns))
    squeeze = sum(1 for b in btns
                  if b.width() - QFontMetrics(b.font()).horizontalAdvance(b.text()) < 12)
    over = sum(1 for b in btns if b.x() + b.width() > tb.width())
    return btns, rows, squeeze, over


print("═══ 1) 工具栏按钮 (窗口宽 %d) ═══" % WIDTHS[0])
btns, rows, squeeze, over = toolbar_stats(WIDTHS[0])
print(f"{'按钮':<18} {'宽':>5} {'高':>4} {'字宽':>5} {'字号px':>6} {'余量':>6}")
print("-" * 52)
for b in sorted(btns, key=lambda b: (b.y(), b.x())):
    fm = QFontMetrics(b.font())
    adv = fm.horizontalAdvance(b.text())
    print(f"{b.text():<18} {b.width():>5} {b.height():>4} {adv:>5} {fm.height():>6} "
          f"{b.width() - adv:>6}")
print("-" * 52)
print(f"布局={tb.layout().__class__.__name__}  工具栏高={tb.height()}px  行数={len(rows)}  "
      f"按钮高={btns[0].height()}px  字高={QFontMetrics(btns[0].font()).height()}px")
print(f"挤压(余量<12px)={squeeze}  溢出={over}   ← 都应为 0")

print("\n═══ 2) 多宽度自适应 (窄窗口/浮动画布) ═══")
print(f"{'窗口宽':>7} {'工具栏高':>8} {'行数':>5} {'挤压':>5} {'溢出':>5}")
for w in WIDTHS:
    _b, rws, sq, ov = toolbar_stats(w)
    print(f"{w:>7} {tb.height():>8} {len(rws):>5} {sq:>5} {ov:>5}")
toolbar_stats(WIDTHS[0])

print("\n═══ 3) 模块库文字截断 ═══")
lib = m.library
sbw = lib.scroll.verticalScrollBar().sizeHint().width()
libb = [b for b in lib.findChildren(QToolButton) if not b.isHidden()]
adv = sorted(QFontMetrics(b.font()).horizontalAdvance(b.text()) for b in libb)
n = len(adv)
print(f"模块库宽={lib.width()}px  滚动条={sbw}px  模块按钮={n} 个")
print("文字宽分位数: " + "  ".join(
    f"P{p}={adv[min(n - 1, int(n * p / 100))]}" for p in (50, 75, 90, 95, 99, 100)))
print(f"{'面板宽':>7} {'文字可用':>8} {'被切':>6} {'占比':>7}")
for W in (360, 460, 500, 560, 620):
    usable = W - 16 - sbw - 24
    bad = sum(1 for a in adv if a > usable)
    mark = "  ← 当前" if W == lib.width() else ""
    print(f"{W:>7} {usable:>8} {bad:>6} {bad / n * 100:>6.1f}%{mark}")

print("\n═══ 4) 深色主题切换后字号保持 ═══")
before = QFontMetrics(m.btn_run.font()).height()
h_before = m.btn_run.height()
m.switch_theme("dark")
app.processEvents()
after = QFontMetrics(m.btn_run.font()).height()
print(f"▶运行 字高: light={before}px → dark={after}px   按钮高: {h_before} → {m.btn_run.height()}px "
      f"{'✅ 保持' if after == before else '❌ 被改'}")
app.quit()
