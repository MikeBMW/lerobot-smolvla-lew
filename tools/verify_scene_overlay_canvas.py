#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_scene_overlay_canvas.py — 「🧩 场景叠加」落到画布上的取证 (离屏真跑, 不猜)

层级 (照 state-space-canvas-engineering):
  ① 语法/导入  ② 渲染(节点项/连线项数)  ③ 双击关键字命中  ④ 真跑: 拉 8791 帧 → 节点
  ⑤ 画布像素级差异 (证明真画上了, 不是只写日志)  ⑥ 关掉后复位

判据:
  - 渲染 项数 == 文件节点/连线数 (回归: 不许把画布改坏)
  - match_node("🎥 真实场景叠加 · 双眼 (sim2real)") 命中本节点 handler
  - 6s 内节点 video_pixmap 非空 + 应用帧数 ≥ 8 (4Hz 拉帧)
  - 节点区域像素差异 > 1% (真画上了) · 关掉后 video_pixmap 复位为 None
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback

sys.path.insert(0, "/home/ubuntu/zmax/tools/gui")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5 import QtWidgets                                                     # noqa: E402
from PyQt5.QtCore import QEventLoop, QRectF, QTimer                             # noqa: E402
from PyQt5.QtGui import QImage, QPainter                                        # noqa: E402

app = QtWidgets.QApplication(sys.argv)
import node_logic as NL                                                          # noqa: E402
import simulink_module as SM                                                     # noqa: E402

FLOW = "/home/ubuntu/zmax/flows/state_space_obs.json"
spec = json.load(open(FLOW, encoding="utf-8"))
fails: list[str] = []


def chk(name, cond, detail=""):
    print(("%-46s %s %s" % (name, "✅" if cond else "❌", detail)).rstrip())
    if not cond:
        fails.append(name)


# ── ① 导入 + ② 渲染 ─────────────────────────────────────────────
m = SM.SimulinkModule()
err = None
try:
    m.load_flow_file(FLOW, confirm=False)
except Exception:                                                                # noqa: BLE001
    err = traceback.format_exc()
app.processEvents()
n_items, n_links = len(m._items), len(m._link_items)
chk("① 导入/加载 无异常", err is None, "" if not err else err[-300:])
chk("② 渲染 节点项 == 文件节点数", n_items == len(spec["nodes"]),
    "%d/%d" % (n_items, len(spec["nodes"])))
chk("② 渲染 连线项 > 0 (回归: 连线不许全丢)", n_links > 0,
    "%d 连线项 / 文件 %d" % (n_links, len(spec["links"])))

# ── ③ 双击关键字命中 ────────────────────────────────────────────
node_name = None
for _n in spec["nodes"]:
    if _n.get("id") == "n_realscene":
        node_name = _n.get("name")
key = NL.match_node(node_name or "")
chk("③ match_node 命中本节点 handler", key == "n_realscene_live", "%s → %s" % (node_name, key))

# ── ④ 真跑: 拉帧进节点 ─────────────────────────────────────────
item = m._ov_live_target_item()
chk("④ 画布上找到「真实场景叠加」节点", item is not None, getattr(item, "node", {}).get("id", "-"))
if item is None:
    print("\n".join(fails))
    raise SystemExit(1)


def node_img():
    """把节点区域离屏渲染成 QImage (取像素级证据)"""
    w, h = int(item.w) + 8, int(item.h) + 8
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(0)
    p = QPainter(img)
    m.canvas._scene.render(p, QRectF(0, 0, w, h),
                           QRectF(item.node["x"] - 4, item.node["y"] - 4, w, h))
    p.end()
    return img


def raw(img):
    img = img.convertToFormat(QImage.Format_RGB32)
    ptr = img.bits()
    ptr.setsize(img.byteCount())
    return bytes(ptr)


before_shape = (int(item.w), int(item.h))
before = raw(node_img())

ok = m.start_canvas_live_overlay(src="overlay_arm", fps=4.0)
chk("④ start_canvas_live_overlay 返回 True", ok is True)

t0 = time.time()
loop = QEventLoop()
QTimer.singleShot(6500, loop.quit)
loop.exec_()
app.processEvents()
el = time.time() - t0

d = m._ov_live
d["bytes"] = d.get("bytes")       # 保留引用
frames = d.get("applied_seq", 0) - 0
chk("④ 节点拿到实时帧 (video_pixmap 非空)",
    item.video_pixmap is not None and not item.video_pixmap.isNull(),
    "%sx%s" % (item.video_pixmap.width() if item.video_pixmap else "-",
               item.video_pixmap.height() if item.video_pixmap else "-"))
chk("④ 应用帧数 ≥ 8 (%.1fs 内 4Hz)" % el, d.get("frames", 0) >= 8, "frames=%d" % d.get("frames", 0))
chk("④ 取帧无失败", d.get("fetch_err", 0) == 0, "fetch_err=%d" % d.get("fetch_err", 0))
chk("④ 节点已放大 (看得清画面)", (int(item.w), int(item.h)) != before_shape,
    "%s → %s" % (before_shape, (int(item.w), int(item.h))))
print("   真值带: %s" % item.video_overlay)

# ── ⑤ 画布像素级差异 ───────────────────────────────────────────
after = raw(node_img())
n = min(len(before), len(after))
diff_px = sum(1 for i in range(0, n, 4) if before[i:i + 3] != after[i:i + 3])
total_px = n // 4
pct = 100.0 * diff_px / max(1, total_px)
chk("⑤ 节点区域像素差异 > 1% (真画上了)", pct > 1.0, "%.2f%% (%d/%d px)" % (pct, diff_px, total_px))

# ── ⑥ 关掉复位 ─────────────────────────────────────────────────
m.stop_canvas_live_overlay()
app.processEvents()
chk("⑥ 停止后 video_pixmap 复位", item.video_pixmap is None)
chk("⑥ 停止后 active=False", m.canvas_live_overlay_active() is False)

print("\n结论: %s" % ("全部通过 ✅" if not fails else "失败 %d 项 ❌ → %s" % (len(fails), fails)))
raise SystemExit(0 if not fails else 1)
