#!/usr/bin/env python3
"""真实窗口实测: 拖到扩展屏会不会被 _clamp_to_screen 拽回主屏 (2026-09-17)

为什么需要这个: 单元测试只证逻辑, 证不了"真窗口 + 真屏幕 + 真5s轮询节拍"下的行为。
本脚本开一个真实 QDialog (1348x945), 复刻 _tick 的节奏 (66ms 定时器 + 5s 节流调 clamp),
然后自己用 wmctrl 把窗口移到 HDMI (x=2000), 观察 14s 内的实际位置。

  CLAMP_VARIANT=new  → 用磁盘上修好的 yolo_input_viewer._clamp_to_screen
  CLAMP_VARIANT=old  → 用 git HEAD 里的老实现 (对照组, 应看到 ≤5s 跳回主屏)

跑法: DISPLAY=:0 gui-venv311/bin/python tools/verify_viewer_clamp_live_window.py
"""
import os
import re
import subprocess
import sys
import textwrap
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
os.environ.setdefault("DISPLAY", ":0")
sys.path.insert(0, os.path.join(HERE, "gui"))

from PyQt5 import QtCore, QtWidgets                     # noqa: E402
import yolo_input_viewer as yiv                         # noqa: E402

VARIANT = os.environ.get("CLAMP_VARIANT", "new")
TITLE = "🧪 clamp 实测窗口"
MOVE_TO_X = 2000
WATCH_S = 14


def old_clamp_source():
    """从 git HEAD 取老版 _clamp_to_screen (对照组用的就是当初闯祸的那段代码)"""
    src = subprocess.check_output(["git", "show", "HEAD:tools/gui/yolo_input_viewer.py"],
                                 cwd=REPO).decode("utf-8")
    m = re.search(r"\n    def _clamp_to_screen\(self, silent=True\):.*?(?=\n    def )", src, re.S)
    if not m:
        raise SystemExit("没在 git HEAD 里找到 _clamp_to_screen")
    return textwrap.dedent(m.group(0))


class Probe(QtWidgets.QDialog):
    def __init__(self):
        super().__init__(None, QtCore.Qt.Window)
        self.setWindowTitle(TITLE)
        self.resize(1348, 945)
        self.move(300, 100)
        self._last_clamp = 0.0
        self.t = QtCore.QTimer(self)
        self.t.setInterval(66)                         # 与 yolo_input_viewer 同款 15Hz
        self.t.timeout.connect(self._tick)
        self.t.start()

    def _log_line(self, s):
        print(f"        [窗口日志] {s}", flush=True)

    def _tick(self):
        if time.time() - self._last_clamp > 5.0:       # 与 _tick 同款 5s 节流
            self._last_clamp = time.time()
            self._clamp_to_screen(silent=False)


# ── 绑定被测实现 ──────────────────────────────────────────────────────────
if VARIANT == "old":
    ns = {"QtWidgets": QtWidgets}
    exec(old_clamp_source(), ns)
    Probe._clamp_to_screen = ns["_clamp_to_screen"]
else:
    Probe._screens = yiv.YoloInputViewer._screens
    Probe._visible_ratio = staticmethod(yiv.YoloInputViewer._visible_ratio)
    Probe._clamp_to_screen = yiv.YoloInputViewer._clamp_to_screen

app = QtWidgets.QApplication(sys.argv[:1])
win = Probe()
win.show()
app.processEvents()

wid = ""
for _ in range(20):
    app.processEvents()
    try:
        wid = subprocess.check_output(["xdotool", "search", "--name", TITLE]).decode().split()[0]
        if wid:
            break
    except Exception:
        pass
    time.sleep(0.3)
if not wid:
    raise SystemExit("拿不到本窗口 id (xdotool 失败)")

scr = [(s.name(), s.geometry().x(), s.geometry().y(), s.geometry().width(), s.geometry().height())
       for s in app.screens()]
print(f"变体={VARIANT}  屏={scr}")
print(f"初始位置: x={win.x()} y={win.y()} {win.width()}x{win.height()}  (窗口 id {wid})")
print(f"→ wmctrl 移到扩展屏 x={MOVE_TO_X} …")

subprocess.run(["wmctrl", "-i", "-r", wid, "-e", f"0,{MOVE_TO_X},100,-1,-1"], check=False)

t0 = time.time()
samples = []
while time.time() - t0 < WATCH_S:
    app.processEvents()
    samples.append((round(time.time() - t0, 1), win.x(), win.y()))
    time.sleep(0.5)

print("时间轴 (x 坐标):")
for t, x, _y in samples:
    flag = "扩展屏✅" if x >= 1920 else "主屏⬅"
    print(f"   t={t:4.1f}s  x={x:5d}  {flag}")

on_ext = [x for t, x, _y in samples if t >= 3.0]
stayed = all(x >= 1920 for x in on_ext)
print(f"\n结果[{VARIANT}]: {'✅ 3s 后一直停在扩展屏, 未被拽回' if stayed else '❌ 被拽回主屏'}")
app.quit()
sys.exit(0 if stayed else 1)
