#!/usr/bin/env python3
"""📐 画布节点文字拥挤度实测 (离屏, 不弹窗)

按 SimNodeItem.paint 里同一套算法 (字号 12→11→10 逐级 + 单行/拆词/拆字两行, avail=w-36)
逐节点算: 名字需要多宽、用几行、最终是否还溢出。用于决定节点框该多大、字号该多少。
用法: QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/probe_canvas_nodes.py
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
GUI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "gui")
sys.path.insert(0, GUI)

from PyQt5.QtWidgets import QApplication  # noqa: E402
from PyQt5.QtGui import QFont, QFontMetrics  # noqa: E402

app = QApplication(sys.argv)
import simulink_module as sm  # noqa: E402

m = sm.SimulinkModule()
m.resize(3068, 1800)


def layout_name(name, w, badge=36, sizes=(12, 11, 10)):
    """复刻 paint 里的排版算法 → (字号, 行数, 是否溢出, 最长行宽, avail)"""
    avail = max(40, w - badge)
    for fs in sizes:
        fm = QFontMetrics(QFont("Arial", fs, QFont.Bold))
        if fm.horizontalAdvance(name) <= avail:
            return fs, 1, False, fm.horizontalAdvance(name), avail
        parts = name.replace("·", " · ").replace("(", " ( ").replace(")", " ) ").split()
        w1, w2 = "", ""
        for pt in parts:
            trial = (w1 + " " + pt).strip()
            if fm.horizontalAdvance(trial) <= avail or not w1:
                w1 = trial
            else:
                w2 = (w2 + " " + pt).strip()
        if fm.horizontalAdvance(w2) <= avail and fm.horizontalAdvance(w1) <= avail:
            return fs, 2, False, max(fm.horizontalAdvance(w1), fm.horizontalAdvance(w2)), avail
        c1, c2 = "", ""
        for ch in name:
            if fm.horizontalAdvance(c1 + ch) <= avail or not c1:
                c1 += ch
            else:
                c2 += ch
        if fm.horizontalAdvance(c2) <= avail:
            return fs, 2, False, max(fm.horizontalAdvance(c1), fm.horizontalAdvance(c2)), avail
    fm = QFontMetrics(QFont("Arial", sizes[-1], QFont.Bold))
    return sizes[-1], 2, True, fm.horizontalAdvance(name), avail


# ⚠️ 只跑不弹对话框的画布: open_compare5/open_z700_flow 会开模态框 → 离屏下卡死 (实测超时)
FLOWS = [("🧮 状态空间", m.open_state_space)]
if os.environ.get("PROBE_ALL"):
    FLOWS += [("🔬 Model Zoo", m.open_compare5), ("🎛 总系统", m.open_topsys)]
print(f"{'画布':<14} {'节点':>5} {'单行':>5} {'两行':>5} {'溢出':>5} {'降到10pt':>9} "
      f"{'最宽名字需要':>12} {'当前avail':>9}")
print("-" * 78)
worst_all = []
for label, fn in FLOWS:
    try:
        fn()
    except Exception as e:
        print(f"{label:<14} 加载失败: {e}")
        continue
    app.processEvents()
    nodes = [n for n in m.nodes if n.get("type") != "row_bg"]
    s1 = s2 = ov = small = 0
    need_max = 0
    worst = []
    for n in nodes:
        fs, lines, overflow, need, avail = layout_name(n["name"], n.get("w", 240))
        s1 += lines == 1
        s2 += lines == 2
        ov += overflow
        small += fs < 12
        if need > need_max:
            need_max = need
        worst.append((need, fs, lines, overflow, n["name"], n.get("w", 240), n.get("h", 84)))
    worst.sort(reverse=True)
    worst_all += worst[:4]
    print(f"{label:<14} {len(nodes):>5} {s1:>5} {s2:>5} {ov:>5} {small:>9} "
          f"{need_max:>12} {max(40, 240 - 36):>9}")

print("\n=== 最挤的 12 个节点 (需要宽度 vs 框宽) ===")
print(f"{'需要px':>7} {'字号':>4} {'行':>3} {'溢出':>5} {'框宽':>5} {'框高':>5}  名字")
worst_all.sort(reverse=True)
seen = set()
for need, fs, lines, ov, name, w, h in worst_all:
    if name in seen:
        continue
    seen.add(name)
    print(f"{need:>7} {fs:>4} {lines:>3} {'★' if ov else '':>5} {w:>5} {h:>5}  {name}")
    if len(seen) >= 12:
        break
app.quit()
