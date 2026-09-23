#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""状态空间画布节点定位体检 (真画布几何, 不是读 JSON 推算)

回答三问用:
  ① 节点真实落在哪条行带 (row_bg 矩形包含判定)
  ② 输出/输入连线数 (断头 = 有入无出 / 孤立 = 无入无出)
  ③ 反向连线 (源右缘 > 目标左缘) 计数
用法: QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/canvas_node_audit.py [flow.json] [node_id...]
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = "/home/ubuntu/lerobot-smolvla-lew"
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)

from PyQt5.QtWidgets import QApplication          # noqa: E402

app = QApplication(sys.argv)
import simulink_module as sm                      # noqa: E402

FLOW = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].endswith(".json") else os.path.join(ROOT, "flows", "state_space_obs.json")
WATCH = [a for a in sys.argv[1:] if not a.endswith(".json")] or ["长程序列规划器", "肌肉记忆技能库", "状态校正器"]

m = sm.SimulinkModule()
m.resize(4200, 2600)
m.clear()
m.load_flow_file(FLOW, confirm=False)
m._relayout_row_gaps()
app.processEvents()
sc = m.canvas.scene()

items, links = {}, []
for i in sc.items():
    t = type(i).__name__
    if t == "SimNodeItem":
        items[i.node["id"]] = i
    elif t == "SimLinkItem":
        links.append(i)

print("画布: 节点 %d · 连线 %d  (%s)" % (len(items), len(links), os.path.basename(FLOW)))

geo = {}
for k, it in items.items():
    geo[k] = (it.scenePos().x(), it.scenePos().y(), getattr(it, "w", 0), getattr(it, "h", 0),
              it.node.get("type"), it.node.get("name", "")[:40])
# 画布加载会重映射 node id → 关注项按**节点名**匹配 (铁律)
by_name = {}
for k, v in geo.items():
    by_name.setdefault(v[5], k)
WATCH_IDS = []
for w in WATCH:
    hit = [k for k, v in geo.items() if w in v[5]]
    WATCH_IDS.extend(hit[:1] if hit else [w])

bands = {k: v for k, v in geo.items() if v[4] == "row_bg" or v[4] == "bg"}
print("\n== 行带 (真几何) ==")
for k, v in sorted(bands.items(), key=lambda kv: kv[1][1]):
    print("   %-14s x=%-6.0f y=%-6.0f w=%-6.0f h=%-6.0f %s" % (k, v[0], v[1], v[2], v[3], v[5]))

ins, outs = {}, {}
for li in links:
    f, t = li.src.node["id"], li.dst.node["id"]
    outs.setdefault(f, []).append(t)
    ins.setdefault(t, []).append(f)

print("\n== 关注节点 ==")
for k in WATCH_IDS:
    if k not in geo:
        print("   %s: 不存在" % k); continue
    x, y, w, h, typ, name = geo[k]
    inside = [(bk, bv[5]) for bk, bv in bands.items()
              if bv[0] - 20 <= x <= bv[0] + bv[2] and bv[1] - 20 <= y <= bv[1] + bv[3]]
    print("   ■ %-13s %s" % (k, name))
    print("     真位置 x=%.0f y=%.0f w=%.0f h=%.0f | 落在带: %s"
          % (x, y, w, h, [b[1][:30] for b in inside] or "无(带外)"))
    print("     入 %d %s" % (len(ins.get(k, [])), ins.get(k, [])))
    print("     出 %d %s" % (len(outs.get(k, [])), outs.get(k, [])))
    _in, _out = len(ins.get(k, [])), len(outs.get(k, []))
    print("     判定: %s" % ("孤立(无入无出)" if not _in and not _out else
                             "断头(有入无出)" if _in and not _out else
                             "悬空(有出无入)" if _out and not _in else "连通"))

print("\n== 反向连线 (源右缘 > 目标左缘) ==")
back = []
for li in links:
    f, t = li.src.node["id"], li.dst.node["id"]
    if f not in geo or t not in geo:
        continue
    if geo[f][4] in ("row_bg", "bg") or geo[t][4] in ("row_bg", "bg"):
        continue
    ax = geo[f][0] + geo[f][2]
    bx = geo[t][0]
    if ax > bx:
        back.append((f, t, ax - bx))
for f, t, d in sorted(back, key=lambda z: -z[2]):
    print("   %-14s → %-14s 右→左 %.0fpx  (%s → %s)" % (f, t, d, geo[f][5][:24], geo[t][5][:24]))
print("   共 %d 条" % len(back))

print("\n== 全画布连通体检 ==")
dead, orphan = [], []
for k, v in geo.items():
    if v[4] in ("row_bg", "bg"):
        continue
    _i, _o = len(ins.get(k, [])), len(outs.get(k, []))
    if _i and not _o:
        dead.append(v[5])
    if not _i and not _o:
        orphan.append(v[5])
print("   断头(有入无出) %d: %s" % (len(dead), dead))
print("   孤立(无入无出) %d: %s" % (len(orphan), orphan))
print("   悬空(有出无入) %d: %s"
      % (len([1 for k, v in geo.items() if v[4] not in ("row_bg", "bg")
              and not len(ins.get(k, [])) and len(outs.get(k, []))]),
         [v[5] for k, v in geo.items() if v[4] not in ("row_bg", "bg")
          and not len(ins.get(k, [])) and len(outs.get(k, []))]))

# 各节点入/出线在 JSON 数组中的先后 → 端口 slot (决定连线起点 y)
print("\n== 端口 slot (连线数组顺序) ==")
for k in WATCH_IDS:
    if k not in geo:
        continue
    o = [(j, t) for j, t in enumerate(outs.get(k, []))]
    i2 = [(j, f) for j, f in enumerate(ins.get(k, []))]
    print("   %-13s 出slot=%s 入slot=%s" % (k, o, i2))
