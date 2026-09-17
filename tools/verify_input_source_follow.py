#!/usr/bin/env python3
"""验证「输入图像窗口跟随画布数据源」修复 (2026-09-17)

三块:
  ① 画布状态取值 _canvas_src_state(module)  —— 真代码, module 用桩
  ② open_input_viewer 复用窗口时的**源对齐** —— 真代码 (窗口对象用桩, 避免真开 GUI)
  ③ 仿真源真出帧 —— 真 _SimGrabber 跑几秒, 确认拿到的就是 metaworld 渲染帧 (老倪要的"仿真视频")

跑法: cd /home/ubuntu/lerobot-smolvla-lew && gui-venv311/bin/python tools/verify_input_source_follow.py
"""
import os
import queue
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(HERE, "gui"))

ok = True

# ── ① 画布状态取值 ───────────────────────────────────────────────────────
import simulink_module as sm                                   # noqa: E402


class MStub:
    def __init__(self, nodes=None, data_source=""):
        self.nodes = nodes or []
        self._data_source = data_source


cases = [
    ("src_state=仿真 → 仿真", MStub([{"params": {"src_state": "仿真"}}]), "仿真"),
    ("src_state=真机 → 真机", MStub([{"params": {"src_state": "真机"}}]), "真机"),
    ("无 src_state 节点 → 默认仿真 (与画布一致)",
     MStub([{"params": {"mode": "train"}}]), "仿真"),
    ("无节点但 _data_source=bypass_real → 真机", MStub([], "bypass_real"), "真机"),
]
print("── ① 画布输入源状态 ──")
for name, mod, want in cases:
    got = sm._canvas_src_state(mod)
    good = got == want
    ok &= good
    print(f"  [{'PASS' if good else 'FAIL'}] {name} → got={got}")

# ── ② 复用窗口时的源对齐 ─────────────────────────────────────────────────
import yolo_input_viewer as yiv                                # noqa: E402


class FakeCb:
    def __init__(self, i):
        self.i = i
        self.switches = 0

    def currentIndex(self):
        return self.i

    def setCurrentIndex(self, i):
        if i != self.i:
            self.switches += 1
        self.i = i


class FakeWin:
    def __init__(self, idx):
        self.cb = FakeCb(idx)
        self.raised = False

    def isVisible(self):
        return True

    def show(self):
        pass

    def raise_(self):
        self.raised = True

    def activateWindow(self):
        pass


print("\n── ② open_input_viewer 复用窗口 → 源对齐 ──")
for have, want_src, want_idx, label in [
        (0, "sim", 1, "旧窗在真机, 画布切仿真 → 必须切到仿真"),
        (1, "real", 0, "旧窗在仿真, 画布切真机 → 必须切到真机"),
        (1, "sim", 1, "两边都仿真 → 不许乱切")]:
    w = FakeWin(have)
    yiv.YoloInputViewer._cur = w
    yiv.open_input_viewer(None, module=None, source=want_src)
    good = (w.cb.i == want_idx) and w.raised
    ok &= good
    print(f"  [{'PASS' if good else 'FAIL'}] {label}: idx {have}→{w.cb.i} (切换次数 {w.cb.switches})")
yiv.YoloInputViewer._cur = None

# ── ③ 仿真源真出帧 (metaworld 渲染) ─────────────────────────────────────
print("\n── ③ 仿真源真出帧 (_SimGrabber → metaworld) ──")
q = queue.Queue(maxsize=6)
g = yiv._SimGrabber(q, False)
g.start()
frames, err, meta = 0, None, {}
t0 = time.time()
while time.time() - t0 < 40 and frames < 3:
    try:
        item = q.get(timeout=20)
    except queue.Empty:
        err = "20s 没出帧"
        break
    if "err" in item:
        err = item["err"]
        break
    frames += 1
    meta = item.get("info", {})
    if frames == 1:
        rgb = item.get("rgb")
        print(f"  帧1: shape={None if rgb is None else rgb.shape} src={meta.get('src')} device={meta.get('device')}")
g.stop_flag = True
good = frames >= 3 and not err
ok &= good
print(f"  [{'PASS' if good else 'FAIL'}] 40s 内拿到 {frames} 帧仿真帧  错误={err}")

print("\n总判定:", "全绿 ✅" if ok else "有失败 ❌")
sys.exit(0 if ok else 1)
