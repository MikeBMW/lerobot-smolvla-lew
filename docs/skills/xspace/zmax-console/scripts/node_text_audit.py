#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""节点文字体检 (只读, 通用): 用**代理画笔**拦下每个节点真实 paint() 里的每次 drawText,
按老倪的规矩判 "看不清" 三种毛病 —— ①文字宽过它的绘制矩形(会挤/被裁) ②画到方框外
③两块文字矩形互相压(遮挡)。外加统计每个节点的文字行数 (行数越多越挤)。

用法: cd /home/ubuntu/zmax_rel && QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python <本脚本> [flow.json ...]
不给参数 = 扫 flows/ 与 src/lerobot/engineering/flows/ 全部。
"""
import glob
import json
import os
import sys

REPO = os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax_rel")
sys.path.insert(0, os.path.join(REPO, "tools", "gui"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QRectF  # noqa: E402
from PyQt5.QtGui import QFontMetrics, QImage, QPainter, QColor  # noqa: E402
from PyQt5.QtWidgets import QApplication, QStyleOptionGraphicsItem  # noqa: E402

MAX_OVER = 1.0          # 文字宽允许超出绘制矩形多少 px (容差)
OVERLAP_FRAC = 0.30     # 两块文字矩形重叠超过小矩形面积的 30% 记为"互相压"
LINE_WARN = 5           # 一个节点里文字行数 ≥ 此值 → 提示"可能挤"


class AuditPainter:
    """代理画笔: set*/fontMetrics/draw* 转发给真画笔; drawText 额外记账。"""

    def __init__(self, real):
        self._r = real
        self.texts = []          # (rect, text, font, width)

    def __getattr__(self, k):
        return getattr(self._r, k)

    def fontMetrics(self):
        return self._r.fontMetrics()

    def font(self):
        return self._r.font()

    def drawText(self, rect, *args):
        # 兼容 drawText(QRectF, flags, str) / drawText(QPointF, str)
        try:
            txt = ""
            r = None
            if isinstance(rect, QRectF):
                r = QRectF(rect)
                txt = str(args[-1]) if args else ""
            elif hasattr(rect, "x") and hasattr(rect, "width"):
                r = QRectF(rect.x(), rect.y(), rect.width(), rect.height())
                txt = str(args[-1]) if args else ""
            else:                      # QPointF / x, y
                txt = str(args[-1]) if args else ""
            if r is not None and txt:
                self.texts.append((r, txt, self._r.font(), self._r.fontMetrics().horizontalAdvance(txt)))
        except Exception:
            pass
        return self._r.drawText(rect, *args)


def overlap_frac(a, b):
    ix = max(0.0, min(a.right(), b.right()) - max(a.left(), b.left()))
    iy = max(0.0, min(a.bottom(), b.bottom()) - max(a.top(), b.top()))
    if ix <= 0 or iy <= 0:
        return 0.0
    small = min(a.width() * a.height(), b.width() * b.height())
    return (ix * iy) / small if small > 0 else 0.0


def main() -> int:
    app = QApplication.instance() or QApplication([])
    import simulink_module as SM  # noqa: E402

    args = [a for a in sys.argv[1:] if a.endswith(".json")]
    if args:
        files = args
    else:
        files = sorted(set(glob.glob(os.path.join(REPO, "flows", "*.json")))
                       | set(glob.glob(os.path.join(REPO, "src/lerobot/engineering/flows", "*.json"))))
    tot = clipped = outside = collide = 0
    lines_hist = {}
    rows = []
    for f in files:
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        nodes = d.get("nodes") if isinstance(d, dict) else d
        if not isinstance(nodes, list):
            continue
        shim = type("Shim", (), {"nodes": nodes, "links": d.get("links", []) if isinstance(d, dict) else []})()
        for n in nodes:
            if not isinstance(n, dict):
                continue
            nm = str(n.get("name", ""))
            try:
                it = SM.SimNodeItem(n, shim)
            except Exception:
                continue
            w = int(max(20, n.get("w", SM.DW)))
            h = int(max(20, n.get("h", SM.DH)))
            img = QImage(w + 8, h + 8, QImage.Format_ARGB32)
            img.fill(QColor("#0a0a0f"))
            p = QPainter(img)
            p.setRenderHint(QPainter.Antialiasing)
            ap = AuditPainter(p)
            err = ""
            try:
                it.paint(ap, QStyleOptionGraphicsItem(), None)
            except Exception as e:
                err = f"paint异常 {e}"
            p.end()
            tot += 1
            ts = ap.texts
            lines_hist[len(ts)] = lines_hist.get(len(ts), 0) + 1
            for r, txt, _fo, wpx in ts:
                if wpx > r.width() + MAX_OVER:
                    clipped += 1
                    rows.append(("文字超框", os.path.basename(f), nm, txt[:34], f"{wpx:.0f}>{r.width():.0f}px"))
                if r.right() > w + 1 or r.bottom() > h + 1 or r.left() < -1 or r.top() < -1:
                    outside += 1
                    rows.append(("画到框外", os.path.basename(f), nm, txt[:34],
                                 f"rect {r.left():.0f},{r.top():.0f} {r.width():.0f}x{r.height():.0f} vs 框 {w}x{h}"))
            for i in range(len(ts)):
                for j in range(i + 1, len(ts)):
                    # 只用**贴合文字**的矩形判重叠 (大容器矩形, 如整条色带标题框, 会误报)
                    def _tight(r, t, fo, wpx):
                        try:
                            fh = QFontMetrics(fo).height()
                        except Exception:
                            return False
                        return (r.height() <= 2.5 * fh and wpx > 0 and r.width() <= 1.7 * wpx)
                    a = ts[i]
                    b = ts[j]
                    if not (_tight(a[0], a[1], a[2], a[3]) and _tight(b[0], b[1], b[2], b[3])):
                        continue
                    fr = overlap_frac(a[0], b[0])
                    if fr > OVERLAP_FRAC:
                        collide += 1
                        rows.append(("文字互压", os.path.basename(f), nm,
                                     f"{a[1][:16]} ✕ {b[1][:16]}", f"重叠 {fr*100:.0f}%"))
            if err:
                rows.append(("异常", os.path.basename(f), nm, err, ""))
    print(f"扫 {tot} 个节点 (代理画笔拦 drawText)")
    for kind in ("文字超框", "画到框外", "文字互压", "异常"):
        sub = [r for r in rows if r[0] == kind]
        print(f"\n[{kind}] {len(sub)} 处")
        for r in sub[:14]:
            print("   %-20s %-34s %-30s %s" % (r[1], r[2][:32], r[3], r[4]))
    print("\n文字行数分布 (节点数 → 行数):", dict(sorted(lines_hist.items())))
    bad = len([r for r in rows if r[0] in ("文字超框", "画到框外", "文字互压", "异常")])
    print("=== 结论:", "无'看不清'问题 ✅" if bad == 0 else f"有 {bad} 处待修 ❌", "===")
    sys.stdout.flush()
    os._exit(0 if bad == 0 else 1)


if __name__ == "__main__":
    raise SystemExit(main())
