#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_three_cam_canvas.py — 画布节点上「三相机叠加拼图」真出画面 (离屏真跑)

验的是**画布这一侧**最后的产物: 节点 video_pixmap 里那张 2×2 拼图。
  ① 三路都探到 (arm+local+local2)
  ② 拼图尺寸 = 572x344 (2 列 × 286, 顶带 20 + 2 行 × 162)
  ③ 逐格裁开数像素 ⇒ 三个格子都有真实画面 (不是黑格/不是同一张图) —— 光看
     "pixmap 非空" 会把"只有一路有帧"误判成三路都通
  ④ 落盘 /tmp/canvas_3cam.png 供人眼复核
用法: DISPLAY=:0 ./gui-venv311/bin/python tools/verify_three_cam_canvas.py
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, "/home/ubuntu/zmax/tools/gui")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("DISPLAY", ":0")
import numpy as np                                                                # noqa: E402
from PyQt5 import QtWidgets                                                       # noqa: E402
from PyQt5.QtCore import QEventLoop, QTimer                                       # noqa: E402

FLOW = "/home/ubuntu/zmax/flows/state_space_obs.json"
app = QtWidgets.QApplication(sys.argv)
import simulink_module as SM                                                      # noqa: E402

fails = []


def chk(name, cond, detail=""):
    print(("%-46s %s %s" % (name, "✅" if cond else "❌", detail)).rstrip())
    if not cond:
        fails.append(name)


m = SM.SimulinkModule()
m.load_flow_file(FLOW, confirm=False)
app.processEvents()
item = m._ov_live_target_item()
chk("画布上有「真实场景叠加」节点", item is not None,
    item.node.get("name", "") if item is not None else "没找到 → 先跑 tools/canvas_add_realscene_node.py")
if item is None:
    raise SystemExit(1)

m.start_canvas_live_overlay()                    # 缺省 = 三路
loop = QEventLoop()
QTimer.singleShot(12000, loop.quit)
loop.exec_()
app.processEvents()

srcs = m._ov_live.get("srcs") or []
chk("① 三路都探到并纳入", set(srcs) == {"arm", "local", "local2"},
    "srcs=%s · 未接=%s" % (srcs, m._ov_live.get("offline") or "无"))

pm = item.video_pixmap
chk("② 节点已出拼图", pm is not None and not pm.isNull(),
    "%sx%s" % (pm.width() if pm else "-", pm.height() if pm else "-"))
chk("② 拼图尺寸 = 572x344 (三格 2 列)", pm is not None and (pm.width(), pm.height()) == (572, 344),
    "%sx%s" % (pm.width() if pm else "-", pm.height() if pm else "-"))
chk("② 实时帧在跑 (frames≥4)", m._ov_live.get("frames", 0) >= 4,
    "frames=%d · 取帧失败 %d" % (m._ov_live.get("frames", 0), m._ov_live.get("fetch_err", 0)))

TILE, BAND = (286, 162), 20
img = None
if pm is not None and not pm.isNull():
    pm.save("/tmp/canvas_3cam.png", "PNG")
    tmp = pm.toImage()
    w, h = tmp.width(), tmp.height()
    bpl = tmp.bytesPerLine()                       # 老版 PyQt5 没 byteStride
    buf = tmp.constBits().asstring(bpl * h)
    img = np.frombuffer(buf, dtype=np.uint8).reshape(h, bpl // 4, 4)[:, :w, :3].astype(np.int16)

for i, nm in enumerate(srcs[:3]):
    if img is None:
        break
    cx, cy = (i % 2) * TILE[0], BAND + (i // 2) * TILE[1]
    cell = img[cy:cy + TILE[1], cx:cx + TILE[0]]
    mean = float(cell.mean()) if cell.size else -1.0
    std = float(cell.std()) if cell.size else 0.0
    dark = float((cell.max(axis=2) < 14).mean()) * 100.0 if cell.size else 100.0
    chk("③ 第%d格 [%s] 是真画面" % (i + 1, nm), std > 8 and dark < 60,
        "mean=%.1f std=%.1f 近黑占比 %.1f%%" % (mean, std, dark))

if len(srcs) >= 2 and img is not None:
    a = img[BAND:BAND + TILE[1], 0:TILE[0]]
    b = img[BAND:BAND + TILE[1], TILE[0]:2 * TILE[0]]
    same = float((np.abs(a - b).max(axis=2) < 10).mean()) * 100.0
    chk("③ 前两格不是同一张画面", same < 95, "逐像素相同占比 %.1f%%" % same)

print("\n拼图已落盘: /tmp/canvas_3cam.png")
print("结论: %s" % ("三相机在画布上全部出画面 ✅" if not fails else "失败 %d 项 ❌ → %s" % (len(fails), fails)))
raise SystemExit(0 if not fails else 1)
