#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按绘制顺序打印某个节点的所有画笔操作 (只读) —— 专门看"有没有东西画在文字上面"。
用法: QT_QPA_PLATFORM=offscreen gui-venv311/bin/python /tmp/node_op_trace.py <flow> <关键词>
"""
import json
import os
import sys

sys.path.insert(0, "/home/ubuntu/zmax_rel/tools/gui")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QRectF  # noqa: E402
from PyQt5.QtGui import QImage, QPainter, QColor  # noqa: E402
from PyQt5.QtWidgets import QApplication, QStyleOptionGraphicsItem  # noqa: E402

FLOW, KW = sys.argv[1], sys.argv[2]
app = QApplication.instance() or QApplication([])
import simulink_module as SM  # noqa: E402

d = json.load(open(FLOW, encoding="utf-8"))
nodes, links = d["nodes"], d.get("links", [])
shim = type("S", (), {"nodes": nodes, "links": links})()

OPS = []


class P:
    """代理画笔: 转发一切, 只记录 (便于拿到真实宽度/度量)。"""

    def __init__(self, real):
        self._r = real
        self._ops = OPS

    def __getattr__(self, k):
        return getattr(self._r, k)

    def fontMetrics(self):
        return self._r.fontMetrics()

    def font(self):
        return self._r.font()

    def _key(self, o):
        if isinstance(o, QRectF):
            return (round(o.x(), 1), round(o.y(), 1), round(o.width(), 1), round(o.height(), 1))
        return None

    def drawText(self, *a):
        txt = a[-1] if isinstance(a[-1], str) else ""
        r = self._key(a[0])
        w = self._r.fontMetrics().horizontalAdvance(txt)
        self._ops.append(("TEXT", r, self._r.font().pointSizeF(), round(w, 1), txt[:40]))
        return self._r.drawText(*a)

    def drawRoundedRect(self, *a):
        self._ops.append(("ROUND", self._key(a[0]) or self._key(a[1]), None, None, ""))
        return self._r.drawRoundedRect(*a)

    def drawRect(self, *a):
        self._ops.append(("RECT", self._key(a[0]) or self._key(a[1]), None, None, ""))
        return self._r.drawRect(*a)

    def drawEllipse(self, *a):
        self._ops.append(("ELLIPSE", self._key(a[0]) or self._key(a[1]), None, None, ""))
        return self._r.drawEllipse(*a)

    def fillRect(self, *a):
        self._ops.append(("FILL", self._key(a[0]) or self._key(a[1]), None, None, ""))
        return self._r.fillRect(*a)


hits = [n for n in nodes if KW in str(n.get("name", ""))]
print(f"{os.path.basename(FLOW)} 命中 {len(hits)}: " + ", ".join(str(n.get('name'))[:34] for n in hits))
for n in hits[:2]:
    w, h = int(n.get("w", SM.DW)), int(n.get("h", SM.DH))
    img = QImage(w + 8, h + 8, QImage.Format_ARGB32)
    img.fill(QColor("#0a0a0f"))
    real = QPainter(img)
    real.setRenderHint(QPainter.Antialiasing)
    real.translate(4, 4)
    p = P(real)
    OPS.clear()
    it = SM.SimNodeItem(n, shim)
    try:
        it.paint(p, QStyleOptionGraphicsItem(), None)
    except Exception as e:
        print("  paint 异常:", e)
    real.end()
    print(f"\n=== {n['name'][:40]} ({w}x{h}) 绘制顺序 ===")
    # 逐个 TEXT, 看它**之后**有没有填充类操作盖住它
    texts = [(i, o) for i, o in enumerate(OPS) if o[0] == "TEXT"]
    for i, o in texts:
        kind, r, pt, tw, t = o
        cover = []
        for k2, o2 in enumerate(OPS):
            if k2 <= i or o2[0] not in ("ROUND", "RECT", "FILL", "ELLIPSE"):
                continue
            r2 = o2[1]
            if not (r and r2):
                continue
            ix = max(0.0, min(r[0] + r[2], r2[0] + r2[2]) - max(r[0], r2[0]))
            iy = max(0.0, min(r[1] + r[3], r2[1] + r2[3]) - max(r[1], r2[1]))
            if ix > 2 and iy > 2 and ix * iy > 0.25 * max(1.0, r[2] * r[3]):
                cover.append((o2[0], r2))
        flag = "  ⚠ 之后有填充盖住" if cover else ""
        print(f"  [{i:02d}] TEXT p{pt:.0f} 宽{tw:5.1f} 矩形{r} | {t!r}{flag}")
        for c in cover[:2]:
            print(f"        ← {c[0]} {c[1]} 在它之后画")
    sys.stdout.flush()
