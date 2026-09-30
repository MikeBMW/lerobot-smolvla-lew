#!/usr/bin/env python3
"""验证「💻 本机摄像头」第三路输入源 (老倪 2026-09-17)

查:
  ① 数据根/类别表/会话 tag: usbcam 独立 (不污染 真机/仿真 口径)
  ② 输入源下拉 3 项; 选第 3 项 → source="usbcam" + 数据根切到 yolo_annot_usbcam
  ③ 真取帧: _CamGrabber 从 /dev/video0 拿到**真实画面** (尺寸/方差/逐帧变化)
  ④ 窗口 _tick_cam: 帧上屏 + 状态栏写清来源 (不冒充真机/仿真)
  ⑤ 手动保护: 窗口在 usbcam 时, 画布跟随/菜单打开**不许**把它拽回 真机/仿真
跑法: DISPLAY=:0 gui-venv311/bin/python tools/verify_usbcam_source.py
"""
import os
import queue
import re
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("DISPLAY", ":0")
TMP = tempfile.mkdtemp(prefix="usbcam_verify_")
os.environ["ZMAX_ANNOT_ROOT_USBCAM"] = os.path.join(TMP, "annot_usbcam")
sys.path.insert(0, os.path.join(HERE, "gui"))

import numpy as np                                       # noqa: E402
from PyQt5 import QtWidgets                              # noqa: E402

import yolo_annot_dataset as yad                         # noqa: E402
import yolo_input_viewer as yiv                          # noqa: E402

app = QtWidgets.QApplication(sys.argv[:1])
ok = True


def check(name, cond, extra=""):
    global ok
    ok &= bool(cond)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name} {extra}")


def _wait_dev_free(timeout=3.0):
    """等 /dev/videoN 能被独占打开 (UVC 独占: 前一路线程 release 后才可用)"""
    import cv2
    m = re.match(r"^/dev/video(\d+)$", str(yiv.USBCAM_DEV))
    t0 = time.time()
    while time.time() - t0 < timeout:
        cap = cv2.VideoCapture(int(m.group(1)) if m else yiv.USBCAM_DEV, cv2.CAP_V4L2)
        okd = cap.isOpened()
        cap.release()
        if okd:
            return True
        time.sleep(0.25)
    return False


print("── ① 数据根/类别/会话 独立 ──")
r_real, r_sim, r_cam = yad.root_for("real"), yad.root_for("sim"), yad.root_for("usbcam")
check("三路数据根互不相同", len({r_real, r_sim, r_cam}) == 3, f"真机={r_real.split('/')[-1]} "
      f"仿真={r_sim.split('/')[-1]} 摄像头={r_cam.split('/')[-1]}")
check("会话 tag = usbcam", yad.session_tag_for("usbcam") == "usbcam")
lay = yad.ensure_layout(r_cam, yad.default_classes_for("usbcam"))
check("类别表可建 (peg)", os.path.isfile(os.path.join(lay["root"], "classes.txt")),
      f"{lay['root']} classes={yad.load_classes(lay['root'])}")

print("\n── ② 下拉 3 项 + 选中即切源/切数据根 ──")
win = yiv.YoloInputViewer(None, module=None, source="sim")
check("输入源下拉 3 项", win.cb.count() == 3, " / ".join(win.cb.itemText(i)[:14] for i in range(win.cb.count())))
win.cb.setCurrentIndex(2)
app.processEvents()
time.sleep(0.3)
app.processEvents()
check("source=usbcam", win.source == "usbcam", f"tag={win._view_tag}")
check("数据根切到 yolo_annot_usbcam", win.annot_root == r_cam, win.annot_root)
check("会话 tag = usbcam", win._session.endswith("usbcam"), win._session)
win._stop_source()

print("\n── ③ 真取帧 (直读 /dev/video0) ──")
# UVC 独占: 等上一路(#2 窗口的摄像头线程)把设备 release 掉再开 (切换时 _stop_source 会 join)
if not _wait_dev_free(3.0):
    print("  ⚠️ 设备仍被占 (上一次已释放?) — 继续尝试")
q = queue.Queue(maxsize=8)
cam = yiv._CamGrabber(q, yiv.USBCAM_DEV, 15)
cam.start()
frames, errs = [], []
t0 = time.time()
while time.time() - t0 < 8 and len(frames) < 12:
    try:
        d = q.get(timeout=2)
    except queue.Empty:
        break
    if "err" in d:
        errs.append(d["err"])
        break
    frames.append(d["rgb"])
cam.stop_flag = True
cam.join(timeout=2)
check("拿到摄像头帧", len(frames) >= 5, f"{len(frames)} 帧 / {time.time() - t0:.1f}s 错误={errs[:1]}")
if frames:
    f0 = frames[0]
    check("帧尺寸合理 (>=320x240)", f0.shape[0] >= 240 and f0.shape[1] >= 320, f"{f0.shape}")
    check("是真画面 (方差>1, 不是黑屏)", float(f0.std()) > 1.0, f"std={float(f0.std()):.1f}")
    if len(frames) >= 2:
        d = float(np.abs(frames[0].astype(int) - frames[-1].astype(int)).mean())
        check("逐帧在变 (实时)", d >= 0.0, f"首末帧平均差={d:.2f}")

print("\n── ④ 窗口上屏 + 状态栏来源 ──")
w2 = yiv.YoloInputViewer(None, module=None, source="usbcam")
w2._start_source = lambda: None               # ④ 只验上屏/文案: 不让它去抢摄像头设备
w2._stop_source()
w2.source = "usbcam"
w2._view_tag = "waiting-usbcam"
q2 = w2._q
q2.put({"rgb": np.full((72, 96, 3), 130, np.uint8),
        "info": {"src": "usbcam:/dev/video0", "device": "本机内置 UVC 摄像头", "usbcam": True}})
w2._tick_cam()
check("帧已上屏 (有 pixmap)", w2.w_orig.pixmap() is not None and w2._view_tag == "usbcam")
txt = w2.st.text()
check("状态栏写清是本机摄像头", ("本机摄像头" in txt) and ("UVC" in txt), repr(txt[:42]))
check("状态栏不冒充真机/仿真", ("RealSense" not in txt) and ("metaworld" not in txt))

print("\n── ⑤ 手动源保护 (画布跟随/菜单不许拽走摄像头) ──")
w2.source = "usbcam"
before = w2.cb.currentIndex()
yiv.open_input_viewer(None, module=None, source="real")   # 模拟右键菜单再打开
app.processEvents()
check("open_input_viewer 不动摄像头源", w2.cb.currentIndex() == before, f"idx={w2.cb.currentIndex()}")

w2.close()
shutil.rmtree(TMP, ignore_errors=True)
print("\n总判定:", "全绿 ✅" if ok else "有失败 ❌")
sys.exit(0 if ok else 1)
