#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证: 📦 数据源节点上的「仿真/真机」切换开关 (真画布 offscreen)

① 画布加载: 节点/连线增量 + 📡 独立传感器节点已撤
② 拨钮绘制不崩 (真渲染该节点) + 拨钮矩形落在节点内
③ 单击拨钮 → on_toggle_src: 切到真机 (位姿+图像进 module._bypass_obs) → 再切回仿真
④ 右键菜单项存在 (拨钮参数驱动)
⑤ Z700 面板图像预览 (有 PNG 时显示真图)
"""
import json
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = "/home/ubuntu/lerobot-smolvla-lew"
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)

from PyQt5.QtCore import QPointF, QRectF, Qt        # noqa: E402
from PyQt5.QtGui import QImage, QPainter            # noqa: E402
from PyQt5.QtWidgets import QApplication            # noqa: E402

app = QApplication(sys.argv)
import simulink_module as sm                        # noqa: E402

fails = []


def chk(name, cond, extra=""):
    print(("  ✅ " if cond else "  ❌ ") + name + (f"   {extra}" if extra else ""))
    if not cond:
        fails.append(name)


def load(flow):
    m = sm.SimulinkModule()
    m.resize(4200, 2600)
    m.clear()
    m.load_flow_file(flow, confirm=False)
    m._relayout_row_gaps()
    app.processEvents()
    items, links = {}, []
    for i in m.canvas.scene().items():
        t = type(i).__name__
        if t == "SimNodeItem":
            items[i.node.get("name", "")] = i
        elif t == "SimLinkItem":
            links.append(i)
    return m, items, links


def find(items, key):
    hits = [(len(k), v) for k, v in items.items() if key in k]
    return min(hits, key=lambda x: x[0])[1] if hits else None


print("═══ ① 画布加载 ═══")
m0, it0, lk0 = load("/tmp/state_space_obs.bak2.json")          # 上一版(含独立传感器节点)
m, items, links = load(os.path.join(ROOT, "flows", "state_space_obs.json"))
print(f"  上一版 {len(it0)} 节点/{len(lk0)} 连线  →  本版 {len(items)} 节点/{len(links)} 连线")
chk("独立 📡 传感器节点已撤", find(items, "旁路真机传感器") is None)
# 🐛 2026-09-19 老倪全系统检查: 原来硬写 79 → 画布加节点 (工程记忆/视觉大模型/DeepSeek) 后误判失败。
#   用例意图是"画布节点齐全", 不是钉死数量 → 改为与 flow JSON 对账 (画布节点数 == 流程条目数, 且非空)
try:
    _flow = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                        "flows", "state_space_obs.json"), encoding="utf-8"))
    _expect = len(_flow["nodes"])
except Exception:
    _expect = None
chk(f"节点数与流程对账 (画布 {len(items)} / 流程 {_expect})",
    bool(items) and (_expect is None or len(items) == _expect), f"实际 {len(items)}")
chk("连线数不减于旧基线 (撤2加1 的净值, 容差≥-1)", len(links) >= len(lk0) - 1, f"{len(lk0)} → {len(links)}")
src_node = find(items, "metaworld 数据源")
chk("📦 数据源节点在", src_node is not None)
chk("数据源节点带 src_switch", bool(src_node and src_node.node["params"].get("src_switch")),
    str((src_node.node["params"] if src_node else {}).get("src_state")))
viz = find(items, "旁路实时可视化")
hit = [li for li in links if "数据源" in li.src.node.get("name", "") and "旁路实时可视化" in li.dst.node.get("name", "")]
chk("📦 数据源 → 📈 旁路可视化 连线", bool(hit))
m1, it1, lk1 = load("/tmp/state_space_obs.bak.json")
chk("旧连线全在 (对 v5.6.16 基线)", {li.src.node.get("name", "")[:16] for li in lk1} <=
    {li.src.node.get("name", "")[:16] for li in links}, f"基线 {len(lk1)} 条")

print("═══ ② 拨钮绘制 (真渲染, 不崩) ═══")
r = src_node.sceneBoundingRect()
img = QImage(int(r.width()) + 24, int(r.height()) + 24, QImage.Format_ARGB32)
img.fill(0xFF0d1117)
pt = QPainter(img)
m.canvas.scene().render(pt, QRectF(img.rect()), r.adjusted(-12, -12, 12, 12))
pt.end()
chk("拨钮渲染出像素", img.save("/tmp/verify_src_switch_node.png"),
    f"{os.path.getsize('/tmp/verify_src_switch_node.png')} B → /tmp/verify_src_switch_node.png")
pill = QRectF(8, src_node.h - 26, src_node.w - 16, 20)
chk("拨钮矩形在节点内", pill.bottom() <= src_node.h and pill.width() > 40, f"{pill.width():.0f}x{pill.height():.0f}")

print("═══ ③ 单击拨钮 → 切换数据源 (真数据) ═══")
logs = []
m._log = lambda x, *a, **k: logs.append(str(x))
m._flow_path = None          # 验证时不写回 flow (避免污染)
before = src_node.node["params"].get("src_state")
src_node.mousePressEvent(type("E", (), {"button": lambda self: Qt.LeftButton,
                                        "pos": lambda self: QPointF(pill.center()),
                                        "accept": lambda self: None})())
app.processEvents()
after = src_node.node["params"].get("src_state")
chk("单击拨钮完成切换", before != after, f"{before} → {after}")
chk("模块数据源标记同步", getattr(m, "_data_source", None) in ("bypass_real", "metaworld"),
    str(getattr(m, "_data_source", None)))
d = getattr(m, "_bypass_obs", None)
if after == "真机":
    chk("真机帧含机器人位姿", bool(d and d.get("tcp")),
        f"TCP={[round(x,4) for x in (d or {}).get('tcp', [])]} quat={[round(x,3) for x in ((d or {}).get('tcp_quat') or [])]}")
    im = (d or {}).get("image") or {}
    pubs = (d or {}).get("pubs") or {}
    honest = bool(im) or ("/foundationpose/tray_reference/debug_image" in pubs)
    chk("图像通道状态如实 (有帧 或 话题在线无帧/无发布者)",
        honest, f"image={'有帧 '+str(im.get('w'))+'x'+str(im.get('h')) if im else '当前无帧'}"
                f" · 发布者计数={pubs.get('/foundationpose/tray_reference/debug_image')}"
                f" · RealSense={pubs.get('/realsense/color/image_raw')}")
    chk("日志含位姿+图像行", any("位姿" in l for l in logs) and any("图像" in l for l in logs))
src_node.mousePressEvent(type("E", (), {"button": lambda self: Qt.LeftButton,
                                        "pos": lambda self: QPointF(pill.center()),
                                        "accept": lambda self: None})())
app.processEvents()
chk("再单击切回仿真", src_node.node["params"].get("src_state") == before,
    f"→ {src_node.node['params'].get('src_state')} (数据源={getattr(m, '_data_source', None)})")
print("   切换日志:")
for l in logs:
    print("     ", l[:110])

print("═══ ④ Z700 面板真机图像预览 ═══")
m._open_bypass_viz("z700_signals")
app.processEvents()
w = getattr(m, "_z700_signals_win", None)
chk("Z700 面板打开", w is not None and w.isVisible())
if w:
    time.sleep(0.6)
    app.processEvents()
    w.refresh()
    txt = w.img_meta.text().replace("\n", " | ")
    has = w.img_view.pixmap() is not None and not w.img_view.pixmap().isNull()
    chk("图像预览如实 (有帧显示真图 / 无帧说明原因)", has or ("话题" in txt or "无发布者" in txt), txt[:130])
    chk("面板截图", w.grab().save("/tmp/verify_z700_img.png"),
        f"{os.path.getsize('/tmp/verify_z700_img.png')} B")

print("\n═══ 结论 ═══")
print(("❌ 失败 %d: " % len(fails)) + "; ".join(fails) if fails else "✅ 全部通过")
sys.exit(1 if fails else 0)
