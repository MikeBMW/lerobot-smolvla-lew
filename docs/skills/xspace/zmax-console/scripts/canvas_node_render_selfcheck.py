#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""画布节点渲染自检 (无窗口): 用**真实 paint()** 把每个节点画进 QImage, 检查
  ① paint 不抛异常 (paint 里抛异常 = Qt 直接 abort 整个 GUI)
  ② 文字/内容没越出方框 (ink 触碰画布边缘 = 被裁)
  ③ 标题单行放得下 / 短显示名生效 (统计)

用法: QT_QPA_PLATFORM=offscreen gui-venv311/bin/python /tmp/render_selfcheck.py <tag>
输出: /tmp/ui_fix/render_<tag>.json + /tmp/ui_fix/render_<tag>.png (整场景拼图, 供目检/VLM)
"""
import json
import os
import sys

sys.path.insert(0, "/home/ubuntu/zmax_rel/tools/gui")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtGui import QGuiApplication, QImage, QPainter, QColor, QFontMetrics  # noqa: E402
from PyQt5.QtCore import QRectF  # noqa: E402
from PyQt5.QtWidgets import QStyleOptionGraphicsItem  # noqa: E402

TAG = sys.argv[1] if len(sys.argv) > 1 else "sc"
JSON_IN = os.environ.get("CANVAS_JSON", "/home/ubuntu/zmax_rel/flows/state_space_obs.json")
OUT = "/tmp/ui_fix"
os.makedirs(OUT, exist_ok=True)

_app = QGuiApplication.instance() or QGuiApplication([])
import simulink_module as SM  # noqa: E402


class _Shim:
    """paint() 里只会用到 scene_ref.links / scene_ref.nodes (端口分布)。"""
    def __init__(self, nodes, links):
        self.nodes = nodes
        self.links = links


def main():
    d = json.load(open(JSON_IN, encoding="utf-8"))
    nodes, links = d["nodes"], d.get("links", [])
    shim = _Shim(nodes, links)
    fm = QFontMetrics(SM._node_font(SM.NODE_TITLE_PT, True))
    res, errs, clipped, disp_rows = [], [], [], []
    # 拼图: 每行一个节点 (放大 1.0), 便于目检
    sheets = []
    for nd in nodes:
        w, h = int(nd.get("w", SM.DW)), int(nd.get("h", SM.DH))
        it = SM.SimNodeItem(nd, shim)
        img = QImage(w + 24, h + 30, QImage.Format_ARGB32)
        img.fill(QColor("#0a0a0f"))
        p = QPainter(img)
        try:
            it.paint(p, QStyleOptionGraphicsItem(), None)
        except Exception as e:
            errs.append({"name": nd.get("name"), "err": f"{type(e).__name__}: {e}"})
            p.end()
            continue
        p.end()
        # ink 检测: 把靠近边缘 3px 内是否有亮像素作为"被裁"判据 (画的正是 0..w / 0..h)
        px = [(x, y) for y in range(img.height()) for x in range(img.width())
              if QColor(img.pixel(x, y)).lightness() > 70]
        edge = [1 for (x, y) in px if x < 3 or y < 3 or x >= img.width() - 3 or y >= img.height() - 3]
        if edge:
            clipped.append({"name": nd.get("name"), "w": w, "h": h, "edge_ink": len(edge)})
        is_bg = nd.get("type") == "row_bg"
        nm = str(nd.get("name", ""))
        disp = SM.node_display_name(nm, None if is_bg else SM.NODE_LABEL_MAX_PX)
        avail = max(40, w - SM.NODE_PAD_R) if not is_bg else max(80, w - 16)
        lines, trunc = SM._wrap_title(disp, fm, avail)
        res.append({"name": nm, "type": nd.get("type"), "w": w, "h": h,
                    "disp": disp, "lines": len(lines), "trunc": bool(trunc),
                    "disp_px": fm.horizontalAdvance(disp),
                    "avail_px": int(avail), "ink_px": len(px)})
        disp_rows.append((nm, disp))
        sheets.append(img)
    # 拼一张竖版总图 (限宽 700, 便于看)
    total_h = sum(im.height() + 4 for im in sheets[:60])
    sheet = QImage(760, min(20000, total_h), QImage.Format_ARGB32)
    sheet.fill(QColor("#05050a"))
    sp = QPainter(sheet)
    y = 0
    for im in sheets[:60]:
        sp.drawImage(4, y, im)
        y += im.height() + 4
        if y > sheet.height() - 10:
            break
    sp.end()
    sheet.save(f"{OUT}/render_{TAG}.png")
    json.dump({"rows": res, "errors": errs, "clipped": clipped},
              open(f"{OUT}/render_{TAG}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    tr = [r for r in res if r["trunc"]]
    two = [r for r in res if r["lines"] > 1]
    print(f"=== render {TAG}: 节点 {len(res)} ===")
    print(f"  paint 异常: {len(errs)}  边缘 ink(疑似被裁): {len(clipped)}")
    print(f"  标题截断(省略): {len(tr)} · 需两行: {len(two)} · 单行: {len(res) - len(two)}")
    for e in errs[:5]:
        print("   [ERR]", e)
    for c in clipped[:8]:
        print("   [裁]  ", c)
    print(f"  拼图: {OUT}/render_{TAG}.png  ({sheet.width()}x{sheet.height()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
