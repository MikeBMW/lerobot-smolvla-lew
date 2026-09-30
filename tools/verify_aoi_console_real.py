#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_aoi_console_real.py — 真桌面验证 (192DPI, 记取"offscreen 全绿≠人能用"教训)

判据:
  ① 窗口完整在屏内 (availableGeometry 内)
  ② 所有按钮不被截断 (实际宽 ≥ sizeHint 宽)
  ③ 截图落盘 (人眼看得到的证据)
用法: DISPLAY=:0 ./gui-venv311/bin/python tools/verify_aoi_console_real.py
"""
from __future__ import annotations

import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(ROOT, "tools"), os.path.join(ROOT, "tools", "gui"),
           os.path.join(ROOT, "src", "lerobot", "policies", "yolo_3d")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("ZMAX_ANNOT_ROOT_AOI", os.path.join(ROOT, "data", "yolo_aoi_annot"))

from PyQt5 import QtWidgets, QtGui, QtCore                                  # noqa: E402
import aoi_inspect_console as aic                                        # noqa: E402

CHECKS = {}


def ck(n, c, d=""):
    CHECKS[n] = bool(c)
    print(f"  {'✅' if c else '❌'} {n}" + (f" — {d}" if d else ""))


def main():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    w = aic.AoiInspectConsole(source="real")
    w._timer.stop()
    w.resize(1500, 900)
    w.show()
    for _ in range(20):
        app.processEvents(); time.sleep(0.05)

    scr = QtWidgets.QApplication.desktop().availableGeometry(w)
    g = w.frameGeometry()
    inside = (g.x() >= scr.x() - 2 and g.y() >= scr.y() - 2
              and g.right() <= scr.right() + 2 and g.bottom() <= scr.bottom() + 2)
    ck("① 窗口完整在屏内", inside, f"窗口 {g.x()},{g.y()} {g.width()}x{g.height()} vs 屏 {scr.width()}x{scr.height()}")

    btns = {**w.skill_btns, "save": w.btn_save, "savenext": w.btn_savenext, "newcls": w.btn_newcls,
            "setcls": w.btn_setcls, "undo": w.btn_undo, "del": w.btn_del, "clear": w.btn_clear,
            "build": w.btn_build, "check": w.btn_check, "train": w.btn_train, "live": w.btn_live,
            "datadir": w.btn_datadir, "expjson": w.btn_expjson, "expcsv": w.btn_expcsv,
            "opt_grab": w.btn_opt_grab, "opt_recent": w.btn_opt_recent, "opt_verd": w.btn_opt_verd,
            "opt_crop": w.btn_opt_crop, "opt_region": w.btn_opt_region, "opt_meta": w.btn_opt_meta,
            "tp_record": w.btn_tp_rec, "tp_goto": w.btn_tp_goto, "tp_copy": w.btn_tp_cmd,
            "roi_keep": w.btn_roi_keep, "roi_clear": w.btn_roi_clear}
    trunc = {k: (b.width(), b.sizeHint().width()) for k, b in btns.items() if b.width() < b.sizeHint().width() - 1}
    ck("② 按钮不被截断 (实际宽≥提示宽)", not trunc, f"{len(btns)} 个; 截断: {trunc or '无'}")

    png = os.path.join(ROOT, "reports", f"aoi_console_real_{time.strftime('%Y%m%d_%H%M%S')}.png")
    ok = w.grab().save(png)
    ck("③ 截图落盘", ok and os.path.getsize(png) > 10000, png)

    # ④ 最大化真能用 (老倪 v2 反馈: "最大化按钮不好使") — 必须真实 DISPLAY 下判 isMaximized
    w.showMaximized()
    for _ in range(20):
        app.processEvents(); time.sleep(0.05)
    is_max = w.isMaximized()
    wide = w.width() >= QtWidgets.QApplication.primaryScreen().availableGeometry().width() - 60
    ck("④ 最大化真生效 (isMaximized + 宽≈屏宽)", is_max and wide,
       f"isMaximized={is_max} 宽={w.width()} 屏宽={QtWidgets.QApplication.primaryScreen().availableGeometry().width()}")
    w.showNormal()
    for _ in range(10):
        app.processEvents(); time.sleep(0.03)

    # ⑤ 窗口类型必须是 Qt.Window (QDialog 的 Dialog 类型在 X11 下最大化不响应 = 根因)
    #   ⚠️ 判据坑: 不能用 `flags & Qt.Dialog` 判定 —— Qt.Dialog = Window|Dialog, 会同时命中 Window 位;
    #   必须取类型字段 WindowType_Mask (低 8 位) 比较。
    _t = int(w.windowFlags()) & int(QtCore.Qt.WindowType_Mask)
    ck("⑤ 窗口类型 = Qt.Window (最大化根因)", _t == int(QtCore.Qt.Window),
       f"type={hex(_t)} flags={hex(int(w.windowFlags()))}")

    out = png.replace(".png", ".json")
    json.dump({"checks": CHECKS, "pass": f"{sum(CHECKS.values())}/{len(CHECKS)}",
               "screen": [scr.width(), scr.height()], "window": [g.x(), g.y(), g.width(), g.height()],
               "btn_widths": {k: [b.width(), b.sizeHint().width()] for k, b in btns.items()},
               "screenshot": png}, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"  判据通过: {sum(CHECKS.values())}/{len(CHECKS)}\n  证据: {out}")
    w.close()
    return 0 if all(CHECKS.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
