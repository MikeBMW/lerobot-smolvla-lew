#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_feishu_button.py — ①-4 取证: 控制台「🔔 发飞书」按钮端到端 (真推送 + 真回执)

判据:
  ① 按钮存在且在界面上 (标题/提示)
  ② 无判据图时点它 → 日志给指引, 不发消息 (不静默失败)
  ③ 有判据图时点它 → 存下当前判据图 PNG → 后台线程真推送 → 日志出现 ✅ + message_id
  ④ 推送用的图 = 当前判据图 (文件名与内容可核)
"""
import glob
import os
import sys
import time

sys.path.insert(0, "/home/ubuntu/zmax_rel/tools/gui")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5 import QtWidgets  # noqa: E402

app = QtWidgets.QApplication(sys.argv)
import aoi_inspect_console as A  # noqa: E402

ok = []


def chk(n, c, d=""):
    ok.append(bool(c))
    print("  %s %s%s" % ("✅" if c else "❌", n, (" — " + d) if d else ""), flush=True)


w = A.AoiInspectConsole()
w.show()
app.processEvents()

print("① 按钮在位")
btns = [b for b in w.findChildren(QtWidgets.QPushButton) if "发飞书" in b.text()]
chk("找到「🔔 发飞书」按钮", bool(btns), btns[0].text() if btns else "")
chk("带说明提示(tooltip)", bool(btns) and "后台" in (btns[0].toolTip() or ""), btns[0].toolTip() if btns else "")

print("② 无判据图时点击 → 只给指引")
w._last_rgb = None
btns[0].click() if btns else None
app.processEvents()
txt = w.txt_log.toPlainText()
chk("日志提示'没有判据图'", "没有判据图" in txt, txt.strip().splitlines()[-1][:60] if txt.strip() else "")

print("③ 有判据图时点击 → 真推送")
src = sorted(glob.glob("/home/ubuntu/zmax_rel/reports/opt_view/金手指_topview.png"))
import cv2  # noqa: E402
img = cv2.imread(src[0]) if src else None
chk("有真判据图可加载", img is not None, os.path.basename(src[0]) if src else "")
if img is not None:
    w._last_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    before = set(glob.glob("/home/ubuntu/zmax_rel/reports/opt_view/console_push_*.png"))
    btns[0].click()
    t0 = time.time()
    while time.time() - t0 < 45:
        app.processEvents()
        if "发飞书: ✅" in w.txt_log.toPlainText() or "✅ 发飞书" in w.txt_log.toPlainText():
            break
        time.sleep(0.2)
    log = w.txt_log.toPlainText()
    after = set(glob.glob("/home/ubuntu/zmax_rel/reports/opt_view/console_push_*.png"))
    new = sorted(after - before)
    chk("存下当前判据图 PNG", bool(new), os.path.basename(new[-1]) if new else "")
    chk("日志出现推送成功 + message_id", ("✅ 发飞书" in log) and ("message_id" in log),
        [l for l in log.splitlines() if "发飞书" in l][-1][:110] if "发飞书" in log else "无")
    if new:
        g = cv2.imread(new[-1])
        chk("推送图与判据图同源 (尺寸一致)", g is not None and img is not None and g.shape == img.shape,
            "推送 %s vs 源 %s" % (g.shape if g is not None else None, img.shape))

print("\n判据通过: %d/%d" % (sum(ok), len(ok)))
sys.stdout.flush()
os._exit(0 if all(ok) else 3)
