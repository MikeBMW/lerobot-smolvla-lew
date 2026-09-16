#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""旁路可视化接入回归验证 (offscreen, 真画布)

① 画布加载: 节点/连线数 + 三个新节点存在 + 三条新连线前向(ax≤bx)
② 零回归: 与备份 flow 对比 —— 旧节点几何逐项不变 (位置/尺寸)
③ 语义映射: 三个节点名 → NODE_LOGIC key 正确 (不被别的关键字抢先)
④ 真执行: 数据源节点读真机帧 (module._bypass_obs / _data_source=bypass_real) + 两个观察器窗口用真数据打开
⑤ 渲染 PNG 取证
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = "/home/ubuntu/lerobot-smolvla-lew"
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)

from PyQt5.QtWidgets import QApplication     # noqa: E402

app = QApplication(sys.argv)
import simulink_module as sm                 # noqa: E402
import node_logic as nl                      # noqa: E402

F = os.path.join(ROOT, "flows", "state_space_obs.json")
BK = "/tmp/state_space_obs.bak.json"
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
            # ⚠️ 画布加载会**重生成 node id** (实测 n1789560638710xxx) → 一律按名字索引
            items[i.node.get("name", "")] = i
        elif t == "SimLinkItem":
            links.append(i)
    return m, items, links


def find(items, key):
    """按名字子串找节点 (id 不可靠); 多个命中取最长公共前缀的那个"""
    hits = [(len(nm), it) for nm, it in items.items() if key in nm]
    return min(hits, key=lambda x: x[0])[1] if hits else None


print("═══ ② 备份 flow 先加载 (做增量基准) ═══")
m0, items0, links0 = load(BK)
print(f"  备份: 节点 {len(items0)} · 连线 {len(links0)}")

print("═══ ① 画布加载 (新 flow) ═══")
m, items, links = load(F)
print(f"  节点 {len(items)} · 连线 {len(links)}")
chk("节点数 = 80", len(items) == 80, f"实际 {len(items)}")
# ⚠️ 画布加载器会丢少量连线 (备份 97→94 同样丢 3) → 看**增量**才对
chk("连线比备份多 3 (加载器固定丢 3 条)", len(links) - len(links0) == 3, f"{len(links0)} → {len(links)}")
for key, nm in (("旁路真机传感器", "ssbyps"), ("旁路实时可视化", "ssbypv"), ("Z700 真机信号", "ssz700")):
    it = find(items, key)
    chk(f"新节点 {nm} 存在", it is not None,
        (f"x={it.scenePos().x():.0f} y={it.scenePos().y():.0f} w={getattr(it,'w',0)} h={getattr(it,'h',0)}"
         if it else ""))
# 新连线 (按名字)
for a, b in (("旁路真机传感器", "43D 统一状态向量"), ("旁路真机传感器", "旁路实时可视化"),
             ("物理世界", "Z700 真机信号")):
    hit = [li for li in links if a in li.src.node.get("name", "") and b in li.dst.node.get("name", "")]
    chk(f"新连线 {a}→{b}", bool(hit))
    for li in hit:
        ax = li.src.scenePos().x() + getattr(li.src, "w", 0)
        bx = li.dst.scenePos().x()
        chk(f"  前向 (ax≤bx) {a}→{b}", ax <= bx, f"ax={ax:.0f} bx={bx:.0f}")

print("═══ ② 零回归: 与备份 flow 对比旧节点几何 ═══")
moved = []
for nid, it in items0.items():
    it2 = items.get(nid)                 # 按**完整名字**匹配 (id 会被重生成, 前缀会撞名)
    if it2 is None:
        moved.append(f"{nid[:14]}(丢失)")
        continue
    a = (round(it.scenePos().x()), round(it.scenePos().y()), getattr(it, "w", 0), getattr(it, "h", 0))
    b = (round(it2.scenePos().x()), round(it2.scenePos().y()), getattr(it2, "w", 0), getattr(it2, "h", 0))
    if a != b:
        moved.append(f"{nid}:{a}→{b}")
# 例外: 「可视化层」色带宽度随新观察器扩展 (by design), 其余节点必须逐项不变
by_design = [m for m in moved if "可视化层" in m]
real_moved = [m for m in moved if "可视化层" not in m]
chk("旧节点几何零变化 (仅可视化层色带按设计加宽)", not real_moved,
    ("; ".join(real_moved[:6])) if real_moved else ("色带: " + "; ".join(by_design) if by_design else ""))
nm = lambda li: (li.src.node.get("name", "")[:16], li.dst.node.get("name", "")[:16])
oldsrc = {nm(li) for li in links0}
newsrc = {nm(li) for li in links}
chk("旧连线全在", oldsrc.issubset(newsrc), f"缺 {len(oldsrc - newsrc)}")

print("═══ ③ 语义映射 (节点名 → NODE_LOGIC key) ═══")
for nm, want in (("📡 旁路真机传感器 (Orin 远程只读 · 真机信号源)", "ss_bypass_sensor"),
                 ("📈 旁路实时可视化 (当前阶段/残差/接触概率)", "ss_bypass_viz"),
                 ("🖥 Z700 真机信号 (全信号观测 · 物理世界输出)", "ss_z700_signals")):
    got = nl.match_node(nm)
    chk(f"{nm[:22]}… → {want}", got == want, f"实际 {got}")
chk("三个 key 都已注册", all(k in nl.NODE_LOGIC for k in ("ss_bypass_sensor", "ss_bypass_viz", "ss_z700_signals")))
chk("源码映射齐 (右键打开 VSCode)",
    all(k in nl._EXTERNAL_LOC for k in ("ss_bypass_sensor", "ss_bypass_viz", "ss_z700_signals")))

print("═══ ④ 真执行 (真数据) ═══")
logs = []
m._log = lambda x, *a, **k: logs.append(str(x))
# 4.1 数据源节点: 读真机帧 + 切数据源
m.on_bypass_sensor_node(find(items, "旁路真机传感器").node)
chk("数据源已切到真机旁路", getattr(m, "_data_source", None) == "bypass_real", str(getattr(m, "_data_source", None)))
p = getattr(m, "_bypass_obs", None)
chk("真机帧已载入 (TCP + 新鲜度)", bool(p and p.get("tcp")),
    f"TCP={[round(x,4) for x in (p or {}).get('tcp', [])]} age={((p or {}).get('age_s'))}s gaps={list(((p or {}).get('gaps') or {}).keys())}")
# 4.2 两个观察器
m._open_bypass_viz("bypass")
app.processEvents()
w1 = getattr(m, "_bypass_view_win", None)
chk("旁路可视化窗口打开", w1 is not None and w1.isVisible())
if w1:
    time.sleep(0.6)
    app.processEvents()
    w1.refresh()
    chk("窗口已灌入真实旁路数据", w1.labs["stage"].text() != "-" and len(w1.curve.res) > 5,
        f"阶段={w1.labs['stage'].text()} 残差={w1.labs['residual'].text()} 接触p={w1.labs['contact_p'].text()} 曲线点={len(w1.curve.res)}")
    print("     零下行:", w1.labs["zero"].text())
m._open_bypass_viz("z700_signals")
app.processEvents()
w2 = getattr(m, "_z700_signals_win", None)
chk("Z700 真机信号窗口打开", w2 is not None and w2.isVisible())
if w2:
    time.sleep(0.6)
    app.processEvents()
    w2.refresh()
    chk("全信号面板有真值", w2.labs["tcp_x"].text() not in ("-", "缺"),
        f"TCP=({w2.labs['tcp_x'].text()},{w2.labs['tcp_y'].text()},{w2.labs['tcp_z'].text()}) "
        f"运行={w2.labs['s_op'].text()} 关节1={w2.labs['q0'].text()} 缺口={w2.labs['b_gaps2'].text()[:40]}")

print("═══ ⑤ 渲染 PNG ═══")
for nm, w in (("bypass", w1), ("z700", w2)):
    if w is not None:
        path = f"/tmp/verify_{nm}.png"
        ok = w.grab().save(path)
        print(f"  {path} {ok} {os.path.getsize(path) if os.path.exists(path) else 0} B")
# 画布局部 (L4 区 + 可视化层)
from PyQt5.QtCore import QRectF                     # noqa: E402
from PyQt5.QtGui import QImage, QPainter            # noqa: E402
sc = m.canvas.scene()
r = sc.itemsBoundingRect()
img = QImage(int(r.width()), int(r.height()), QImage.Format_ARGB32)
img.fill(0xFF0d1117)
pt = QPainter(img)
sc.render(pt, QRectF(img.rect()), r)
pt.end()
img.save("/tmp/verify_canvas_full.png")
print(f"  /tmp/verify_canvas_full.png {os.path.getsize('/tmp/verify_canvas_full.png')} B (画布全图, 含新节点)")

print("\n═══ 结论 ═══")
print(("❌ 失败 %d 项: " % len(fails)) + "; ".join(fails) if fails else "✅ 全部通过")
sys.exit(1 if fails else 0)
