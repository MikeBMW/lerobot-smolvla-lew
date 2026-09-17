# -*- coding: utf-8 -*-
"""真机桌面 (192DPI) 标定 UI 目检取证:
① 标定行/数据行按钮是否被挤压截断 (老倪红线: "显示不全" = 没做)
② 两窗 + 标定控件在真实屏幕上的实际像素 (offscreen 96DPI 会误判)
③ 落一张截图给人目检
跑法: DISPLAY=:0 gui-venv311/bin/python 本文件 [--with-chain]
"""
import os
import sys
import time

ROOT = "/home/ubuntu/lerobot-smolvla-lew"
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
os.environ.setdefault("DISPLAY", ":0")
OUT = "/home/ubuntu/zmax_data/annot_ui_real_192dpi.png"

import numpy as np                                                            # noqa: E402
from PyQt5 import QtWidgets                                                   # noqa: E402

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
import yolo_input_viewer as yiv                                               # noqa: E402

ok = True


def chk(tag, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(f"  {'✅' if cond else '❌'} {tag} {detail}")


WITH = "--with-chain" in sys.argv
if WITH:
    print("链路:", yiv._RemoteChain.ensure())
v = yiv.open_input_viewer(None, module=None, source="real")
if WITH:                                     # 有链路就吃真机帧, 没有就用合成帧 (只为看 UI)
    t0 = time.time()
    while time.time() - t0 < 30:
        app.processEvents(); time.sleep(0.05)
        if v._rgb is not None:
            break
if v._rgb is None:
    fr = np.zeros((480, 640, 3), np.uint8)
    fr[340:470, 190:450] = (0, 200, 170)
    fr[20:60, 20:200] = (120, 120, 120)
    v._rgb = fr
    v._paint_frames()
_entry_ok = v.chk_annot.isVisible() and v.chk_annot.width() > 60
chk("真桌面默认状态: 「✏️ 标定模式」入口可见且够大", _entry_ok,
    f"| {v.chk_annot.width()}x{v.chk_annot.height()}px text={v.chk_annot.text()!r}")
chk("真桌面默认状态: 常显提示可见且写明下一步", v.lbl_annot_hint.isVisible() and "标定模式" in v.lbl_annot_hint.text(),
    f"| {v.lbl_annot_hint.text()[:50]}")
v.chk_annot.setChecked(True)                 # 标定模式 (按钮/面板全出现)
v.w_orig.add_box_px((190, 340, 450, 470), "optical_module")
app.processEvents(); time.sleep(0.6); app.processEvents()

scr = app.primaryScreen().availableGeometry()
print(f"屏幕 {scr.width()}x{scr.height()} · DPI={app.primaryScreen().logicalDotsPerInch():.0f} · 窗口 {v.width()}x{v.height()}")
vis = [b for b in v.findChildren(QtWidgets.QPushButton) if b.isVisible()]
rows = {}
for b in vis:
    y = b.mapTo(v, b.rect().topLeft()).y() // 20
    rows.setdefault(y, []).append(b)
bad = []
for b in vis:
    hint = b.sizeHint().width()
    got = b.width()
    if got < hint - 1:
        bad.append(f"{b.text()}({got}<{hint})")
chk("标定/数据按钮文字未被截断 (实际宽 ≥ sizeHint)", not bad, f"| 截断: {bad}" if bad else f"共 {len(vis)} 个按钮")
print(f"   按钮行分布: {[(k*20, [b.text() for b in v2]) for k, v2 in sorted(rows.items())]}")
lo, ro = v.w_orig.geometry(), v.w_rot.geometry()
chk("两窗并排且右窗可见", ro.x() > lo.x() and v.w_rot.isVisible(),
    f"左 {lo.width()}x{lo.height()} @{lo.x()} · 右 {ro.width()}x{ro.height()} @{ro.x()}")
chk("左窗显示帧 + 框", v.w_orig.pixmap() is not None and not v.w_orig.pixmap().isNull()
    and len(v.w_orig.boxes()) == 1, f"| 框 {len(v.w_orig.boxes())}")
chk("数据行显示路径/张数/类别", v.annot_root in v.lbl_data.text() and "类别" in v.lbl_data.text(),
    f"| {v.lbl_data.text()[:90]}")
chk("状态行含标定信息", "标定:" in v.st.text() and "已存" in v.st.text())
chk("窗口完整在屏内", v.x() >= 0 and v.y() >= 0 and v.x() + v.width() <= scr.width() + 2
    and v.y() + v.height() <= scr.height() + 2, f"@({v.x()},{v.y()})")
v.raise_(); app.processEvents(); time.sleep(0.8); app.processEvents()
v.grab().save(OUT, "PNG")
chk("截图已存", os.path.isfile(OUT) and os.path.getsize(OUT) > 10000,
    f"{OUT} ({os.path.getsize(OUT) if os.path.isfile(OUT) else 0} B)")
v.close()
if WITH:
    yiv._RemoteChain.stop()
print("\n结论:", "✅ 全部通过" if ok else "❌ 有不通过项")
sys.exit(0 if ok else 1)
