#!/usr/bin/env python3
"""状态空间画布 → 矢量 PDF 全图导出 (不依赖 Qt/GUI 截图, 直接读真源 JSON 画)。

用法:
  QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/canvas_pdf_export.py \
      [--out reports/canvas_pdf/canvas_latest.pdf] [--version v20261001-xxxxxxxx] [--no-preview]

产物:
  · 多页矢量 PDF (封面/图例页 + 全图总览页 + 分层详图页 3 列 × 3 行带组)
  · 可选 PNG 预览 (pdftoppm, 供人眼/手机快速确认)
  · 同目录写 canvas_version.json (供 8796 /canvas/version 与发布脚本读)

自查 (写进每页页脚):
  · 全图节点/连线数 = JSON 真值 (89 / 182)
  · 逐页节点数/连线数; 收尾断言"所有节点至少被画一次、所有连线至少被画一次"
布局:
  · 行带 (row_bg/bg) 还原成背景色带 (按层 L2/L3/L4/L5 分行)
  · 连线走正交折线: 跨行带 → 走行带之间的走廊 (避免长直线穿节点); 同带 → 走带内上/下轨
  · 超长跨行连线 (跨距 > 8000px) 弱化为细线 + 低透明度
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from reportlab.lib.colors import Color, HexColor, white                     # noqa: E402
from reportlab.pdfbase import pdfmetrics                                    # noqa: E402
from reportlab.pdfbase.ttfonts import TTFont                                # noqa: E402
from reportlab.pdfgen import canvas as rl_canvas                            # noqa: E402

from lerobot.engineering import canvas_publish as CP                         # noqa: E402

FONT = "CJK"
# 必须同时含 Latin + CJK 字形 (DroidSansFallback 只有 CJK ⇒ 数字/英文会整段消失, 实测踩过)
FONT_CANDIDATES = [
    ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0),
    ("/usr/share/fonts/truetype/arphic/uming.ttc", 0),
    ("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf", 0),
]

TYPE_COLOR = {
    "model": "#2f6fd0", "data": "#12897b", "hardware": "#c2610c",
    "condition": "#c0392b", "system": "#6c3ea8", "mode_switch": "#b7950b",
    "node": "#555555",
}
TYPE_FILL = {
    "model": "#eef4fd", "data": "#e8f6f3", "hardware": "#fdf1e6",
    "condition": "#fdeceb", "system": "#f3ecfb", "mode_switch": "#fdf7e3",
    "node": "#f4f4f4",
}
TYPE_CN = {"model": "model 模型/算法", "data": "data 数据源", "hardware": "hardware 硬件/执行",
           "condition": "condition 条件/限幅", "system": "system 系统/元层",
           "mode_switch": "mode_switch 模式开关", "row_bg": "row_bg 层行带(背景)"}

PAGE_W = 3370.0                       # A0 横向宽 (1189mm)
DETAIL_H = 1400.0
MARGIN = 26.0
FOOTER_H = 34.0
NODE_PAD = 3.0
LONG_LINK_PX = 8000.0


# ───────────────────────── 字体 ─────────────────────────
def register_font() -> None:
    for p, idx in FONT_CANDIDATES:
        if os.path.exists(p):
            pdfmetrics.registerFont(TTFont(FONT, p, subfontIndex=idx))
            return
    raise SystemExit("找不到可用 CJK 字体 (需要能嵌进 PDF 的 TTF/TTC)")


def sw(txt: str, size: float) -> float:
    return pdfmetrics.stringWidth(txt, FONT, size)


def wrap(txt: str, size: float, maxw: float) -> list[str]:
    """按字符折行 (中英混排: 中文可在任意字符断行)。"""
    lines, cur = [], ""
    for ch in txt:
        if ch == "\n":
            lines.append(cur)
            cur = ""
            continue
        if sw(cur + ch, size) <= maxw or not cur:
            cur += ch
        else:
            lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines


def fit_text(txt: str, box_w: float, box_h: float, hi: float = 9.0, lo: float = 1.1):
    """自动字号: 返回 (size, lines) —— 在框内不截断, 取最大可用字号。"""
    size = hi
    while size > lo:
        lines = wrap(txt, size, box_w)
        if len(lines) * size * 1.18 <= box_h and all(sw(l, size) <= box_w + 0.5 for l in lines):
            return size, lines
        size -= 0.2
    return lo, wrap(txt, lo, box_w)


# ───────────────────────── 画布模型 ─────────────────────────
class Canvas:
    def __init__(self, j: dict, version: str, md5: str):
        self.j = j
        self.version = version
        self.md5 = md5
        self.nodes = j.get("nodes", [])
        self.links = j.get("links", [])
        self.by_id = {n["id"]: n for n in self.nodes}
        self.bands = sorted([n for n in self.nodes if n.get("type") in ("row_bg", "bg")],
                            key=lambda n: n["y"])
        self.boxes = [n for n in self.nodes if n.get("type") not in ("row_bg", "bg")]
        self.x0 = min(n["x"] for n in self.nodes)
        self.y0 = min(n["y"] for n in self.nodes)
        self.x1 = max(n["x"] + n["w"] for n in self.nodes)
        self.y1 = max(n["y"] + n["h"] for n in self.nodes)
        self.dangling = [l for l in self.links if l.get("f") not in self.by_id or l.get("t") not in self.by_id]
        self.drawn_nodes: set[str] = set()
        self.drawn_links: set[int] = set()

    def band_of(self, n: dict):
        """节点所在的背景行带 (按中心 y 判)。"""
        cy = n["y"] + n["h"] * 0.5
        for b in self.bands:
            if b["y"] <= cy <= b["y"] + b["h"]:
                return b
        return None


def corridor_y(c: Canvas, f: dict, t: dict, band_f, band_t) -> float:
    """跨行带连线的走廊 y: 取两行带之间的空白带中点 (不穿节点行)。"""
    if band_f is not None and band_t is not None and band_f is not band_t:
        up, dn = (band_f, band_t) if band_f["y"] < band_t["y"] else (band_t, band_f)
        gap_top, gap_bot = up["y"] + up["h"], dn["y"]
        if gap_bot > gap_top + 6:
            return (gap_top + gap_bot) * 0.5
        return gap_top + 12
    fy, ty = f["y"] + f["h"] * 0.5, t["y"] + t["h"] * 0.5
    return max(f["y"] + f["h"], t["y"] + t["h"]) + 14      # 同带: 走带内下轨


def route(c: Canvas, l: dict) -> list[tuple[float, float]]:
    """正交折线路径 (内容像素坐标)。"""
    f, t = c.by_id.get(l.get("f")), c.by_id.get(l.get("t"))
    if f is None or t is None:
        return []
    sx, sy = f["x"] + f["w"], f["y"] + f["h"] * 0.5
    tx, ty = t["x"], t["y"] + t["h"] * 0.5
    bf, bt = c.band_of(f), c.band_of(t)
    if tx >= sx + 24:                                       # 前向
        if abs(ty - sy) < 26 and bf is bt:
            return [(sx, sy), (tx, ty)]
        cor = corridor_y(c, f, t, bf, bt)
        st = 14.0 if (tx - sx) > 120 else max(6.0, (tx - sx) / 4)
        return [(sx, sy), (sx + st, sy), (sx + st, cor), (tx - st, cor), (tx - st, ty), (tx, ty)]
    # 反向 / 回环: 绕到行带上下轨再回来
    cor = corridor_y(c, f, t, bf, bt)
    lane = min(sy, ty) - 16 if abs(sy - ty) < 40 else cor
    return [(sx, sy), (sx + 18, sy), (sx + 18, lane), (tx - 18, lane), (tx - 18, ty), (tx, ty)]


# ───────────────────────── 绘制 ─────────────────────────
class Painter:
    def __init__(self, c: Canvas, out: Path):
        self.c = c
        self.out = out
        self.pdf = rl_canvas.Canvas(str(out), pagesize=(1587.0, 1123.0))   # 首页=封面 A3
        self.pdf.setTitle("状态空间画布全图 %s" % c.version)
        self.pdf.setAuthor("Hermes Agent / Z-MAX")
        self.pdf.setSubject("状态空间模型全图 (89 节点 / 182 连线) %s" % c.version)
        self.page_no = 0
        self.pages = 0
        self.page_marks: list[dict] = []

    # ── 坐标变换 (内容 px → 页面 pt) ──
    def set_window(self, x0, y0, x1, y1, page_w, page_h):
        self.pdf.setPageSize((page_w, page_h))
        self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1
        self.pw, self.ph = page_w, page_h
        self.s = min((page_w - 2 * MARGIN) / (x1 - x0), (page_h - 2 * MARGIN - FOOTER_H) / (y1 - y0))
        self.ox = MARGIN + ((page_w - 2 * MARGIN) - (x1 - x0) * self.s) / 2
        self.oy = MARGIN + FOOTER_H                              # 底部留页脚

    def X(self, x):
        return self.ox + (x - self.x0) * self.s

    def Yt(self, y):
        """内容 y (元素上边缘) → PDF y (元素上边缘)。内容 y 向下增大, PDF 向上增大。"""
        return self.ph - MARGIN - (y - self.y0) * self.s

    # ── 底层 ──
    def bands(self, x0, y0, x1, y1):
        p = self.pdf
        for b in self.c.bands:
            if b["y"] + b["h"] < y0 or b["y"] > y1:
                continue
            col = b.get("params", {}).get("bg") or b.get("color") or "#eef1f5"
            try:
                col = HexColor(col)
            except Exception:                                                # noqa: BLE001
                col = HexColor("#eef1f5")
            p.setFillColor(col)
            p.setFillAlpha(0.13)
            p.setStrokeColor(col)
            p.setStrokeAlpha(0.45)
            p.setLineWidth(0.5)
            bx = max(b["x"], x0)
            bx2 = min(b["x"] + b["w"], x1)
            by = max(b["y"], y0)
            by2 = min(b["y"] + b["h"], y1)
            if bx2 <= bx or by2 <= by:
                continue
            p.roundRect(self.X(bx), self.Yt(by2), (bx2 - bx) * self.s, (by2 - by) * self.s, 2,
                        fill=1, stroke=1)
            self.c.drawn_nodes.add(b["id"])                     # 行带本身也是节点(背景带)
            p.setFillAlpha(1)
            p.setStrokeAlpha(1)
            # 行带标题: 自动字号 + 折行, 空间不足时**裁到行带矩形内** (不许越界飘成"野字")
            name = CP.sanitize_label(b.get("name", ""))
            bw = max(12.0, (bx2 - bx) * self.s - 10)
            bh = max(8.0, (by2 - by) * self.s - 8)
            fs, lines = fit_text(name, bw, bh, hi=11.0, lo=4.0)
            p.saveState()
            pth = p.beginPath()
            pth.rect(self.X(bx) + 2, self.Yt(by) - bh - 4, bw + 6, bh + 8)
            p.clipPath(pth, stroke=0)
            p.setFillColor(Color(0.13, 0.15, 0.19))
            p.setFont(FONT, fs)
            ty = self.Yt(by) - fs - 2
            for ln in lines:
                p.drawString(self.X(bx) + 4, ty, ln)
                ty -= fs * 1.16
            p.restoreState()

    def legend(self, x, y, w=520.0):
        p = self.pdf
        p.setFont(FONT, 9)
        p.setFillColor(Color(0.15, 0.16, 0.2))
        p.drawString(x, y, "图例 (按节点 type 上色) · 连线: 灰蓝正交折线, 跨距>8000px 弱化")
        y -= 16
        items = [k for k in TYPE_COLOR]
        for i, k in enumerate(items):
            yy = y - i * 15
            p.setFillColor(HexColor(TYPE_FILL[k]))
            p.setStrokeColor(HexColor(TYPE_COLOR[k]))
            p.setLineWidth(0.8)
            p.roundRect(x, yy - 3, 26, 10, 2, fill=1, stroke=1)
            p.setFillColor(Color(0.2, 0.2, 0.24))
            p.setFont(FONT, 8)
            p.drawString(x + 33, yy, TYPE_CN.get(k, k))
        return y - len(items) * 15

    # ── 连线 ──
    def links(self, x0, y0, x1, y1, win_key: str):
        p = self.pdf
        for i, l in enumerate(self.c.links):
            pts = route(self.c, l)
            if len(pts) < 2:
                continue
            lx0 = min(t[0] for t in pts)
            lx1 = max(t[0] for t in pts)
            ly0 = min(t[1] for t in pts)
            ly1 = max(t[1] for t in pts)
            # 只画与本页窗口相交的线
            if lx1 < x0 or lx0 > x1 or ly1 < y0 or ly0 > y1:
                continue
            span = abs(lx1 - lx0) + abs(ly1 - ly0)
            if span > LONG_LINK_PX:
                cur_col, cur_alpha, lw = Color(0.42, 0.5, 0.62), 0.30, 0.35
            elif span > 3000:
                cur_col, cur_alpha, lw = Color(0.35, 0.44, 0.58), 0.55, 0.55
            else:
                cur_col, cur_alpha, lw = Color(0.28, 0.38, 0.55), 0.85, 0.9
            p.setStrokeColor(cur_col)
            p.setStrokeAlpha(cur_alpha)
            p.setLineWidth(lw)
            p.setLineJoin(0)
            path = p.beginPath()
            path.moveTo(self.X(pts[0][0]), self.Yt(pts[0][1]))
            for (px, py) in pts[1:]:
                path.lineTo(self.X(px), self.Yt(py))
            p.drawPath(path, fill=0, stroke=1)
            self.c.drawn_links.add(i)
            # 箭头 (目标端)
            tt = self.c.by_id.get(l.get("t"))
            if tt is not None:
                ax, ay = self.X(pts[-1][0]), self.Yt(pts[-1][1])
                s = 4.2
                p.setFillColor(cur_col)
                p.setFillAlpha(cur_alpha)
                pth = p.beginPath()
                pth.moveTo(ax - s, ay - s * 0.62)
                pth.lineTo(ax, ay)
                pth.lineTo(ax - s, ay + s * 0.62)
                pth.close()
                p.drawPath(pth, fill=1, stroke=0)
                p.setFillAlpha(1)
            # 短连线标签 (长线标了看不清)
            lbl = CP.sanitize_label(l.get("label", "") or "")
            if lbl and span < 1600 and self.s > 0.30:
                mid = pts[len(pts) // 2]
                p.setFont(FONT, max(2.4, 3.4 * self.s / 0.45))
                p.setFillColor(Color(0.36, 0.4, 0.5))
                p.setFillAlpha(0.8)
                p.drawString(self.X(mid[0]) + 2, self.Yt(mid[1]) + 1.5, lbl[:18])
                p.setFillAlpha(1)

    # ── 节点 ──
    def nodes(self, x0, y0, x1, y1):
        p = self.pdf
        for n in self.c.boxes:
            if n["x"] + n["w"] < x0 or n["x"] > x1 or n["y"] + n["h"] < y0 or n["y"] > y1:
                continue
            t = n.get("type", "node")
            stroke = HexColor(TYPE_COLOR.get(t, TYPE_COLOR["node"]))
            fill = HexColor(TYPE_FILL.get(t, TYPE_FILL["node"]))
            bx, by = self.X(n["x"]), self.Yt(n["y"] + n["h"])
            bw, bh = n["w"] * self.s, n["h"] * self.s
            p.setFillColor(fill)
            p.setStrokeColor(stroke)
            p.setLineWidth(0.9)
            p.roundRect(bx, by, bw, bh, min(4.0, bh * 0.22), fill=1, stroke=1)
            # 顶部色条 (类型标识)
            p.setFillColor(stroke)
            p.setFillAlpha(0.85)
            p.rect(bx + 0.6, by + bh - max(1.6, bh * 0.07), bw - 1.2, max(1.4, bh * 0.07),
                   fill=1, stroke=0)
            p.setFillAlpha(1)
            name = CP.sanitize_label(n.get("name", ""))
            inner_w = max(6.0, bw - 2 * NODE_PAD - 1)
            inner_h = max(4.0, bh - 2 * NODE_PAD - max(2.5, bh * 0.09))
            fs, lines = fit_text(name, inner_w, inner_h)
            fits = (all(sw(l, fs) <= inner_w + 0.5 for l in lines)
                    and len(lines) * fs * 1.18 <= inner_h)
            if not fits:                                        # 极小节点: 裁到框内, 不许越界
                p.saveState()
                pth = p.beginPath()
                pth.rect(bx + 0.5, by + 0.5, bw - 1, bh - 1)
                p.clipPath(pth, stroke=0)
            p.setFillColor(Color(0.10, 0.12, 0.16))
            ty = by + bh - max(2.5, bh * 0.09) - fs - 1.0
            for ln in lines:
                if ty < by - fs:
                    break
                p.setFont(FONT, fs)
                p.drawString(bx + NODE_PAD, ty, ln)
                ty -= fs * 1.18
            if not fits:
                p.restoreState()
            self.c.drawn_nodes.add(n["id"])

    # ── 页眉/页脚 ──
    def header(self, title: str, sub: str = ""):
        p = self.pdf
        p.setFillColor(Color(0.09, 0.11, 0.15))
        p.setFont(FONT, 12)
        p.drawString(MARGIN, self.ph - MARGIN + 4, title)
        if sub:
            p.setFont(FONT, 8.5)
            p.setFillColor(Color(0.35, 0.38, 0.44))
            p.drawString(MARGIN + sw(title, 12) + 14, self.ph - MARGIN + 4, sub)

    def footer(self, page_no: int, pages: int, n_here: int, l_here: int):
        p = self.pdf
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        p.setStrokeColor(Color(0.78, 0.8, 0.84))
        p.setLineWidth(0.5)
        p.line(MARGIN, MARGIN + FOOTER_H - 12, self.pw - MARGIN, MARGIN + FOOTER_H - 12)
        left = ("%s · 生成 %s · 源 md5 %s" % (self.c.version, ts, self.c.md5[:8]))
        mid = ("累计已画(含总览页): 节点 %d/%d · 连线 %d/%d (真值 = flows/state_space_obs.json)"
               % (len(self.c.drawn_nodes), len(self.c.nodes), len(self.c.drawn_links), len(self.c.links)))
        right = ("本页 节点 %d · 连线 %d · 第 %d/%d 页" % (n_here, l_here, page_no, pages))
        p.setFont(FONT, 7.6)
        p.setFillColor(Color(0.28, 0.3, 0.35))
        p.drawString(MARGIN, MARGIN + 3, left)
        p.drawString(MARGIN + 430, MARGIN + 3, mid)
        p.drawRightString(self.pw - MARGIN, MARGIN + 3, right)
        self.page_marks.append({"page": page_no, "nodes": n_here, "links": l_here,
                                "version": self.c.version})

    def page_count_marks(self, x0, y0, x1, y1) -> tuple[int, int]:
        n = sum(1 for v in self.c.boxes
                if not (v["x"] + v["w"] < x0 or v["x"] > x1 or v["y"] + v["h"] < y0 or v["y"] > y1))
        ln = 0
        for l in self.c.links:
            pts = route(self.c, l)
            if len(pts) < 2:
                continue
            if (max(t[0] for t in pts) < x0 or min(t[0] for t in pts) > x1
                    or max(t[1] for t in pts) < y0 or min(t[1] for t in pts) > y1):
                continue
            ln += 1
        return n, ln

    # ── 页 ──
    def cover(self, det_hint: int = 6):
        self.det_hint = det_hint
        self.page_no += 1
        self.pdf.setPageSize((1587.0, 1123.0))            # A3 横向
        self.pw, self.ph = 1587.0, 1123.0
        p = self.pdf
        p.setFillColor(Color(1, 1, 1))
        p.rect(0, 0, self.pw, self.ph, fill=1, stroke=0)
        p.setFillColor(Color(0.07, 0.09, 0.14))
        p.setFont(FONT, 30)
        p.drawString(MARGIN + 20, self.ph - 110, "Z-MAX 状态空间 · 模型全图")
        p.setFont(FONT, 13)
        p.setFillColor(Color(0.3, 0.33, 0.4))
        p.drawString(MARGIN + 20, self.ph - 140, "State-Space Canvas — 全拓扑矢量图 (%s)" % self.c.version)
        st = {"nodes": len(self.c.nodes), "links": len(self.c.links)}
        p.setFont(FONT, 11)
        p.setFillColor(Color(0.15, 0.17, 0.22))
        info = [
            "真源: flows/state_space_obs.json   (realpath: %s)" % CP.source_json(),
            "节点 %d (其中背景行带 %d) · 连线 %d · md5 %s · 画布名: %s"
            % (st["nodes"], len(self.c.bands), st["links"], self.c.md5, self.c.j.get("name", "")[:70]),
            "本 PDF: 封面/图例 → 全图总览(1 页) → 分层详图(3 个行带组 × 自适应分列 = 共 %d 页); 全部矢量, 手机端可无限放大。" % self.det_hint,
            "布局: 按层行带 (L2/L3/L4/L5) 分行; 行带还原为背景色带; 跨行连线走行带之间的走廊做正交折线。",
        ]
        y = self.ph - 180
        for ln in info:
            p.drawString(MARGIN + 20, y, ln)
            y -= 20
        # 行带索引
        y -= 8
        p.setFont(FONT, 11)
        p.setFillColor(Color(0.09, 0.11, 0.15))
        p.drawString(MARGIN + 20, y, "层行带 (自上而下) · 每带内节点数:")
        y -= 20
        p.setFont(FONT, 9)
        for b in self.c.bands:
            inside = sum(1 for n in self.c.boxes
                         if b["y"] <= n["y"] + n["h"] * 0.5 <= b["y"] + b["h"])
            p.setFillColor(Color(0.22, 0.24, 0.3))
            p.drawString(MARGIN + 34, y, "y %5d..%-5d  h %4d  节点 %2d   %s"
                         % (b["y"], b["y"] + b["h"], b["h"], inside, CP.sanitize_label(b.get("name", ""))[:64]))
            y -= 15
        # 图例
        self.legend(MARGIN + 900, self.ph - 210, 520)
        # 页脚
        p.setFont(FONT, 7.6)
        p.setFillColor(Color(0.28, 0.3, 0.35))
        p.drawString(MARGIN + 20, MARGIN + 6,
                     "%s · 生成 %s · 封面/图例页 · 全图 %d 节点 / %d 连线 (逐页自查见各页页脚)"
                     % (self.c.version, time.strftime("%Y-%m-%d %H:%M:%S"),
                        len(self.c.nodes), len(self.c.links)))
        self.page_marks.append({"page": 1, "nodes": 0, "links": 0, "kind": "cover"})

    def overview(self, pages_hint: int = 11):
        self.pdf.showPage()
        self.page_no += 1
        cw = self.c.x1 - self.c.x0
        ch = self.c.y1 - self.c.y0
        pw = PAGE_W
        ph = MARGIN * 2 + FOOTER_H + (pw - 2 * MARGIN) * ch / cw
        self.set_window(self.c.x0, self.c.y0, self.c.x1, self.c.y1, pw, ph)
        p = self.pdf
        p.setFillColor(white)
        p.rect(0, 0, pw, ph, fill=1, stroke=0)
        self.header("全图总览 (89 节点 / 182 连线 · 比例尺 %.3f pt/px)" % self.s, "整个画布一页容纳; 细节看后面的分层详图")
        p.saveState()
        pth = p.beginPath()
        pth.rect(MARGIN - 6, self.oy - 6, pw - 2 * MARGIN + 12, ph - self.oy - MARGIN + 12)
        p.clipPath(pth, stroke=0)
        n_here, l_here = self.page_count_marks(self.c.x0, self.c.y0, self.c.x1, self.c.y1)
        self.bands(self.c.x0, self.c.y0, self.c.x1, self.c.y1)
        self.links(self.c.x0, self.c.y0, self.c.x1, self.c.y1, "ov")
        self.nodes(self.c.x0, self.c.y0, self.c.x1, self.c.y1)
        p.restoreState()
        self.footer(self.page_no, pages_hint, n_here, l_here)

    ROW_TITLES = ["行带组① 数据源 · L5 大模型层 · L4 专家层 · L3 高级层 · 记忆中枢",
                  "行带组② L2 记忆 · 分段感知/控制/状态机 · 原子技能库 SK01-08",
                  "行带组③ 执行层 · 验证层 · 可视化层"]

    def rows_abs(self):
        """3 个行带组的 y 切点 —— **从行带之间的空白自动推导**(不写死坐标, 未来画布改版也成立)。

        候选切点 = 相邻行带之间的空档中点; 在其中选 2 个使 3 组节点数最均衡 (每组 ≥5 个节点)。
        """
        import itertools
        bands = self.c.bands
        cands = []
        for i in range(len(bands) - 1):
            g0 = bands[i]["y"] + bands[i]["h"]
            g1 = bands[i + 1]["y"]
            if g1 - g0 >= 40:
                cands.append((g0 + g1) * 0.5)
        top, bot = self.c.y0 - 40, self.c.y1 + 40

        def cnt(y0, y1):
            return sum(1 for n in self.c.boxes if y0 <= n["y"] + n["h"] * 0.5 <= y1)

        if len(cands) >= 2:
            N = len(self.c.boxes) / 3.0
            best = None
            for a, b in itertools.combinations(sorted(cands), 2):
                groups = [(top, a), (a, b), (b, bot)]
                ks = [cnt(*g) for g in groups]
                if min(ks) < 5:
                    continue
                cost = sum(((k - N) / max(1.0, N)) ** 2 for k in ks)
                if best is None or cost < best[0]:
                    best = (cost, groups)
            if best:
                return best[1]
        med = sorted(n["y"] + n["h"] * 0.5 for n in self.c.boxes)
        return [(top, med[len(med) // 3]), (med[len(med) // 3], med[2 * len(med) // 3]),
                (med[2 * len(med) // 3], bot)]

    def row_boxes(self, ri: int):
        ry0, ry1 = self.rows_abs()[ri]
        inside = [n for n in self.c.boxes if ry0 <= n["y"] + n["h"] * 0.5 <= ry1]
        return inside or self.c.boxes

    def detail_plan(self):
        """[(ri, (ry0,ry1), [(cx0,cx1), ...]), ...] —— 详图分页计划 (页数唯一真源)。"""
        out = []
        for ri, (ry0, ry1) in enumerate(self.rows_abs()):
            out.append((ri, (ry0, ry1), self.plan_columns(self.row_boxes(ri))))
        return out

    @staticmethod
    def plan_columns(boxes, max_cols: int = 4, target_w: float = 6200.0):
        """选列数与列边界: 切点只能落在**节点之间 ≥250px 的空档中点** (绝不切断节点),
        代价 = 列宽不均衡 + 节点数不均衡 ⇒ 自动避免"某一列只有 1 个节点/几乎空白"的废页。"""
        import itertools
        segs = sorted((n["x"], n["x"] + n["w"]) for n in boxes)
        ex0, ex1 = segs[0][0] - 70, segs[-1][1] + 70
        extent = ex1 - ex0
        maxc = max(1, min(max_cols, int(extent / target_w) + 1))
        gaps, cur = [], segs[0][1]
        for a, b in segs[1:]:
            if a > cur + 250:
                gaps.append((cur + a) * 0.5)
            cur = max(cur, b)
        best = None
        for ncol in range(1, maxc + 1):
            for comb in itertools.combinations(gaps, ncol - 1):
                bs = [ex0] + list(comb) + [ex1]
                cols = [(bs[i], bs[i + 1]) for i in range(ncol)]
                if any(c1 - c0 < 3500.0 for c0, c1 in cols):
                    continue                                        # 过窄列 (白白放大)
                k_ideal = len(boxes) / ncol
                cost = 0.0
                for c0, c1 in cols:
                    n_in = sum(1 for s in segs if c0 <= (s[0] + s[1]) * 0.5 < c1)
                    cost += ((c1 - c0) / target_w) ** 2             # 列越宽 ⇒ 比例尺越小 ⇒ 越不清晰
                    cost += 2.5 * ((n_in - k_ideal) / max(1.0, k_ideal)) ** 2
                if best is None or cost < best[0]:
                    best = (cost, cols)
        return best[1] if best else [(ex0, ex1)]

    def detail_pages(self, pages_hint: int = 11):
        """分层详图: 3 个行带组 (语义分组) × 每组按节点 x 空档自适应分列 (见 plan_columns)。"""
        plan = self.detail_plan()
        for ri, (ry0, ry1), cols in plan:
            ncol = len(cols)
            for ci, (cx0, cx1) in enumerate(cols):
                self.pdf.showPage()
                self.page_no += 1
                self.set_window(cx0, ry0, cx1, ry1, PAGE_W, DETAIL_H)
                p = self.pdf
                p.setFillColor(white)
                p.rect(0, 0, PAGE_W, DETAIL_H, fill=1, stroke=0)
                self.header("%s  ·  第 %d/%d 列" % (self.ROW_TITLES[ri], ci + 1, ncol),
                            "内容窗口 x %d..%d · y %d..%d · 比例尺 %.3f pt/px (矢量, 可放大)"
                            % (cx0, cx1, ry0, ry1, self.s))
                p.saveState()
                pth = p.beginPath()
                pth.rect(MARGIN - 6, self.oy - 6, PAGE_W - 2 * MARGIN + 12,
                         DETAIL_H - self.oy - MARGIN + 12)
                p.clipPath(pth, stroke=0)
                n_here, l_here = self.page_count_marks(cx0, ry0, cx1, ry1)
                self.bands(cx0, ry0, cx1, ry1)
                self.links(cx0, ry0, cx1, ry1, "d%d%d" % (ri, ci))
                self.nodes(cx0, ry0, cx1, ry1)
                p.restoreState()
                self.footer(self.page_no, pages_hint, n_here, l_here)

    def run(self, preview: bool = True) -> dict:
        det = list(self.detail_plan())
        pages = 2 + sum(len(c) for _, _, c in det)                     # 封面 + 总览 + 详图
        self.cover(det_hint=sum(len(c) for _, _, c in det))
        self.overview(pages)
        self.detail_pages(pages)
        self.pdf.showPage()
        self.pdf.save()

        missing_n = [n["id"] for n in self.c.nodes if n["id"] not in self.c.drawn_nodes]
        missing_l = [i for i in range(len(self.c.links)) if i not in self.c.drawn_links]
        meta = {
            "version": self.c.version, "ts": time.time(), "md5": self.c.md5,
            "nodes": len(self.c.nodes), "links": len(self.c.links),
            "nodes_drawn": len(self.c.drawn_nodes), "links_drawn": len(self.c.drawn_links),
            "pages": self.page_no, "bytes": self.out.stat().st_size,
            "pdf": str(self.out), "bands": len(self.c.bands),
            "dangling_links": len(self.c.dangling),
            "missing_nodes": missing_n[:20], "missing_links": missing_l[:20],
            "page_marks": self.page_marks,
        }
        if preview:
            png = self.out.parent / (self.out.stem + "_p1.png")
            try:
                subprocess.run(["pdftoppm", "-png", "-r", "70", "-f", "1", "-l", "1",
                                str(self.out), str(png.with_suffix(""))],
                               check=True, capture_output=True, timeout=180)
                meta["preview"] = str(list(self.out.parent.glob(png.stem + "*.png"))[0])
            except Exception as e:                                              # noqa: BLE001
                meta["preview_err"] = "%s: %s" % (type(e).__name__, e)
        return meta


def build(out: Path | None = None, preview: bool = True) -> dict:
    register_font()
    j = CP.load_canvas()
    md5 = CP.source_md5()
    version = CP.version_of(md5)
    c = Canvas(j, version, md5)
    out = Path(out) if out else CP.OUT_DIR / ("canvas_%s.pdf" % version)
    out.parent.mkdir(parents=True, exist_ok=True)
    p = Painter(c, out)
    meta = p.run(preview=preview)
    meta["src"] = str(CP.source_json())
    return meta


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="")
    ap.add_argument("--no-preview", action="store_true")
    a = ap.parse_args()
    m = build(Path(a.out) if a.out else None, preview=not a.no_preview)
    print(json.dumps(m, ensure_ascii=False, indent=1))
    ok = (m["nodes_drawn"] == m["nodes"] and m["links_drawn"] == m["links"]
          and m["dangling_links"] == 0)
    print("[PDF自查] 节点 %d/%d · 连线 %d/%d · 页数 %d · %s"
          % (m["nodes_drawn"], m["nodes"], m["links_drawn"], m["links"], m["pages"],
             "通过" if ok else "不通过"))
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
