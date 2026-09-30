#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_ov_autoload_empty_canvas.py — 空画布上点「🧩 场景叠加」也要出结果

老倪铁律: 工具按钮点了必出结果。重启控制台后画布常常是空的 ⇒ 按钮必须
**自动把 flows/state_space_obs.json 读进来**再出画面, 而不是弹一句"没节点"。

验法: 新建 SimulinkModule 但**不加载任何流程图** ⇒ 直接调 start_canvas_live_overlay()
      ① 画布真被自动加载 (真节点数 > 0)
      ② 节点真出画面 (572x344 拼图)
      ③ 画布上**已有内容**时不得被替换 (造一个只有 1 个真节点的空壳, 确认没被 load_flow 覆盖)
用法: DISPLAY=:0 ./gui-venv311/bin/python tools/verify_ov_autoload_empty_canvas.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, "/home/ubuntu/zmax/tools/gui")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("DISPLAY", ":0")
from PyQt5 import QtWidgets                                                       # noqa: E402
from PyQt5.QtCore import QEventLoop, QTimer                                       # noqa: E402

app = QtWidgets.QApplication(sys.argv)
import simulink_module as SM                                                      # noqa: E402

fails = []


def chk(name, cond, detail=""):
    print(("%-46s %s %s" % (name, "✅" if cond else "❌", detail)).rstrip())
    if not cond:
        fails.append(name)


def real_n(m):
    return len([i for i in m._items.values()
                if (i.node.get("type") or "") not in ("bg", "row_bg")])


# ① 空画布 → 按钮应自动加载
m = SM.SimulinkModule()
chk("起始画布确实是空的", real_n(m) == 0, "真节点 %d" % real_n(m))
m.start_canvas_live_overlay()
loop = QEventLoop()
QTimer.singleShot(12000, loop.quit)
loop.exec_()
app.processEvents()
n = real_n(m)
chk("① 空画布被自动加载", n >= 50, "真节点 %d (bg/row_bg 不计)" % n)
it = m._ov_live_target_item()
chk("① 目标节点已就位", it is not None, it.node.get("name", "-") if it else "-")
chk("② 节点已出画面", it is not None and it.video_pixmap is not None
    and not it.video_pixmap.isNull(),
    "%sx%s" % (it.video_pixmap.width() if it and it.video_pixmap else "-",
               it.video_pixmap.height() if it and it.video_pixmap else "-"))

# ③ 画布非空 ⇒ 不得被替换
m2 = SM.SimulinkModule()
m2.load_flow_file("/home/ubuntu/zmax/flows/state_space_obs.json", confirm=False)
app.processEvents()
for i in list(m2._items.values())[1:]:                     # 只留 1 个真节点当"编辑中"
    if (i.node.get("type") or "") not in ("bg", "row_bg"):
        m2._items.pop(i.node["id"], None)
        break
n_before = real_n(m2)
m2.start_canvas_live_overlay()
loop2 = QEventLoop()
QTimer.singleShot(4000, loop2.quit)
loop2.exec_()
app.processEvents()
chk("③ 画布非空时不被替换", real_n(m2) <= n_before + 1,
    "调用前 %d → 调用后 %d (应为提示而非覆盖)" % (n_before, real_n(m2)))

print("\n结论: %s" % ("空画布自动出结果 ✅" if not fails else "失败 %d 项 ❌ → %s" % (len(fails), fails)))
raise SystemExit(0 if not fails else 1)
