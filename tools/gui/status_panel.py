#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📊 左下角常驻状态面板 (Z-MAX 控制台 · 2026-10-01 老倪)

老倪原话: 「将硬件 GPU CPU 内存 磁盘大小等状态、状态空间的在役模型版本号、模型是否在推理、
训练中的模型版本号、模型是否在训练的状态、数据生成的场景 3DGS 数据资产版本号, 这些信息都
推到 8796 服务, 放在窗口左下角, 注意要用红绿灯、状态条、进度条等控件显示, 不要占用太大面积,
不要用很多文字, 我要看状态」⇒ 本控件: **极小面积 + 极少文字**, 文字只留 3~4 字符数字与
极短版本号, 其余全靠 红绿灯 / 状态条 / 进度条 表达, 详细内容放 tooltip(悬停才看)。

数据源 (冻结契约, 由 8796 服务端提供):
  { "ts": float,
    "hw": {"gpu": {"util","mem_used_mb","mem_total_mb","temp_c","name"},
           "cpu": {"util","cores","load1"},
           "mem": {"used_gb","total_gb"},
           "disk": {"used_gb","total_gb","pct"}},
    "models":  [{"layer","name","version","state":"in_service|candidate|untrained","inferring":bool}],
    "training":{"active","layer","name","version","step","total","pct","eta_s","speed_s_per_step"},
    "assets":  [{"kind":"3DGS","name","version","path"}] }

形态 (两行, 总 420x68 px):
  第1行  GPU/CPU/内存/磁盘: Ø8 灯 + 名称 + 迷你状态条(40x7) + 3~4 字符数值   ... 右端 通信灯
  第2行  模型: Ø8 灯 + 层标签(L2..) + 极短版本 + 推理(▲)/训练(◐)标记;
         训练中额外一条进度条(74x7) + %;  末尾 3DGS v<版本>
颜色语义: 绿=在役&健康 · 黄=候选或忙 · 红=异常/未训练 · 灰=未知(含服务不可达)

运行/自检:
  QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/gui/status_panel.py --selftest
  QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/gui/status_panel.py --live-shot /tmp/p.png --seconds 3
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
import urllib.request

from PyQt5.QtCore import Qt, QPointF, QRectF, QThread, QTimer
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPolygonF
from PyQt5.QtWidgets import QApplication, QWidget

# ---- 配色 (与 tools/gui/hw_widgets.py 同一套口径) ----
C_BG2, C_BORDER = "#161b22", "#30363d"
C_WHITE, C_GRAY, C_DIM = "#e6edf3", "#8b949e", "#6e7681"
C_GREEN, C_YELLOW, C_RED, C_CYAN = "#3fb950", "#d29922", "#f85149", "#39d0d8"
TRACK = "#2b3340"
UI, MONO = "Noto Sans CJK SC", "Consolas"

# 状态 → 灯色
STATE_COLOR = {"in_service": C_GREEN, "candidate": C_YELLOW, "untrained": C_RED}
LAYER_ORDER = ("L2", "L3", "L4", "L5")

DEFAULT_URL = os.environ.get("ZMAX_STATUS_URL", "http://127.0.0.1:8796/status/all")


def tone(v, lo=70.0, hi=90.0):
    """利用率 → 颜色。缺测(None) = 灰 (不画 0 冒充)。"""
    try:
        if v is None:
            return C_DIM
        f = float(v)
    except Exception:
        return C_DIM
    return C_GREEN if f < lo else (C_YELLOW if f < hi else C_RED)


def _num(v):
    try:
        return int(round(float(v)))
    except Exception:
        return None


def _txt(v, suffix="%"):
    n = _num(v)
    if n is None:
        return "—"
    s = str(max(0, min(999, n)))
    return s + suffix


_DATE_PRE = re.compile(r"^v?\d{8}-")


def short_ver(v):
    """极短版本号: 去掉所有模型共有的日期前缀(v20261001-), 优先留最能区分的尾巴。

    'v20261001-annot' -> 'annot' · 'v20261001-r6' -> 'r6' ·
    'smolvla_lew_v10_1h/004000' -> '004000' · 'v1001-r6' -> 'r6' · 'unknown' -> 'unknown'
    """
    v = str(v or "").strip()
    if not v:
        return "—"
    v = _DATE_PRE.sub("", v)
    if "/" in v:
        v = v.split("/")[-1]
    parts = v.split("-")
    if (len(parts) > 1 and 1 <= len(parts[-1]) <= 8 and len(parts[0]) >= 4
            and any(c.isdigit() for c in parts[0])):
        v = parts[-1]            # 头像版本号(v1001 / v20261001)才换成尾巴; 'deepseek-vl' 这类保持原名
    return v or "—"


# ============================================================
# 取数线程: 只往队列里放, 绝不碰任何 Qt 控件
# ============================================================
class _Fetcher(QThread):
    def __init__(self, url, out, interval=1.0, timeout=0.9, parent=None):
        super().__init__(parent)
        self.url = url
        self.out = out                      # list, 主线程消费
        self.interval = float(interval)
        self.timeout = float(timeout)
        self._stop = threading.Event()
        self.setObjectName("status_panel_fetch")

    def stop(self):
        self._stop.set()

    def run(self):
        while not self._stop.is_set():
            t0 = time.time()
            try:
                req = urllib.request.Request(self.url, headers={"Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    body = r.read(262144)
                obj = json.loads(body.decode("utf-8", "replace"))
                if isinstance(obj, dict):
                    self.out.append((True, obj, time.time()))
                else:
                    self.out.append((False, "not-a-dict", time.time()))
            except Exception as e:                                  # 读失败静默降级
                self.out.append((False, "%s: %s" % (type(e).__name__, e), time.time()))
            # 只留最近 2 条, 防无界增长
            del self.out[:-2]
            self._stop.wait(max(0.05, self.interval - (time.time() - t0)))


# ============================================================
# 面板
# ============================================================
class StatusPanel(QWidget):
    W, H = 420, 68
    POLL_MS = 1000
    MAX_CHIPS = 4

    def __init__(self, parent=None, url=None, poll=True):
        super().__init__(parent)
        self.url = url or DEFAULT_URL
        self.setFixedSize(self.W, self.H)
        self.setToolTip("状态面板: 等待 8796 /status/all …")
        self._obj = None                    # 最近一次成功载荷
        self._err = "未连接"                # 最近一次失败原因 (不显示在界面上, 只进 tooltip)
        self._age = None                    # 最近一次成功取数的时刻
        self._sig = None                    # 值变化才重绘
        self._queue = []
        self._worker = None
        if poll:
            self._worker = _Fetcher(self.url, self._queue, interval=self.POLL_MS / 1000.0, parent=self)
            self._worker.start()
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._tick)
            self._timer.start(self.POLL_MS)
            app = QApplication.instance()
            if app is not None:
                try:
                    app.aboutToQuit.connect(self.shutdown)
                except Exception:
                    pass

    # ---------- 生命周期 ----------
    def shutdown(self):
        try:
            self._timer.stop()
        except Exception:
            pass
        w = self._worker
        if w is not None and w.isRunning():
            w.stop()
            w.wait(2000)

    def closeEvent(self, e):                                            # noqa: N802
        self.shutdown()
        super().closeEvent(e)

    # ---------- 取数消费 (主线程) ----------
    def _tick(self):
        try:
            if self._queue:
                ok, payload, ts = self._queue[-1]
                del self._queue[:]
                if ok:
                    self._obj, self._age, self._err = payload, ts, None
                else:
                    self._obj, self._err = None, str(payload)
                self._apply()
        except Exception:
            pass                                                        # 轮询绝不炸 UI

    def _apply(self):
        sig = self._signature()
        if sig == self._sig:                                            # 值没变不重绘(省 GPU)
            return
        self._sig = sig
        self._refresh_tooltip()
        self.update()

    def _signature(self):
        try:
            return self._signature_inner()
        except Exception as e:                                          # 畸形载荷: 退化成"每次重绘"
            return ("bad", repr(e))

    def _signature_inner(self):
        d = self._obj
        if not isinstance(d, dict):
            return ("err", self._err)
        hw = d.get("hw") or {}
        g = (hw.get("gpu") or {})
        c = (hw.get("cpu") or {})
        m = (hw.get("mem") or {})
        k = (hw.get("disk") or {})
        mods = tuple((str(x.get("layer", "")), str(x.get("version", "")), str(x.get("state", "")),
                      bool(x.get("inferring"))) for x in (d.get("models") or []) if isinstance(x, dict))
        tr = d.get("training") or {}
        trs = (bool(tr.get("active")), str(tr.get("layer", "")), str(tr.get("version", "")),
               _num(tr.get("pct")), _num(tr.get("step")))
        asst = tuple((str(x.get("kind", "")), str(x.get("version", "")))
                     for x in (d.get("assets") or []) if isinstance(x, dict))
        return (_num(g.get("util")), _num(g.get("temp_c")), _num(c.get("util")),
                _num((float(m.get("used_gb") or 0) / float(m.get("total_gb") or 1)) * 100) if m.get("total_gb") else None,
                _num(k.get("pct")), mods, trs, asst)

    # ---------- 供自检/手动喂数 ----------
    def feed(self, obj):
        self._obj, self._age, self._err = obj, time.time(), None
        self._apply()

    def feed_error(self, msg="unavailable"):
        self._obj, self._err, self._age = None, msg, None
        self._apply()

    # ---------- 数据派生 (全部防御式, 缺字段=缺测, 绝不抛) ----------
    def _rows(self):
        d = self._obj if isinstance(self._obj, dict) else {}
        hw = d.get("hw") if isinstance(d.get("hw"), dict) else {}
        gpu = hw.get("gpu") if isinstance(hw.get("gpu"), dict) else {}
        cpu = hw.get("cpu") if isinstance(hw.get("cpu"), dict) else {}
        mem = hw.get("mem") if isinstance(hw.get("mem"), dict) else {}
        dsk = hw.get("disk") if isinstance(hw.get("disk"), dict) else {}
        g_u, c_u = _num(gpu.get("util")), _num(cpu.get("util"))
        m_u = None
        try:
            if mem.get("total_gb"):
                m_u = _num(float(mem.get("used_gb") or 0) / float(mem["total_gb"]) * 100.0)
        except Exception:
            m_u = None
        d_u = _num(dsk.get("pct"))
        if d_u is None and dsk.get("total_gb"):
            try:
                d_u = _num(float(dsk.get("used_gb") or 0) / float(dsk["total_gb"]) * 100.0)
            except Exception:
                d_u = None
        row1 = [("GPU", g_u), ("CPU", c_u), ("内存", m_u), ("磁盘", d_u)]
        return row1, gpu, cpu, mem, dsk

    def _models(self):
        d = self._obj if isinstance(self._obj, dict) else {}
        ms = [x for x in (d.get("models") or []) if isinstance(x, dict)]

        def _key(x):
            ly = str(x.get("layer", ""))
            return (LAYER_ORDER.index(ly) if ly in LAYER_ORDER else 9, ly)
        return sorted(ms, key=_key)

    def _training(self):
        d = self._obj if isinstance(self._obj, dict) else {}
        t = d.get("training")
        return t if isinstance(t, dict) else {}

    def _chips(self):
        """按层聚合 (型号可能一层多个): 每层一个 chip —— 优先展示**在役**那一个的版本号,
        灯色取该层最好状态 (在役>候选>未训练), 推理标记 = 该层任一在推理。
        ⇒ 一排就看得出「哪层在役/哪层只是候选/哪层没训过」。最多 MAX_CHIPS 层, 其余聚合成 ×N。
        """
        groups = {}
        order = []
        for m in self._models():
            ly = str(m.get("layer") or "?")
            if ly not in groups:
                groups[ly] = []
                order.append(ly)
            groups[ly].append(m)
        chips = []
        for ly in order:
            ms = groups[ly]
            prim = None
            for st in ("in_service", "candidate", "untrained"):
                for x in ms:
                    if str(x.get("state")) == st:
                        prim = x
                        break
                if prim is not None:
                    break
            prim = prim or ms[0]
            chips.append({"layer": ly, "state": str(prim.get("state") or ""),
                          "version": prim.get("version"), "inferring": any(bool(x.get("inferring")) for x in ms),
                          "n": len(ms), "in_service": any(str(x.get("state")) == "in_service" for x in ms)})
        if not chips:
            # 读不到/服务不可达 ⇒ 占位灰灯 (行形状不变, 一眼看出"没数据"而不是"没这一层")
            chips = [{"layer": ly, "state": "", "version": "", "inferring": False,
                      "n": 0, "in_service": False, "placeholder": True} for ly in LAYER_ORDER]
        return chips

    def _assets(self):
        d = self._obj if isinstance(self._obj, dict) else {}
        return [x for x in (d.get("assets") or []) if isinstance(x, dict)]

    def _refresh_tooltip(self):
        try:
            self._refresh_tooltip_inner()
        except Exception:
            self.setToolTip("状态面板 · %s" % self.url)

    def _refresh_tooltip_inner(self):
        d = self._obj
        if not isinstance(d, dict):
            self.setToolTip("状态面板 · 8796 /status/all 不可达\n%s\n%s" % (self.url, self._err or ""))
            return
        _, gpu, cpu, mem, dsk = self._rows()
        gpu = gpu or {}
        cpu = cpu or {}
        mem = mem or {}
        dsk = dsk or {}
        L = ["状态面板 · %s" % self.url]
        L.append("GPU %s · util %s%% · 显存 %s/%s MB · %s°C" % (
            gpu.get("name", "—"), _num(gpu.get("util")), gpu.get("mem_used_mb", "—"),
            gpu.get("mem_total_mb", "—"), gpu.get("temp_c", "—")))
        L.append("CPU %s 核 · util %s%% · load1 %s" % (
            cpu.get("cores", "—"), _num(cpu.get("util")), cpu.get("load1", "—")))
        L.append("内存 %s/%s GB · 磁盘 %s/%s GB (%s%%)" % (
            mem.get("used_gb", "—"), mem.get("total_gb", "—"),
            dsk.get("used_gb", "—"), dsk.get("total_gb", "—"), dsk.get("pct", "—")))
        L.append("模型 (%d):" % len(self._models()))
        for m in self._models():
            L.append("  [%s] %s · %s · %s%s" % (
                m.get("layer", "?"), m.get("name", "?"), m.get("version", "?"),
                m.get("state", "?"), " · 推理中" if m.get("inferring") else ""))
        t = self._training()
        if t.get("active"):
            L.append("训练中: [%s] %s · %s · %s/%s (%s%%) · eta %ss · %s s/step" % (
                t.get("layer", "?"), t.get("name", "?"), t.get("version", "?"),
                t.get("step", "?"), t.get("total", "?"), t.get("pct", "?"),
                t.get("eta_s", "?"), t.get("speed_s_per_step", "?")))
        else:
            L.append("训练中: 无")
        for a in self._assets():
            L.append("资产: %s %s · %s · %s" % (a.get("kind", ""), a.get("version", ""),
                                                a.get("name", ""), a.get("path", "")))
        self.setToolTip("\n".join(L))

    # ---------- 绘制 ----------
    def paintEvent(self, _e):                                           # noqa: N802
        try:
            self._paint()
        except Exception:                                               # paint 内异常会 abort 全进程
            pass

    def _paint(self):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(C_BG2))
        p.setPen(QPen(QColor(C_BORDER), 1))
        p.drawLine(0, 0, w, 0)

        # 字体一律用 setPixelSize (本机 Qt 字体 DPI≈192, pt 会放大 ~1.5 倍 ⇒ 撑破小框)
        f_lb = QFont(UI)
        f_lb.setPixelSize(10)
        f_sm = QFont(MONO)
        f_sm.setPixelSize(11)
        f_ver = QFont(MONO)
        f_ver.setPixelSize(10)
        f_num = QFont(MONO)
        f_num.setPixelSize(11)
        f_num.setBold(True)
        f_sb = QFont(MONO)
        f_sb.setPixelSize(11)
        f_sb.setBold(True)

        row1, gpu, cpu, mem, dsk = self._rows()
        y1 = 6.0
        gw = 98.0
        for i, (cap, val) in enumerate(row1):
            x0 = 6.0 + i * gw
            col = QColor(tone(val))
            self._lamp(p, x0 + 5, y1 + 16, col, val is not None)
            p.setPen(QColor(C_GRAY))
            p.setFont(f_lb)
            p.drawText(QRectF(x0 + 11, y1, 21, 32), Qt.AlignVCenter | Qt.AlignLeft,
                       QFontMetrics(f_lb).elidedText(cap, Qt.ElideRight, 21))
            # 迷你状态条
            bx, bw, bh = x0 + 34, 34, 7
            by = y1 + 16 - bh / 2.0
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(TRACK))
            p.drawRoundedRect(QRectF(bx, by, bw, bh), 3.5, 3.5)
            if val is not None:
                p.setBrush(col)
                p.drawRoundedRect(QRectF(bx, by, max(3.0, bw * min(1.0, max(0.0, val / 100.0))), bh), 3.5, 3.5)
            p.setPen(QColor(C_WHITE if val is not None else C_DIM))
            p.setFont(f_num)
            p.drawText(QRectF(x0 + 70, y1, 24, 32), Qt.AlignVCenter | Qt.AlignRight, _txt(val))

        # 通信灯 (绿=最近取数成功; 灰=服务不可达/读失败)
        fresh = self._age is not None and (time.time() - self._age) < max(3.0, self.POLL_MS / 1000.0 * 3)
        self._lamp(p, w - 9, y1 + 16, QColor(C_GREEN if fresh else C_DIM), fresh)

        # ---- 第 2 行 ----
        y2, cy2 = h - 28.0, h - 11.0
        vs = self._chips()
        agg = len(vs) > self.MAX_CHIPS
        n_chips = self.MAX_CHIPS + (1 if agg else 0)
        chipw = 55.0 if agg else 64.0
        for i, m in enumerate(vs[:self.MAX_CHIPS]):
            x = 6.0 + i * chipw
            st = str(m.get("state", ""))
            col = QColor(STATE_COLOR.get(st, C_DIM))
            self._lamp(p, x + 6, cy2, col, st in STATE_COLOR)
            # 推理/训练标记 = 灯的外圈 (青环=推理中 · 黄弧=训练中), 不占额外宽度
            if self._is_training_layer(m.get("layer")):
                p.setPen(QPen(QColor(C_YELLOW), 1.5))
                p.setBrush(Qt.NoBrush)
                p.drawArc(QRectF(x - 0.5, cy2 - 6.5, 13, 13), 40 * 16, 280 * 16)
            elif m.get("inferring"):
                p.setPen(QPen(QColor(C_CYAN), 1.5))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(QRectF(x - 0.5, cy2 - 6.5, 13, 13))
            p.setPen(QColor(C_WHITE))
            p.setFont(f_sm)
            ly = str(m.get("layer", "?"))[:3] or "?"
            p.drawText(QRectF(x + 14, y2, 14, 34), Qt.AlignVCenter | Qt.AlignLeft, ly)
            p.setPen(QColor(C_GRAY))
            p.setFont(f_ver)
            vw = int(chipw - 32)
            p.drawText(QRectF(x + 29, y2, vw, 34), Qt.AlignVCenter | Qt.AlignLeft,
                       QFontMetrics(f_ver).elidedText(short_ver(m.get("version")), Qt.ElideRight, vw))
        if agg:
            n_rest = sum(int(r.get("n") or 1) for r in vs[self.MAX_CHIPS:])
            x = 6.0 + self.MAX_CHIPS * chipw
            worst = C_GREEN if any(r.get("in_service") for r in vs[self.MAX_CHIPS:]) else C_DIM
            self._lamp(p, x + 6, cy2, QColor(worst), True)
            p.setPen(QColor(C_GRAY))
            p.setFont(f_sb)
            p.drawText(QRectF(x + 14, y2, chipw - 16, 34), Qt.AlignVCenter | Qt.AlignLeft,
                       "×%d" % n_rest)

        # 训练进度条 + %
        tx = 6.0 + n_chips * chipw + 6.0
        bar_w = 44.0
        pct_x = tx + bar_w + 3.0
        pct_w = 26.0
        t = self._training()
        if t.get("active"):
            pct = _num(t.get("pct"))
            if pct is None:
                try:
                    pct = _num(float(t.get("step") or 0) / float(t.get("total") or 1) * 100.0)
                except Exception:
                    pct = None
            bw, bh = bar_w, 7
            by = cy2 - bh / 2.0
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(TRACK))
            p.drawRoundedRect(QRectF(tx, by, bw, bh), 3.5, 3.5)
            if pct is not None:
                p.setBrush(QColor(C_CYAN))
                p.drawRoundedRect(QRectF(tx, by, max(3.0, bw * min(1.0, max(0.0, pct / 100.0))), bh), 3.5, 3.5)
            p.setPen(QColor(C_WHITE if pct is not None else C_DIM))
            p.setFont(f_sb)
            p.drawText(QRectF(pct_x, y2, pct_w, 34), Qt.AlignVCenter | Qt.AlignRight, _txt(pct))
        else:
            self._lamp(p, tx + 5, cy2, QColor(C_DIM), False)
            pct_x = tx + 14.0
            pct_w = 8.0

        # 3DGS 资产 (末尾, 极短)
        assets = [a for a in self._assets() if str(a.get("kind", "")).upper() == "3DGS"]
        ver = short_ver(assets[-1].get("version")) if assets else "—"
        label = "3DGS %s" % ver
        if len(assets) > 1:
            label = "3DGS ×%d %s" % (len(assets), ver)
        p.setFont(f_ver)
        xr = w - 6.0
        room = max(24.0, xr - (pct_x + pct_w + 8.0))
        label = QFontMetrics(f_ver).elidedText(label, Qt.ElideRight, int(room))
        tw = QFontMetrics(f_ver).width(label)
        p.setPen(QColor(C_BLUE_A if assets else C_DIM))
        p.drawText(QRectF(xr - tw, y2, tw, 34), Qt.AlignVCenter | Qt.AlignRight, label)
        if room >= 44.0:                       # 挤不下时省掉灯, 只留标签
            self._lamp(p, xr - tw - 8, cy2, QColor(C_GREEN if assets else C_DIM), bool(assets))

    def _is_training_layer(self, layer):
        t = self._training()
        return bool(t.get("active")) and str(t.get("layer", "")) == str(layer)

    @staticmethod
    def _lamp(p, cx, cy, col, on=True):
        """Ø8 红绿灯圆点 (亮=有状态, 灰=未知)"""
        col = QColor(col)
        if on and col.name() != C_DIM:
            glow = QColor(col)
            glow.setAlpha(60)
            p.setPen(Qt.NoPen)
            p.setBrush(glow)
            p.drawEllipse(QRectF(cx - 7, cy - 7, 14, 14))
        p.setBrush(col)
        p.setPen(QPen(QColor("#000000"), 1))
        p.drawEllipse(QRectF(cx - 4, cy - 4, 8, 8))


C_BLUE_A = "#58a6ff"        # 资产标签色 (模块级常量, 与 studio 的 C_BLUE 同值)


# ============================================================
# 自检 / 单机截图
# ============================================================
DEMO = {
    "ts": 1759000000.0,
    "hw": {"gpu": {"util": 97, "mem_used_mb": 21003, "mem_total_mb": 24564, "temp_c": 71,
                   "name": "NVIDIA GeForce RTX 4090"},
           "cpu": {"util": 41, "cores": 16, "load1": 6.52},
           "mem": {"used_gb": 21.4, "total_gb": 31.2},
           "disk": {"used_gb": 812, "total_gb": 1024, "pct": 79}},
    "models": [{"layer": "L2", "name": "YOLO+解析链", "version": "v1001-r6", "state": "in_service", "inferring": True},
               {"layer": "L3", "name": "SmolVLA+LEW", "version": "v1001-r6", "state": "in_service", "inferring": False},
               {"layer": "L4", "name": "INTACT", "version": "r3", "state": "candidate", "inferring": False},
               {"layer": "L5", "name": "planner", "version": "v2", "state": "untrained", "inferring": False}],
    "training": {"active": True, "layer": "L5", "name": "planner", "version": "v7", "step": 12400,
                 "total": 20000, "pct": 62, "eta_s": 1830, "speed_s_per_step": 0.42},
    "assets": [{"kind": "3DGS", "name": "station_scan", "version": "v12", "path": "/home/ubuntu/zmax_data/3dgs/station"}],
}



# 8796 /status/all 真实响应快照 (2026-10-01 抓取, 13 个模型; 模型名截断到 24 字符以省空间)
REAL = {"ts": 0.0, "hw": {"gpu": {"util": 0, "mem_used_mb": 660, "mem_total_mb": 8188, "temp_c": 55, "name": "NVIDIA GeForce RTX 4060 Laptop GPU"}, "cpu": {"util": 9, "cores": 32, "load1": 2.98}, "mem": {"used_gb": 7.7, "total_gb": 31.0}, "disk": {"used_gb": 353, "total_gb": 425, "pct": 83}}, "models": [{"layer": "L2", "name": "YOLO 检测 + 2D→3D 解算 (真机域在", "version": "v20261001-annot", "state": "in_service", "inferring": True}, {"layer": "L2", "name": "SAM3 开放词汇分割 (官方权重 09-29 ", "version": "v20261001-annot_v1", "state": "candidate", "inferring": False}, {"layer": "L2", "name": "状态空间小模型组 (前馈/估计/预测/校正)", "version": "unknown", "state": "in_service", "inferring": True}, {"layer": "L2", "name": "外观质量检测 AOI (金手指/端面)", "version": "unknown", "state": "in_service", "inferring": False}, {"layer": "L3", "name": "SmolVLA+LEW 长程规划 (在役运行时 ", "version": "smolvla_lew_v10_1h/004000", "state": "in_service", "inferring": True}, {"layer": "L3", "name": "SmolVLA+LEW 长程规划 LoRA (7", "version": "v20261001-r6", "state": "candidate", "inferring": False}, {"layer": "L3", "name": "L3 长程序列规划器 TaskPlanner", "version": "unknown", "state": "in_service", "inferring": False}, {"layer": "L3", "name": "Flow-Matching Action Hea", "version": "unknown", "state": "in_service", "inferring": False}, {"layer": "L4", "name": "INTACT-JEPA 意图-动作 (在役稳定指", "version": "intact_l4_current", "state": "in_service", "inferring": True}, {"layer": "L4", "name": "INTACT 世界模型 光模块插入 v6+LoR", "version": "v20261001-r200", "state": "candidate", "inferring": False}, {"layer": "L4", "name": "流形专家预测器 (JEPA: 潜空间→流形→动作", "version": "unknown", "state": "in_service", "inferring": False}, {"layer": "L4", "name": "阶段专家 MOE · 7 专家 + 先验门控路由", "version": "unknown", "state": "in_service", "inferring": False}, {"layer": "L5", "name": "DeepSeek 视觉规划 (L5 大模型主路)", "version": "deepseek-vl", "state": "in_service", "inferring": True}], "training": {"active": False, "layer": "", "name": "", "version": "", "step": 0, "total": 0, "pct": 0, "eta_s": 0, "speed_s_per_step": 0.0, "note": "无 >1500MiB 的计算进程 ⇒ 未在训练"}, "assets": [{"kind": "3DGS", "name": "scene_20261001_run3 · 81612 高斯", "version": "v20261001-574772c8", "path": "/home/ubuntu/zmax_data/gs_assets/scene_20261001_run3/gs.splat"}]}


def _selftest(shot=None):
    app = QApplication.instance() or QApplication(sys.argv[:1])
    ok = True
    res = []

    def chk(name, cond, extra=""):
        nonlocal ok
        ok = ok and bool(cond)
        res.append("%s %s%s" % ("✓" if cond else "✗", name, (" :: " + str(extra)) if extra else ""))

    # 1) 面积红线
    pn = StatusPanel(poll=False)
    chk("面积 ≤ 420x90 px", pn.width() <= 420 and pn.height() <= 90, "%dx%d" % (pn.width(), pn.height()))

    # 2) 颜色阈值
    chk("阈值 69→绿", tone(69) == C_GREEN)
    chk("阈值 70→黄", tone(70) == C_YELLOW)
    chk("阈值 90→红", tone(90) == C_RED)
    chk("缺测→灰", tone(None) == C_DIM)

    # 2b) 极短版本号规则 (8796 真实载荷里的写法)
    chk("short_ver 去日期前缀", short_ver("v20261001-annot") == "annot", short_ver("v20261001-annot"))
    chk("short_ver 留尾巴", short_ver("v20261001-r6") == "r6", short_ver("v20261001-r6"))
    chk("short_ver ckpt 目录", short_ver("smolvla_lew_v10_1h/004000") == "004000", short_ver("smolvla_lew_v10_1h/004000"))
    chk("short_ver 兜底", short_ver("unknown") == "unknown" and short_ver(None) == "—")

    # 2c) 同层多模型 → 聚合成一个 chip 且优先在役
    pn.feed(REAL)
    ch = pn._chips()
    chk("13 模型聚合成 4 层 chip", [c["layer"] for c in ch] == ["L2", "L3", "L4", "L5"], [c["layer"] for c in ch])
    l2 = ch[0]
    chk("L2 chip 取在役模型版本", short_ver(l2["version"]) == "annot" and l2["state"] == "in_service", l2)
    chk("L2 chip 标记推理中", l2["inferring"] is True)

    # 3) 正常载荷: 渲染不崩 + 有内容
    pn.feed(DEMO)
    img = pn.grab().toImage()
    nonbg = sum(1 for y in range(0, img.height(), 2) for x in range(0, img.width(), 2)
                if abs(img.pixelColor(x, y).red() - 0x16) > 12 or abs(img.pixelColor(x, y).green() - 0x1b) > 12)
    chk("正常载荷渲染有内容(非背景像素)", nonbg > 200, nonbg)
    if shot:
        pn.grab().save(shot)
    chk("tooltip 含全部模型与训练", all(k in pn.toolTip() for k in ("L2", "L3", "L4", "L5", "训练中", "3DGS")),
        pn.toolTip().splitlines()[0])

    # 4) 服务不可用 → 灰点, 不崩
    pn.feed_error("ConnectionRefusedError")
    im2 = pn.grab().toImage()
    chk("降级不崩且能重绘", im2.width() == pn.width() and im2.height() == pn.height())
    if shot:
        pn.grab().save(shot.replace(".png", "_degraded.png"))
    chk("降级 tooltip 明写不可达", "不可达" in pn.toolTip())

    # 4b) 多模型(6 个) → 聚合位渲染不崩, 仍 ≤420 宽
    many = json.loads(json.dumps(DEMO))
    many["models"] = many["models"] + [{"layer": "L6", "name": "x2", "version": "v9", "state": "in_service", "inferring": True},
                                       {"layer": "L7", "name": "x3", "version": "v8", "state": "candidate", "inferring": False}]
    pn.feed(many)
    pn.grab()
    chk("6 模型走聚合位不崩", pn.width() == 420)
    if shot:
        pn.grab().save(shot.replace(".png", "_many.png"))

    # 5) 畸形载荷防御
    bad = [None, {}, {"hw": None}, {"hw": {"gpu": {"util": "x"}}, "models": "nope", "training": [], "assets": {}},
           {"hw": {"mem": {"used_gb": None, "total_gb": 0}}, "disk": {"pct": "abc"}},
           {"models": [{"layer": "L4"}], "training": {"active": True, "pct": None, "step": 3, "total": 0}}]
    for i, b in enumerate(bad):
        try:
            pn.feed(b)
            pn.grab()
            chk("畸形载荷 #%d 不崩" % i, True)
        except Exception as e:
            chk("畸形载荷 #%d 不崩" % i, False, repr(e))

    # 6) 无服务真实构造 (3s 轮询尝试) → 灰, 不崩
    pn2 = StatusPanel(poll=True, url="http://127.0.0.1:59999/status/all")
    pn2._worker.interval = 0.3
    t0 = time.time()
    while time.time() - t0 < 1.6:
        app.processEvents()
        time.sleep(0.05)
    pn2.grab()
    chk("连不上时仍为灰灯", pn2._obj is None and pn2._err is not None, pn2._err)
    pn2.shutdown()

    print("\n".join(res))
    print("SELFTEST %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def _live_shot(path, url, seconds):
    app = QApplication.instance() or QApplication(sys.argv[:1])
    pn = StatusPanel(url=url)
    pn.show()
    t0 = time.time()
    while time.time() - t0 < float(seconds):
        app.processEvents()
        time.sleep(0.05)
    pn.grab().save(path)
    print("shot=%s url=%s data=%s err=%s tooltip=%s" % (
        path, url, "ok" if isinstance(pn._obj, dict) else "none", pn._err, pn.toolTip().replace("\n", " | ")))
    pn.shutdown()
    return 0 if isinstance(pn._obj, dict) else 3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--shot", default="")
    ap.add_argument("--live-shot", default="")
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--seconds", type=float, default=3.0)
    a = ap.parse_args()
    if a.selftest:
        return _selftest(a.shot or None)
    if a.live_shot:
        return _live_shot(a.live_shot, a.url, a.seconds)
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
