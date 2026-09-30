#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_station_button.py — 交互级: 真调一次「🛰 工位总览」按钮的 handler

验三件独立的事 (自报日志不算证据):
  ① 6 路总览页真可达 (8793/station → 200, 且页面含 6 格 + 控制区)
  ② 浏览器**新窗口真开了** (wmctrl 里出现"工位总览"窗口, 且不是调用前就有的)
  ③ 该窗口被搬到**控制台那块屏**并最大化 (几何 = XSpace Studio 那块屏)
用法: DISPLAY=:0 QT_QPA_PLATFORM=offscreen python verify_station_button.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, "/home/ubuntu/zmax/tools/gui")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("DISPLAY", ":0")

from PyQt5 import QtWidgets                                                      # noqa: E402

app = QtWidgets.QApplication(sys.argv)
import simulink_module as SM                                                     # noqa: E402

KEY = "工位总览"
logs: list = []
fails: list = []


def chk(name, cond, detail=""):
    print(("  %-40s %s %s" % (name, "✅" if cond else "❌", detail)).rstrip())
    if not cond:
        fails.append(name)


def wins(g=False):
    cmd = ["wmctrl", "-lG"] if g else ["wmctrl", "-l"]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout.splitlines()
    except Exception:
        return []


# ── 清场: 关掉已有的总览窗, 保证是"冷启动"真开新窗 ──
for _l in [x for x in wins() if KEY in x]:
    subprocess.run(["wmctrl", "-i", "-c", _l.split(None, 1)[0]], timeout=5)
time.sleep(3)
before = {l.split(None, 1)[0] for l in wins()}
print("调用前 %s 窗口数: %d" % (KEY, len([x for x in wins() if KEY in x])))

m = SM.SimulinkModule()
try:
    m.log_signal.connect(lambda s: logs.append(s))
except Exception as e:                                                           # noqa: BLE001
    print("  (日志信号挂不上, 只看结果: %s)" % e)

t0 = time.time()
m.open_station_page()
for _ in range(70):                       # 最多等 ~35s
    app.processEvents()
    time.sleep(0.5)
    if any(("总览页已打开" in s) or ("没能打开" in s) for s in logs):
        break
dt = time.time() - t0

print("\n--- 按钮真打的日志 ---")
for s in logs:
    print("   ", s)

print("\n--- 窗口表(含 %s) ---" % KEY)
gl = [x for x in wins(True) if KEY in x]
for x in gl:
    print("   ", x)

st = None
try:
    with urllib.request.urlopen("http://127.0.0.1:8793/station", timeout=6) as r:
        st = r.status
        body = r.read().decode("utf-8", "replace")
except Exception as e:                                                           # noqa: BLE001
    st, body = "%s" % e, ""

new = [x for x in gl if x.split()[0] not in before]
studio = [x for x in wins(True) if "XSpace Studio" in x]
geo_same = False
if new and studio:
    _n = new[0].split()
    _s = studio[0].split()
    geo_same = (abs(int(_n[2]) - int(_s[2])) <= 40 and abs(int(_n[3]) - int(_s[3])) <= 60
                and int(_n[4]) >= int(_s[4]) * 0.9)

print("\n--- 断言 ---")
chk("① 总览页可达 (8793/station → 200)", st == 200, "实际: %s" % st)
chk("① 页面含 6 格 + 控制区", ("金手指" in body and "表面" in body and "授权" in body),
    "金手指/表面/授权 %s/%s/%s" % ("金手指" in body, "表面" in body, "授权" in body))
chk("② 浏览器新窗真开 (冷启动)", bool(new), "新窗: %s" % (new[0].split()[0] if new else "无"))
chk("③ 搬到控制台那块屏 + 最大化", geo_same,
    "新窗 %s vs 控制台 %s" % (new[0].split()[2:6] if new else "无",
                              studio[0].split()[2:6] if studio else "无"))
chk("③ 点了就出声(日志有进度回执)", any("浏览器已启动" in s for s in logs) and
    any("总览页已打开" in s for s in logs))
print("\n点击 → 页面已打开: %.1fs" % dt)
print("\n结论: %s" % ("全部通过 ✅" if not fails else "未通过 ❌ %s" % fails))
sys.exit(1 if fails else 0)
