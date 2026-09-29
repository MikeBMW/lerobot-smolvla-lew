#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🖥 硬件可视化控件 (2026-09-29 老倪:「不要用那么多文字来表达, 要换成状态条, 圆环百分比,
再加上红绿灯这样的指示灯, 重新设计 UI 参考 CANoe hardware / Vector Hardware Manager」)

三个自绘控件 + 一个装配体:
  Ring    圆环百分比 (弧 + 中心数值 + 极短标题), 缺测画灰环 + '—'
  StatBar 状态条 (名称 + 圆角条 + 数值), 颜色按阈值 (绿/黄/红)
  Lamp    指示灯 (发光圆点 + 设备名 + 一行小字)
  HwVisual  装配: 设备灯带(本机放最右/最后) → 圆环行 → 状态条行

配色/阈值口径: 绿 ok · 黄 警戒 · 红 危险 · 灰 缺测(不画 0 冒充)。
  GPU 利用率: 空闲(<5%)灰, 在跑绿; **训练中 <50% 判黄**(老倪的掉载口径: 训练须满负荷)
  显存/CPU/内存: <80 绿 · 80-92 黄 · >92 红     磁盘: <80 绿 · 80-90 黄 · >90 红
  温度: <70 绿 · 70-82 黄 · >82 红              功耗: 按 nvidia-smi power.limit 的比例
"""
from __future__ import annotations

from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

C_BG, C_BG2, C_CARD, C_BORDER = "#0d1117", "#161b22", "#1c2333", "#30363d"
C_WHITE, C_GRAY, C_DIM, C_BLUE = "#ffffff", "#8b949e", "#6e7681", "#58a6ff"
C_GREEN, C_YELLOW, C_RED, C_CYAN = "#3fb950", "#d29922", "#f85149", "#39d0d8"
TRACK = "#2b3340"           # 状态条底槽: 原用卡底色 ⇒ 看不出量程(质检)
UI, MONO = "Arial", "Consolas"


def _tone(pct, lo=80.0, hi=92.0):
    if pct is None:
        return C_DIM
    return C_GREEN if pct < lo else (C_YELLOW if pct < hi else C_RED)


def _tone_temp(t):
    if t is None:
        return C_DIM
    return C_GREEN if t < 70 else (C_YELLOW if t < 82 else C_RED)


class Ring(QWidget):
    """圆环百分比: 弧从 12 点顺时针, 中心大号数值, 环下极短标题"""

    def __init__(self, caption="", unit="%", parent=None):
        super().__init__(parent)
        self.caption = caption
        self.unit = unit
        self._frac = None          # None = 缺测
        self._text = "—"
        self._color = C_DIM
        self._sub = ""
        self.setMinimumSize(132, 150)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def set_value(self, frac, text=None, color=None, sub=""):
        self._frac = None if frac is None else max(0.0, min(1.0, float(frac)))
        self._text = "—" if text is None else str(text)
        self._color = color or C_BLUE
        self._sub = sub or ""
        self.update()

    def paintEvent(self, _e):                                                    # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        d = min(w, h - 26) - 10
        r = QRectF((w - d) / 2.0, 4.0, d, d)
        pen = QPen(QColor(C_BORDER), 9)
        pen.setCapStyle(Qt.FlatCap)      # 质检: 圆头端帽让弧比数值多 ~8.6°(34% 看着像 36%)
        p.setPen(pen)
        p.drawArc(r, 0, 360 * 16)
        if self._frac is not None and self._frac > 0:
            pen2 = QPen(QColor(self._color), 9)
            pen2.setCapStyle(Qt.FlatCap)
            p.setPen(pen2)
            p.drawArc(r, 90 * 16, -int(360 * 16 * self._frac))
        # 中心文字
        p.setPen(QColor(C_WHITE if self._frac is not None else C_DIM))
        f = QFont(MONO, 15, QFont.Bold)
        p.setFont(f)
        p.drawText(QRectF(0, 4 + d * 0.28, w, d * 0.44), Qt.AlignCenter, self._text)
        if self._sub:
            p.setPen(QColor(C_GRAY))
            p.setFont(QFont(MONO, 9))            # 质检: 中文/数字字号不一、基线差 5px → 统一等宽 9pt
            p.drawText(QRectF(0, 4 + d * 0.60, w, d * 0.34), Qt.AlignCenter, self._sub)
        # 环下标题
        p.setPen(QColor(C_GRAY))
        p.setFont(QFont(UI, 10, QFont.Bold))
        p.drawText(QRectF(0, h - 22, w, 20), Qt.AlignCenter, self.caption)


class StatBar(QWidget):
    """状态条: 左名称 · 中圆角条(底色=轨) · 右数值。缺测画空轨 + '—'"""

    def __init__(self, caption="", unit="", parent=None):
        super().__init__(parent)
        self.caption = caption
        self.unit = unit
        self._frac = None
        self._text = "—"
        self._color = C_DIM
        self.setFixedHeight(34)
        self.setMinimumWidth(300)

    def set_value(self, frac, text=None, color=None):
        self._frac = None if frac is None else max(0.0, min(1.0, float(frac)))
        self._text = "—" if text is None else str(text)
        self._color = color or C_BLUE
        self.update()

    def paintEvent(self, _e):                                                    # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        p.setPen(QColor(C_GRAY))
        p.setFont(QFont(UI, 10))
        p.drawText(QRectF(0, 0, 150, h), Qt.AlignVCenter | Qt.AlignLeft, self.caption)
        x0, x1 = 158, w - 110
        if x1 - x0 < 40:
            x1 = max(x0 + 40, w - 60)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(TRACK))
        p.drawRoundedRect(QRectF(x0, h / 2.0 - 7, x1 - x0, 14), 7, 7)
        if self._frac:
            p.setBrush(QColor(self._color))
            p.drawRoundedRect(QRectF(x0, h / 2.0 - 7, max(6.0, (x1 - x0) * self._frac), 14), 7, 7)
        p.setPen(QColor(C_WHITE if self._frac is not None else C_DIM))
        p.setFont(QFont(MONO, 11, QFont.Bold))
        p.drawText(QRectF(x1 + 8, 0, w - x1 - 10, h), Qt.AlignVCenter | Qt.AlignRight,
                   "%s%s" % (self._text, self.unit if self._frac is not None else ""))


class Lamp(QWidget):
    """指示灯: 发光圆点 + 设备名 + 一行小字 (红/黄/绿/灰)"""

    COLOR = {"ok": C_GREEN, "warn": C_YELLOW, "err": C_RED, "off": C_DIM, "busy": C_BLUE}

    def __init__(self, name="", parent=None):
        super().__init__(parent)
        self.name = name
        self._state = "off"
        self._sub = ""
        self.setFixedSize(152, 62)

    def set_state(self, state, sub=""):
        self._state = state if state in self.COLOR else "off"
        self._sub = sub or ""
        self.update()

    def paintEvent(self, _e):                                                    # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        col = QColor(self.COLOR[self._state])
        w, h = self.width(), self.height()
        cx, cy, r = 15.0, h / 2.0, 9.0
        if self._state != "off":                       # 光晕(亮=在线)
            glow = QColor(col)
            glow.setAlpha(70)
            p.setPen(Qt.NoPen)
            p.setBrush(glow)
            p.drawEllipse(QRectF(cx - r - 4, cy - r - 4, (r + 4) * 2, (r + 4) * 2))
        p.setBrush(col)
        p.setPen(QPen(QColor("#000000"), 1))
        p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
        p.setPen(QColor(C_WHITE))
        p.setFont(QFont(UI, 10, QFont.Bold))
        nm = self.name
        while nm and QFontMetrics(p.font()).width(nm) > (w - cx - r - 12):
            nm = nm[:-1]
        if nm != self.name:
            nm = self.name[:max(1, len(nm) - 1)] + "…"
        p.drawText(QRectF(cx + r + 6, cy - 20, w - cx - r - 8, 22), Qt.AlignVCenter, nm)
        p.setPen(QColor(C_GRAY))
        p.setFont(QFont(MONO, 8))
        sub = self._sub
        while sub and QFontMetrics(p.font()).width(sub) > (w - cx - r - 12):     # 质检: 小字被硬裁
            sub = sub[:-1]
        if sub != self._sub:
            sub = (self._sub[:max(1, len(sub) - 1)] + "…") if len(self._sub) > 2 else sub
        p.drawText(QRectF(cx + r + 6, cy + 1, w - cx - r - 8, 22), Qt.AlignVCenter, sub)


class HwVisual(QWidget):
    """装配体: 设备灯带 → 圆环行(GPU/显存/CPU/内存) → 状态条行(磁盘/温度/功耗/吞吐)"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._peak_sps = 0.0
        self._peak_w = 0.0
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)

        self.lb_dev = QLabel("设备状态")
        self.lb_dev.setFont(QFont(UI, 10, QFont.Bold))
        self.lb_dev.setStyleSheet(f"color:{C_GRAY};border:none;background:transparent;")
        v.addWidget(self.lb_dev)
        self.row_dev = QHBoxLayout()
        self.row_dev.setSpacing(10)
        v.addLayout(self.row_dev)          # 质检: 原来先 addStretch ⇒ 灯全挤到右边, 左侧 31% 空白
        self._lamps = {}

        self.row_ring = QHBoxLayout()
        self.row_ring.setSpacing(18)
        v.addLayout(self.row_ring)         # 质检: 环只占右端 21% ⇒ 改成每环 stretch=1 铺满
        self.rings = {}
        for key, cap, unit in (("gpu", "GPU 利用率", "%"), ("vram", "显存占用", "%"),
                               ("cpu", "CPU 负载", "%"), ("mem", "内存占用", "%")):
            rg = Ring(cap, unit)
            self.rings[key] = rg
            self.row_ring.addWidget(rg, 1)

        self.row_bar = QHBoxLayout()
        self.row_bar.setSpacing(26)
        v.addLayout(self.row_bar)
        self.bars = {}
        for key, cap, unit in (("disk", "磁盘占用", "%"), ("temp", "GPU 温度", "°C"),
                               ("power", "GPU 功耗", "W"), ("sps", "训练吞吐", " 步/s")):
            b = StatBar(cap, unit)
            self.bars[key] = b
            self.row_bar.addWidget(b, 1)

    # ── 数据入口 (缺字段一律画 '—', 不用 0 冒充) ──
    def set_data(self, m):
        m = m or {}
        loc = m.get("local") or {}
        gu, vu, cu, mu = (loc.get("gpu_util"), loc.get("vram_pct"),
                          loc.get("cpu_pct"), loc.get("mem_pct"))
        training = bool(loc.get("training"))
        gpu_col = C_DIM if (gu is None or gu < 5) else (C_YELLOW if (training and gu < 50) else C_GREEN)
        self.rings["gpu"].set_value((gu or 0) / 100.0 if gu is not None else None,
                                    None if gu is None else "%.0f" % gu, gpu_col,
                                    "训练中" if training else "空闲")
        vu_t = None if vu is None else "%.0f" % vu
        self.rings["vram"].set_value(None if vu is None else vu / 100.0, vu_t, _tone(vu),
                                     "" if loc.get("vram_used_mb") is None
                                     else "%s/%sGB" % (round(loc["vram_used_mb"] / 1024.0),
                                                       round((loc.get("vram_total_mb") or 0) / 1024.0)))
        self.rings["cpu"].set_value(None if cu is None else cu / 100.0,
                                    None if cu is None else "%.0f" % cu, _tone(cu),
                                    "" if not loc.get("cpu_cores") else "%s核" % loc["cpu_cores"])
        self.rings["mem"].set_value(None if mu is None else mu / 100.0,
                                    None if mu is None else "%.0f" % mu, _tone(mu),
                                    "" if loc.get("mem_total_gb") is None
                                    else "%s/%sGB" % (round(loc.get("mem_used_gb") or 0),
                                                      round(loc["mem_total_gb"])))

        dp = loc.get("disk_pct")
        self.bars["disk"].set_value(None if dp is None else dp / 100.0,
                                    None if dp is None else "%.0f" % dp, _tone(dp, 80, 90))
        tp = loc.get("gpu_temp")
        self.bars["temp"].set_value(None if tp is None else tp / 100.0,
                                    None if tp is None else "%.0f" % tp, _tone_temp(tp))
        pw, pl = loc.get("gpu_power"), loc.get("gpu_power_limit")
        if pw:
            self._peak_w = max(self._peak_w, float(pw))
        den = float(pl) if pl else None          # 没有额定限值就不画条(避免"空载也满格"误导)
        self.bars["power"].set_value(None if (pw is None or not den) else pw / den,
                                     None if pw is None else "%.0f" % pw, C_BLUE)
        self.bars["power"].setToolTip("满格 = %s（%s）" % (
            ("%.0fW 额定限值来自 nvidia-smi power.limit" % float(pl)) if pl
            else "本次观测峰值 %.0fW — 未读到 power.limit" % (self._peak_w or 0), "GPU 功耗"))
        sps = loc.get("sps")
        if sps:
            self._peak_sps = max(self._peak_sps, float(sps))
        self.bars["sps"].set_value((float(sps) / self._peak_sps) if (sps and self._peak_sps) else None,
                                   None if sps is None else "%.1f" % sps,
                                   C_GREEN if (sps and training) else (C_BLUE if sps else C_DIM))

        devs = list(m.get("devices") or [])
        if m.get("remote_src"):
            devs.append({"name": "远端数据源", "sub": m["remote_src"], "state": "ok"})
        elif m.get("remote_src_off"):
            devs.append({"name": "远端数据源", "sub": "未连通(仅本机数据)", "state": "err"})
        _ln = (loc.get("gpu_name") or "")[:12].lower()      # 本机显卡名 → 用来认出"同一台机"
        merged = False
        for d in devs:
            if _ln and _ln in str(d.get("sub", "")).lower():
                d["name"], d["sub"], merged = "本机", (loc.get("gpu_name") or "—")[:16], True
        if not merged:
            devs.append({"name": "本机", "sub": (loc.get("gpu_name") or "—")[:16],
                         "state": "ok" if loc.get("gpu_util") is not None else "off"})
        names = [d.get("name") for d in devs if d.get("name") != "本机"] + \
                [d.get("name") for d in devs if d.get("name") == "本机"]      # ★ 本机/4060 排最后
        for n in list(self._lamps):
            if n not in names:
                self._lamps.pop(n).setParent(None)
        for i, n in enumerate(names):
            d = next(x for x in devs if x.get("name") == n)
            if n not in self._lamps:
                self._lamps[n] = Lamp(n)
            self.row_dev.insertWidget(i, self._lamps[n])      # 已存在也重插 → 顺序确定(本机永远最后)
            self._lamps[n].set_state(d.get("state", "off"), d.get("sub", ""))
        self.lb_dev.setText("设备状态")          # 名字在灯上, 不再重复写一遍(老倪: 别那么多文字)
