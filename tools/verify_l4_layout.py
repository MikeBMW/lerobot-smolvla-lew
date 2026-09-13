# -*- coding: utf-8 -*-
"""真画布取证 (L4/L3 INTACT 区摆位 + 连线方向): 加载 flows/state_space_obs.json → 用画布自身几何算每条连线的 ax/bx
(右出线连左入线 = ax > bx), 并渲染 L4/L3 区 PNG。

用法: QT_QPA_PLATFORM=offscreen QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_l4_layout.py
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = "/home/ubuntu/lerobot-smolvla-lew"
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)

from PyQt5.QtCore import QRectF, Qt          # noqa: E402
from PyQt5.QtGui import QImage, QPainter     # noqa: E402
from PyQt5.QtWidgets import QApplication     # noqa: E402

app = QApplication(sys.argv)
import simulink_module as sm                 # noqa: E402

m = sm.SimulinkModule()
m.resize(4200, 2600)
m.open_state_space()
app.processEvents()
sc = m.canvas.scene()

node = {}
for i in sc.items():
    if type(i).__name__ == "SimNodeItem":
        node[i.node["id"]] = i
print(f"画布: 节点 {len(node)} · 连线 {sum(1 for i in sc.items() if type(i).__name__=='SimLinkItem')}")

WATCH = {"L4 条件": "解码器→DiT", "metaworld 真渲染帧": "数据源→INTACT", "意图/潜空间/动作块": "INTACT→解码器",
         "潜空间 z": "VLM→DiT", "接触流形坐标": "接触流形→DiT", "性能流形代价": "性能流形→DiT",
         "⬆ 几何 手/销/孔 (z R7)": "2D3D→流形预测", "预测流形 (JEPA)": "流形预测→流形",
         "action→前馈层": "DiT→前馈"}
print("\n关键连线 (画布真实几何; ax = 源右缘, bx = 目标左缘):")
rows = []
for li in sc.items():
    if type(li).__name__ != "SimLinkItem":
        continue
    lk, s, d = li.link, li.src, li.dst
    ax = s.scenePos().x() + getattr(s, "w", 0)
    bx = d.scenePos().x()
    lbl = lk.get("label", "")
    if lbl in WATCH:
        state = "❌ 右出线连左入线" if ax > bx + 1 else ("✅ 竖直" if abs(ax - bx) <= 1 else f"✅ 前向 {round(bx-ax)}px")
        print(f"  {WATCH[lbl]:<16} {s.node['name'][:16]:<18}→{d.node['name'][:16]:<18} ax={ax:>5.0f} bx={bx:>5.0f} {state}")
        rows.append((WATCH[lbl], ax, bx, state))

print("\n画布真实几何 (节点名 / x / 渲染 w×h):")
for i in node.values():
    nm = i.node.get("name", "")
    if any(k in nm for k in ("INTACT", "Flow-Matching", "流形专家", "接触流形", "性能流形", "VLM 通用", "前馈加速器", "metaworld 数据源")):
        print(f"  {nm[:32]:<34} x={i.scenePos().x():>6.0f} w={getattr(i,'w',0):>4} h={getattr(i,'h',0):>4} y={i.scenePos().y():>7.0f}")

# 全画布真实反向连线
back = []
for li in sc.items():
    if type(li).__name__ != "SimLinkItem":
        continue
    lk, s, d = li.link, li.src, li.dst
    ax = s.scenePos().x() + getattr(s, "w", 0)
    bx = d.scenePos().x()
    if ax > bx + 1:
        back.append((round(ax - bx), s.node["name"][:18], d.node["name"][:18], lk.get("label", "")[:18]))
print(f"\n画布真实反向连线 {len(back)} 条:")
for b in sorted(back, key=lambda z: -z[0]):
    print(f"   退{b[0]:>5}px  {b[1]:<20}→{b[2]:<20} [{b[3]}]")

ts = time.strftime("%Y%m%d_%H%M%S")
os.makedirs(os.path.join(ROOT, "reports"), exist_ok=True)
region = QRectF(-120, -900, 1560, 760)
img = QImage(int(region.width()), int(region.height()), QImage.Format_ARGB32)
img.fill(Qt.black)
p = QPainter(img)
p.setRenderHint(QPainter.Antialiasing, True)
sc.render(p, QRectF(0, 0, region.width(), region.height()), region)
p.end()
out = os.path.join(ROOT, "reports", f"canvas_l4_l3_layout_{ts}.png")
img.save(out)
print(f"\n→ {out} ({img.width()}x{img.height()})")
