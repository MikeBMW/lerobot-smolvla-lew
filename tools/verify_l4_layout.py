# -*- coding: utf-8 -*-
"""🎯 状态空间画布摆位 + 连线体检 (真画布几何, 贝塞尔采样; 不是读 JSON 推算)。

为什么要"真画布": 加载时画布会自己重排 —— 普通节点强制 ≥280×110 (simulink_module.py:5146),
`_relayout_row_gaps(min_gap=56)` 按 round(y/60) 分桶把桶内后一个节点推到"前一个右缘+56"(12044 行),
所以 JSON 里的 x/w 只是输入。本工具复现用户视角 (load_flow_file + _relayout_row_gaps) 后逐条量:
  ① 反向连线: ax(源右缘) > bx(目标左缘) = "右出线连左入线"
  ② 方框重叠  ③ 连线穿框 (路径穿过第三个节点)  ④ 连线交叉 (两两曲线相交, 排除共端点)
  ⑤ 关键链 ax/bx 表  ⑥ L4/L3 区 PNG + 全画布 PNG

端口几何 (3289 行 SimLinkItem._path): ay = src.y + h·(i+1)/(n+1), by = dst.y + h·(j+1)/(m+1)
  i/j = 该连在该节点出入线里的序号, n/m = 总数 → **只取决于 link 在 JSON 数组里的先后**, 与 in1/in2 命名无关。

用法: QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_l4_layout.py [flow.json]
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

FLOW = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "flows", "state_space_obs.json")
m = sm.SimulinkModule()
m.resize(4200, 2600)
m.clear()
m.load_flow_file(FLOW, confirm=False)
m._relayout_row_gaps()      # 复现用户视角 (open_state_space() 加载后同样调用)
app.processEvents()
sc = m.canvas.scene()

items, links = {}, []
for i in sc.items():
    t = type(i).__name__
    if t == "SimNodeItem":
        items[i.node["id"]] = i
    elif t == "SimLinkItem":
        links.append(i)
print(f"画布: 节点 {len(items)} · 连线 {len(links)}   ({os.path.basename(FLOW)})")

NODES = [(it.node["id"], it.node.get("name", "")[:22], it.scenePos().x(), it.scenePos().y(),
          getattr(it, "w", 0), getattr(it, "h", 0))
         for it in items.values() if it.node.get("type") != "row_bg"]
PATHS = {id(li): [li._path().pointAtPercent(k / 48.0) for k in range(49)] for li in links}


def pair(li):
    return li.src.node.get("name", "")[:18], li.dst.node.get("name", "")[:18]


# ① 反向连线
print("\n① 反向连线 (ax > bx = 右出线连左入线):")
back = []
for li in links:
    ax = li.src.scenePos().x() + getattr(li.src, "w", 0)
    bx = li.dst.scenePos().x()
    if ax > bx + 1:
        back.append((ax - bx, pair(li), str(li.link.get("label", ""))[:24]))
for d, (s, t), lb in sorted(back, key=lambda z: -z[0]):
    print(f"   ❌ 退 {d:>6.0f}px  {s} → {t}  [{lb}]")
print(f"   合计 {len(back)} 条")

# ② 方框重叠
print("\n② 方框重叠:")
ov = [(a[1], b[1]) for i, a in enumerate(NODES) for b in NODES[i + 1:]
      if a[2] < b[2] + b[4] and b[2] < a[2] + a[4] and a[3] < b[3] + b[5] and b[3] < a[3] + a[5]]
for a, b in ov:
    print(f"   ❌ {a} ⨯ {b}")
print(f"   合计 {len(ov)} 对")

# ③ 连线穿框
print("\n③ 连线穿框 (路径穿过非端点节点):")
occ = []
for li in links:
    ends = (li.src.node["id"], li.dst.node["id"])
    hit = sorted({nname for nid, nname, x, y, w, h in NODES if nid not in ends and
                  sum(1 for p in PATHS[id(li)][3:-3] if x < p.x() < x + w and y < p.y() < y + h) >= 3})
    if hit:
        occ.append((pair(li), hit))
for (s, t), hits in occ:
    print(f"   ⚠️  {s} → {t}  穿过 {hits}")
print(f"   合计 {len(occ)} 条")

# ④ 连线交叉
def seg_int(p1, p2, p3, p4):
    def cr(o, a, b):
        return (a.x() - o.x()) * (b.y() - o.y()) - (a.y() - o.y()) * (b.x() - o.x())
    d1, d2, d3, d4 = cr(p3, p4, p1), cr(p3, p4, p2), cr(p1, p2, p3), cr(p1, p2, p4)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


print("\n④ 连线交叉:")
cross = []
for i in range(len(links)):
    for k in range(i + 1, len(links)):
        a, b = links[i], links[k]
        if {a.src.node["id"], a.dst.node["id"]} & {b.src.node["id"], b.dst.node["id"]}:
            continue
        pa, pb = PATHS[id(a)], PATHS[id(b)]
        if any(seg_int(pa[u], pa[u + 1], pb[v], pb[v + 1])
               for u in range(len(pa) - 1) for v in range(len(pb) - 1)):
            cross.append((pair(a), pair(b)))
print(f"   合计 {len(cross)} 对")
for (s1, t1), (s2, t2) in cross[:12]:
    print(f"   ⚠️  [{s1}→{t1}] ⨯ [{s2}→{t2}]")

# ⑤ 关键链 ax/bx
WATCH = [("metaworld 真渲染帧", "数据源 → INTACT 策略"), ("意图/潜空间/动作块", "INTACT 策略 → 意图解码器"),
         ("L4 条件", "意图解码器 → DiT (L4→L3 条件)"), ("潜空间 z", "VLM → DiT"),
         ("接触流形坐标", "接触流形 → DiT"), ("性能流形代价", "性能流形 → DiT"),
         ("action→前馈层", "DiT → 前馈加速器"), ("u_ff 建议", "前馈加速器 → 动作调制器"),
         ("阶段切换与动作融合", "动作调制器 → 安全边界"), ("action 直通执行端", "DiT → 机器人执行器"),
         ("技能执行指令", "SK01-08 → 机器人执行器"), ("执行结果", "执行器 → 物理世界"),
         ("⬆ 几何 手/销/孔 (z R7)", "2D3D → 流形专家预测器"), ("预测流形 (JEPA)", "流形专家预测器 → 流形")]
print("\n⑤ 关键链 (画布真实几何):")
for pref, desc in WATCH:
    for li in links:
        if not str(li.link.get("label", "")).startswith(pref):
            continue
        s, d = li.src, li.dst
        ax = s.scenePos().x() + getattr(s, "w", 0)
        bx = d.scenePos().x()
        st = f"❌ 回退 {round(ax - bx)}px" if ax > bx + 1 else (
            "✅ 竖直" if abs(ax - bx) <= 1 else f"✅ 前向 {round(bx - ax)}px")
        print(f"   {desc:<26} {s.node['name'][:12]:<14}→{d.node['name'][:12]:<14} ax={ax:>6.0f} bx={bx:>6.0f} {st}")

print("\n⑥ L4 层节点 (渲染几何 — 应全部同一 y = 一层):")
for nid, nname, x, y, w, h in sorted(NODES, key=lambda n: (n[3], n[2])):
    if nid.startswith("ssbg7") or nid in ("ssintact", "ssintact_dec", "ssmani_exp", "ssmani_c", "ssmani_p"):
        print(f"   {nname:<26} x={x:>6.0f} y={y:>7.0f} w={w:>4} h={h:>4}")

ts = time.strftime("%Y%m%d_%H%M%S")
os.makedirs(os.path.join(ROOT, "reports"), exist_ok=True)
for tag, region, scale in (("l4_l3_layout", QRectF(-120, -960, 2320, 780), 1.0),
                           ("full", QRectF(-650, -1560, 7200, 3200), 0.5)):
    img = QImage(int(region.width() * scale), int(region.height() * scale), QImage.Format_ARGB32)
    img.fill(Qt.black)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    sc.render(p, QRectF(0, 0, img.width(), img.height()), region)
    p.end()
    out = os.path.join(ROOT, "reports", f"canvas_{tag}_{ts}.png")
    img.save(out)
    print(f"→ {out} ({img.width()}x{img.height()})")
