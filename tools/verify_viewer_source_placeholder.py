#!/usr/bin/env python3
"""验证「没连真机时, 选真机不许放 metaworld 画面」修复 (2026-09-17)

老倪问: 没接真机, 选了真机为什么还在放 metaworld 视频?
根因: 切输入源只切了链路, **没清画面** —— 真机路径只在"帧文件签名变化"时才重画,
      没有新帧 → 屏上一直挂着切源前那副 metaworld 画面 (状态栏文字虽写了"无新帧", 画面骗人)。
修法: ①切源即清画面/签名/框 + 显示新源占位提示
      ②真机无新鲜帧 (超 10s / meta.ok=false) → 换"真机无帧"占位画面, 只让**新鲜**真机帧上屏
      ③冻结(标定中)时不动画面 (标定员正在标的帧不许被顶掉)

真窗口真代码跑 (offscreen + 临时帧目录), 不碰 Orin/Docker (置 _chain_stopped=True + 桩掉起链路方法)。
跑法: cd /home/ubuntu/lerobot-smolvla-lew && gui-venv311/bin/python tools/verify_viewer_source_placeholder.py
"""
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
TMP = tempfile.mkdtemp(prefix="ss_live_")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["DISPLAY"] = ":0"
os.environ["ZMAX_SS_REMOTE_DIR"] = TMP            # 真机帧文件改到临时目录
os.environ["ZMAX_ANNOT_ROOT"] = os.path.join(TMP, "annot")
sys.path.insert(0, os.path.join(HERE, "gui"))

import numpy as np                                       # noqa: E402
import cv2                                               # noqa: E402
from PyQt5 import QtWidgets                              # noqa: E402

import yolo_input_viewer as yiv                          # noqa: E402

app = QtWidgets.QApplication(sys.argv[:1])
ok = True


def check(name, cond, extra=""):
    global ok
    ok &= bool(cond)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name} {extra}")


def frame_bytes(w):
    """子窗当前显示的像素 (判定画面有没有真的换掉)"""
    pm = w.pixmap()
    if pm is None or pm.isNull():
        return None
    img = pm.toImage()
    ptr = img.constBits()
    ptr.setsize(img.byteCount())
    return bytes(ptr)


JPG, META = yiv.LIVE_JPG, yiv.LIVE_META
print(f"临时帧目录: {TMP}")

win = yiv.YoloInputViewer(None, module=None, source="sim")
win._chain_stopped = True          # 禁止自愈重连
# 起链路 (ssh/docker) 换桩 — 本测试只验画面语义, 不能真去连 Orin
yiv._RemoteChain.ensure = classmethod(lambda cls: "测试桩: 不起链路")
yiv._RemoteChain.stop = classmethod(lambda cls: None)

print("\n── ① 切源必须清掉上一路画面 ──")
# 先摆一副"仿真帧"在屏上 (模拟切源前的状态)
win._rgb = np.full((64, 64, 3), 210, np.uint8)
win._paint_frames()
_before = frame_bytes(win.w_orig)
win._view_tag = "sim-idle"
win.cb.setCurrentIndex(0)          # 用户选 真机 → 触发 _switch → _stop_source + _start_source(桩)
app.processEvents()
time.sleep(0.3)
app.processEvents()
_after = frame_bytes(win.w_orig)
check("切到真机 → 画面已换 (旧仿真帧不再留在屏上)",
      _before is not None and _after is not None and _before != _after)
check("画面标记 = waiting-real", win._view_tag == "waiting-real", f"tag={win._view_tag}")

print("\n── ② 真机无新鲜帧 (老帧 + meta.ok=false) → 占位, 不显示旧帧 ──")
cv2.imwrite(JPG, np.full((48, 48, 3), 30, np.uint8))            # 放一个"旧真机帧"
os.utime(JPG, (time.time() - 3 * 3600, time.time() - 3 * 3600))  # 3 小时前
json.dump({"ok": False, "reason": "服务 /zmax/live_frame 不可达", "age_s": 9999.0},
          open(META, "w"))
win._tick_real()
app.processEvents()
check("无新鲜帧 → tag=stale-real (占位画面)", win._view_tag == "stale-real", f"tag={win._view_tag}")
_st = win.st.text()
check("状态栏写明链路无数据 + 原因", ("无数据" in _st or "无新帧" in _st) and ("不可达" in _st),
      repr(_st[:80]))

print("\n── ③ 帧陈旧但 meta 说 ok → 也不许上屏冒充实时 ──")
json.dump({"ok": True, "age_s": 9999.0, "src": "d405", "w": 48, "h": 48}, open(META, "w"))
win._tick_real()
app.processEvents()
check("stale(age>5s) → 仍为占位", win._view_tag == "stale-real", f"tag={win._view_tag}")

print("\n── ④ 真机新鲜帧 → 正常上屏 (真机源没坏) ──")
_r, _ = 12, 34
_known = np.zeros((48, 48, 3), np.uint8)
_known[:, :24] = 255                       # 左半白右半黑 — 便于比对
cv2.imwrite(JPG, _known[:, :, ::-1])       # cv2 写 BGR
json.dump({"ok": True, "age_s": 0.2, "src": "d405", "w": 48, "h": 48, "device": "Orin UVC",
           "seq": 7, "jpeg_bytes": 900, "encode_ms": 3, "quality": 80, "server_fps": 10},
          open(META, "w"))
win._tick_real()
app.processEvents()
check("新鲜帧 → tag=real", win._view_tag == "real", f"tag={win._view_tag}")
check("新鲜帧画面 = 真机帧 (不是占位)", frame_bytes(win.w_orig) is not None
      and win._rgb is not None and int(win._rgb[:, :10].mean()) > 200,
      f"左上角均值={None if win._rgb is None else int(win._rgb[:, :10].mean())}")

print("\n── ⑤ 冻结(标定中) → 画面不许被占位顶掉 ──")
win._frozen = True
json.dump({"ok": False, "reason": "断流", "age_s": 9999.0}, open(META, "w"))
win._view_tag = "real"
win._tick_real()
app.processEvents()
check("冻结时保持原帧", win._view_tag == "real", f"tag={win._view_tag}")
win._frozen = False

print("\n── ⑥ 切回仿真 → 清掉真机画面并给仿真占位 ──")
win.cb.setCurrentIndex(1)
app.processEvents()
time.sleep(0.2)
app.processEvents()
check("切回仿真 → waiting-sim", win._view_tag == "waiting-sim", f"tag={win._view_tag}")

win.close()
shutil.rmtree(TMP, ignore_errors=True)
print("\n总判定:", "全绿 ✅" if ok else "有失败 ❌")
sys.exit(0 if ok else 1)
