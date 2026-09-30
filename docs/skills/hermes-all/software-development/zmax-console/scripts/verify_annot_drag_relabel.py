#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""标定窗两个真 bug 的可复跑取证 (offscreen, 无显示环境可跑)

用法 (必须用控制台的 gui venv, 它有 PyQt5):
    cd ~/lerobot-smolvla-lew && gui-venv311/bin/python \
        ~/.hermes/skills/software-development/zmax-console/scripts/verify_annot_drag_relabel.py

验两条 (2026-09-17 老倪报「左键拖不出框」+「改选中类别不好使」的回归锚点):
  A. 拖框锚点: 按下→多步移动→松开, 必须拖出**整块**矩形 (不是最后一小段/碎片)
     · 0°   显示(100,100)→(260,220), 320x240 原帧显示在 640x480 控件 → 期望原帧 (50,50,130,110)
     · 180° 同上 → 期望原帧 (189,129,269,189)  (自动换算回原始帧坐标, 标签不会镜像)
  B. 选中项跨窗镜像: 在**旋转窗**(右窗)选中一个框, 左窗 selected() 必须同步;
     然后 _relabel_selected() 必须把两窗的框都改成新类别 (修复前左窗恒 -1 → "按钮坏了")

判据: 全部 ✅ 打印 "ALL PASS" 且 exit 0。改 tools/gui/yolo_label_widget.py 或
tools/gui/yolo_input_viewer.py 之后, **先跑本脚本再重启控制台**。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = os.environ.get("ZMAX_REPO", "/home/ubuntu/lerobot-smolvla-lew")
sys.path.insert(0, os.path.join(REPO, "tools", "gui"))
sys.path.insert(0, os.path.join(REPO, "tools"))

import numpy as np                                        # noqa: E402
from PyQt5 import QtCore, QtGui, QtWidgets                # noqa: E402
from yolo_label_widget import YoloLabelWidget             # noqa: E402

app = QtWidgets.QApplication([])
fails = []


def ev(t, x, y, btn=QtCore.Qt.LeftButton):
    return QtGui.QMouseEvent(t, QtCore.QPointF(x, y), btn, btn, QtCore.Qt.NoModifier)


def drag(rot_deg, pts, release):
    """在给定旋转角的控件上模拟一次拖框, 返回首框 (原始帧像素坐标) 或 None"""
    w = YoloLabelWidget(rot_deg=rot_deg, editable=True)
    w.resize(640, 480)
    w.set_frame_rgb(np.zeros((240, 320, 3), dtype=np.uint8))   # scale=2, off=(0,0)
    w.show()
    app.processEvents()
    w.mousePressEvent(ev(QtCore.QEvent.MouseButtonPress, *pts[0]))
    for x, y in pts[1:]:
        w.mouseMoveEvent(ev(QtCore.QEvent.MouseMove, x, y, QtCore.Qt.NoButton))
    w.mouseReleaseEvent(ev(QtCore.QEvent.MouseButtonRelease, *release))
    bx = w.boxes_px()
    return tuple(bx[0][:4]) if bx else None


# ── A. 拖框锚点 (0° / 180°) ────────────────────────────────────────────────
PTS = [(100, 100), (140, 130), (180, 160), (220, 190), (260, 220)]
for rot, expect in ((0, (50.0, 50.0, 130.0, 110.0)), (180, (189.0, 129.0, 269.0, 189.0))):
    got = drag(rot, PTS, (260, 220))
    ok = got is not None and all(abs(got[i] - expect[i]) <= 1.5 for i in range(4))
    print(f"[A] 拖框 rot={rot:>3}°  得到 {got}  期望 {expect}  ->", "OK" if ok else "FAIL")
    if not ok:
        fails.append(f"drag rot={rot}: got {got}, want {expect}")

# ── B. 选中项跨窗镜像 + 改选中类别 ────────────────────────────────────────
try:
    import yolo_input_viewer as yv                        # noqa: E402
    import yolo_annot_dataset as yad                      # noqa: E402

    yv._SimGrabber = lambda *a, **k: None                 # 不真起仿真采集线程
    w = yv.YoloInputViewer(source="sim")                  # sim 源: 不碰真机链路/数据根
    w.timer.stop()
    w._rgb = np.zeros((240, 320, 3), dtype=np.uint8)
    w.w_orig.resize(640, 480)
    w.w_rot.resize(640, 480)
    w._paint_frames()
    w._toggle_annot(True)
    BOX = (50.0, 50.0, 130.0, 110.0)
    w.w_orig.set_boxes([(*BOX, "peg")])
    w.w_rot.set_boxes([(*BOX, "peg")])
    w._syncing = True
    w.w_orig._sel = -1
    w.w_rot._sel = -1
    w._syncing = False
    w.w_rot._sel = 0                        # 模拟"在旋转窗里点选这个框"
    w.w_rot._emit()                         # 触发 selectionChanged -> _mirror_sel
    mirrored = w.w_orig.selected() == 0
    print(f"[B1] 右窗选中后 左窗 selected() = {w.w_orig.selected()} (期望 0) ->",
          "OK" if mirrored else "FAIL")
    if not mirrored:
        fails.append("selection mirror not working")
    yad.add_class(w.annot_root, "hole")
    w.cb_cls.setCurrentText("hole")
    w._relabel_selected()
    l = [b["cls"] for b in w.w_orig.boxes()]
    r = [b["cls"] for b in w.w_rot.boxes()]
    ok = l == ["hole"] and r == ["hole"]
    print(f"[B2] 改选中类别后 左窗 {l} 右窗 {r} (期望 ['hole'] 两边) ->", "OK" if ok else "FAIL")
    if not ok:
        fails.append(f"relabel: left={l} right={r}")
except Exception as e:                                     # noqa: BLE001
    print("[B] 构造 YoloInputViewer 失败:", type(e).__name__, e)
    fails.append(f"viewer init: {e}")

print("\n" + ("ALL PASS" if not fails else "FAILURES:\n  - " + "\n  - ".join(fails)))
sys.exit(0 if not fails else 1)
