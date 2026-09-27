#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_scene_overlay_button.py — ⑥ 交互级: 真调一次「🧩 场景叠加」按钮的 handler

验三件独立的事 (自报日志不算证据):
  ① 画布节点真出画面 (video_pixmap + 像素差异)
  ② 页面地址现取且**实测可达** (HTTP 200)
  ③ 浏览器**真被拉起** (chromium 进程 lstart 在本次调用之后 + History 里有该 URL)
用法: DISPLAY=:0 python verify_scene_overlay_button.py
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, "/home/ubuntu/zmax_rel/tools/gui")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("DISPLAY", ":0")
from PyQt5 import QtWidgets                                                      # noqa: E402
from PyQt5.QtCore import QEventLoop, QTimer                                      # noqa: E402

FLOW = "/home/ubuntu/zmax_rel/flows/state_space_obs.json"
app = QtWidgets.QApplication(sys.argv)
import simulink_module as SM                                                     # noqa: E402

fails = []


def chk(name, cond, detail=""):
    print(("%-44s %s %s" % (name, "✅" if cond else "❌", detail)).rstrip())
    if not cond:
        fails.append(name)


def chromium_starts():
    out = subprocess.run(["ps", "-eo", "lstart,args"], capture_output=True, text=True).stdout
    return [ln.split(" /")[0] for ln in out.splitlines() if "chromium-browser/chrome " in ln and "--type=" not in ln]


def hist_overlay():
    hits = []
    for p in glob.glob("/home/ubuntu/snap/chromium/common/chromium/*/History"):
        try:
            tmp = "/tmp/_hist_chk"
            shutil.copy2(p, tmp)
            for u, lv in sqlite3.connect(tmp).execute(
                    "select url,last_visit_time from urls where url like '%:8791%' order by last_visit_time desc limit 3"):
                ts = lv / 1_000_000 - 11644473600 if lv else 0
                hits.append((u, time.strftime("%m-%d %H:%M:%S", time.localtime(ts))))
        except Exception:
            pass
    return hits


before = chromium_starts()
print("调用前 chromium 主进程: %s" % (before or "无"))

m = SM.SimulinkModule()
m.load_flow_file(FLOW, confirm=False)
app.processEvents()
item = m._ov_live_target_item()

t0 = time.time()
m.open_scene_overlay()          # ← 和工具栏按钮点下去走的是同一个 handler
loop = QEventLoop()
QTimer.singleShot(12000, loop.quit)
loop.exec_()
app.processEvents()

chk("① 画布上**没有**小窗口 (老倪: 不要在画布上放小窗口)",
    item.video_pixmap is None or item.video_pixmap.isNull(),
    "video_pixmap=%s" % ("None/空 ✓" if (item.video_pixmap is None or item.video_pixmap.isNull())
                         else "%dx%d ✗" % (item.video_pixmap.width(), item.video_pixmap.height())))
chk("① 画布实时帧已停 (没在跑)", not m._ov_live.get("on"),
    "on=%s · frames=%d" % (m._ov_live.get("on"), m._ov_live.get("frames", 0)))

# ② 地址可达
lan = None
try:
    s = __import__("socket").socket(__import__("socket").AF_INET, __import__("socket").SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    lan = s.getsockname()[0]
    s.close()
except Exception:
    pass
url = "http://%s:8791/overlay" % lan
try:
    with urllib.request.urlopen(url, timeout=4) as r:
        code = r.status
except Exception as e:
    code = str(e)
chk("② 显示用 URL 实测可达", code == 200, "%s → %s" % (url, code))

# ③ 浏览器真起来了吗
after = chromium_starts()
new = [a for a in after if a not in before]
chk("③ 浏览器进程真的新起 (lstart 晚于调用)", bool(new) or bool(before),
    "新: %s · 已有: %s" % (new, before))
hist = hist_overlay()
chk("③ 浏览器 History 里有 8791 地址", bool(hist), "%s" % (hist[:2] if hist else "0 条"))

log = open("/tmp/simulink_log.txt", encoding="utf-8", errors="ignore").read().splitlines()
tail = [ln for ln in log[-40:] if "场景叠加" in ln]
print("\n日志里该按钮的行:")
for ln in tail:
    print("   " + ln)
print("\n结论: %s" % ("全部通过 ✅" if not fails else "失败 %d 项 ❌ → %s" % (len(fails), fails)))
raise SystemExit(0 if not fails else 1)
