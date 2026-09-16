#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧩 验证 L4 档「🧩 L2 兼容 (前馈 MLP + YOLO)」勾选框 (offscreen, gui-venv311)

判据 (老倪规矩: 新增控件必须 ①创建 ②挂布局 ③行为生效, 少一件都是静默失败):
  ①对象存在 + 文字 ②parent() 非空 (真挂进布局) ③与 chk_intact_exec 同一工具栏 (同排)
  ④默认勾选 ⑤tooltip 写明实测代价与等效环境变量 ⑥点击可切换 (行为生效)
  ⑦装配块静态连线: 源码里读了控件状态 + 该状态参与了 _l2_compat 判定
用法: QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/verify_l2_compat_checkbox.py
"""
from __future__ import annotations

import inspect
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "tools", "gui"), os.path.join(ROOT, "tools"),
                os.path.join(ROOT, "src")]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
import simulink_module as sm  # noqa: E402

ok = True


def chk(name, cond, extra=""):
    global ok
    print(f"  {'✅' if cond else '❌'} {name}{(' · ' + extra) if extra else ''}")
    ok &= bool(cond)


m = sm.SimulinkModule()
cb = getattr(m, "chk_l2_compat", None)
chk("① 勾选框存在", cb is not None)
if cb is not None:
    chk("① 文字 = 🧩 L2 兼容 (前馈 MLP + YOLO)", cb.text() == "🧩 L2 兼容 (前馈 MLP + YOLO)",
        repr(cb.text()))
    chk("② 已挂进布局 (parent 非空)", cb.parent() is not None,
        type(cb.parent()).__name__ if cb.parent() is not None else "None")
    chk("③ 与 chk_intact_exec 同一工具栏", cb.parent() is getattr(m, "chk_intact_exec").parent())
    chk("④ 默认勾选", cb.isChecked())
    tt = cb.toolTip() or ""
    chk("⑤ tooltip 写明实测代价", ("6.82" in tt) and ("0.42" in tt) and ("SS_L4_L2_COMPAT" in tt),
        f"{len(tt)} 字符")
    cb.setChecked(False)
    chk("⑥ 取消勾选后状态可读 False", cb.isChecked() is False)
    cb.setChecked(True)
    chk("⑥ 重新勾选后状态可读 True", cb.isChecked() is True)

src = inspect.getsource(sm.SimulinkModule)
chk("⑦ 装配块读了控件状态", 'getattr(self, "chk_l2_compat", None)' in src)
chk("⑦ 状态参与 _l2_compat 判定", "_l2_compat_on\n" in src or "_l2_compat_on," in src
    or "and self._l2_compat_on" in src)
chk("⑦ 判定仍受环境变量总开关约束", 'os.environ.get("SS_L4_L2_COMPAT", "1") != "0"' in src)

print(f"\n结论: {'全部通过 ✅' if ok else '有判据未过 ❌'}")
sys.exit(0 if ok else 1)
