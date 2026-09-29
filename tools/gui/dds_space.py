#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🌐 全局数据空间 · 控制台视图 (对标 Apollo DreamView 的 channel/频道清单)

设计口径(2026-09-29 老倪: 「全链路 topic 可视化 + 全面数据质量管理 + 数据闭环」):
  · **不做第 13 个模块卡**(老倪投诉过功能重复入口) ⇒ 作为「🌐 全局数据空间」页里的一个 Tab
  · 数据源全部是**已落盘的事实**, 本页不自己采数据(免得又一处口径):
      /home/ubuntu/zmax_data/dataspace/live.json  ← DDS 全链路探针(频率/帧龄/配对/字段真值/质量裁决)
      /home/ubuntu/zmax_data/dataspace/loop.json  ← 闭环九环节证据(pass/fail/unknown)
      src/lerobot/dataspace/topics.py             ← 注册表(话题/类型/QoS/生产者/消费者/门)
  · 老倪要求: 内容可复制可导出(JSON/CSV)、字少不挤不截断、指标不夸大
  · prod 档是"静默正确"(不发=预期) ⇒ 页面必须显式标出当前档位与"本档不发"的原因, 别让人以为是坏了
"""
import csv
import io
import json
import os
import time

LIVE = os.environ.get("ZMAX_DATASPACE_LIVE", "/home/ubuntu/zmax_data/dataspace/live.json")
LOOP = os.environ.get("ZMAX_DATASPACE_LOOP", "/home/ubuntu/zmax_data/dataspace/loop.json")
MODE_FILE = os.path.join(os.path.expanduser("~"), ".zmax_telemetry_mode")
REPO = os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax_rel")

MODE_ORDER = ["prod", "diag", "calib", "test"]


def _load(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                        # noqa: BLE001
        return {}


def registry():
    """注册表(话题/规则/闭环门/模式) —— 从包里读, 不复制一份"""
    try:
        import sys
        if os.path.join(REPO, "src") not in sys.path:
            sys.path.insert(0, os.path.join(REPO, "src"))
        from lerobot.dataspace import topics as T
        return T
    except Exception:                                                        # noqa: BLE001
        return None


def current_mode():
    """档位读取口径与守护一致: env > 运行时(文件) > prod"""
    env = (os.environ.get("ZMAX_TELEMETRY") or "").strip().lower()
    if env:
        return env, "env ZMAX_TELEMETRY(锁定)"
    try:
        with open(MODE_FILE, encoding="utf-8") as f:
            m = f.read().strip().lower()
        if m:
            return m, "运行时文件 ~/.zmax_telemetry_mode"
    except OSError:
        pass
    return "prod", "默认(未设置)"


def set_mode(mode):
    """切换档位(写运行时文件; env 锁定时由调用方拒绝)"""
    if mode not in MODE_ORDER:
        return False, "非法档位 %s" % mode
    if (os.environ.get("ZMAX_TELEMETRY") or "").strip():
        return False, "env ZMAX_TELEMETRY 已锁定, 页面不能改(改 env 或重启服务)"
    tmp = MODE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(mode + "\n")
    os.replace(tmp, MODE_FILE)
    return True, "已切到 %s (守护 2s 内跟随)" % mode


# ─────────────────────────── 纯数据(不依赖 Qt, 便于自检) ───────────────────────────
def channel_rows():
    """频道清单: 注册表 × 实测(live.json) 合并成一张表"""
    T = registry()
    live = _load(LIVE)
    lt = live.get("topics") or {}
    rows = []
    keys = list(T.TOPICS) if T else list(lt)
    for k in keys:
        reg = (T.TOPICS.get(k) if T else {}) or {}
        lv = lt.get(k) or {}
        rules = lv.get("rules") or []
        bad = [r for r in rules if not r.get("ok")]
        rows.append({
            "topic": "zmax/" + k,
            "type": (reg.get("type") or "").split("::")[-1],
            "qos": reg.get("qos"),
            "hz": lv.get("hz", -1.0), "hz_design": reg.get("rate_hz"),
            "age_s": lv.get("age_s"), "count": lv.get("count", 0),
            "matched": lv.get("matched_pubs"),
            "verdict": lv.get("verdict", "-"), "score": lv.get("score", -1.0),
            "bad": "; ".join("%s(%s)" % (r.get("rule"), r.get("msg")) for r in bad),
            "producer": (reg.get("producer") or "")[:60],
            "consumers": ", ".join(reg.get("consumers") or [])[:60],
            "fields": lv.get("fields") or {},
            "allowed": (k in T.topics_for_mode(live.get("mode") or "prod")) if T else None,
        })
    return rows


def loop_rows():
    d = _load(LOOP)
    return d.get("stages") or [], d.get("counts") or {}, d.get("stuck_at")


def alerts():
    """质量告警流: 频道规则不过 + 闭环环节 fail"""
    out = []
    for r in channel_rows():
        if r["bad"]:
            out.append((r["verdict"], r["topic"], r["bad"], r["age_s"]))
    st, _c, _s = loop_rows()
    for s in st:
        if s.get("status") == "fail":
            out.append(("fail", s.get("id", ""), s.get("evidence", "")[:110], None))
    return sorted(out, key=lambda x: {"fail": 0, "veto": 0, "warn": 1}.get(x[0], 2))


def summary_line():
    T = registry()
    live = _load(LIVE)
    mode, src = current_mode()
    n_allowed = live.get("n_topics_allowed")
    n_reg = live.get("n_topics_registered")
    alive = live.get("n_topic_alive")
    age = (time.time() - live["ts"]) if live.get("ts") else None
    st, cnt, stuck = loop_rows()
    return {
        "mode": mode, "mode_src": src, "mode_desc": (T.MODE_DESC.get(mode, "") if T else ""),
        "n_allowed": n_allowed, "n_reg": n_reg, "alive": alive,
        "live_age_s": round(age, 1) if age is not None else None,
        "loop": cnt, "stuck_at": stuck,
        "n_alerts": len(alerts()),
        "registry_v": live.get("registry_version") or (T.VERSION if T else None),
    }


def export_csv(rows=None):
    rows = rows or channel_rows()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["topic", "类型", "QoS", "实测Hz", "设计Hz", "帧龄s", "条数", "配对", "裁决", "本档允许", "问题"])
    for r in rows:
        w.writerow([r["topic"], r["type"], r["qos"], r["hz"], r["hz_design"], r["age_s"], r["count"],
                    r["matched"], r["verdict"], r["allowed"], r["bad"]])
    return buf.getvalue()


def export_json():
    return json.dumps({"ts": time.time(), "summary": summary_line(), "channels": channel_rows(),
                       "loop": loop_rows()[0], "alerts": alerts()}, ensure_ascii=False, indent=1)


# ─────────────────────────── Qt 视图(被 studio 嵌入) ───────────────────────────
def build_widget(parent=None, into_tabs=None):
    """返回本页的"头部条"(档位/刷新/导出)。

    into_tabs=None  → 自己带一个 QTabWidget(独立查看用)
    into_tabs=<QTabWidget> → 把自己的 4 个 Tab 塞进调用方那一个 Tab 栏里
                            (老倪: 一个功能一个入口, 不做第 13 个模块卡, 也不做嵌套 Tab)
    """
    from PyQt5.QtCore import Qt, QTimer
    from PyQt5.QtGui import QColor, QFont
    from PyQt5.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel,
                                 QPushButton, QTableWidget, QTableWidgetItem, QTabWidget,
                                 QTextEdit, QVBoxLayout, QWidget)

    DARK = "background:#0d1117; color:#c9d1d9;"
    OK, WARN, BAD, DIM = "#3fb950", "#d29922", "#f85149", "#8b949e"
    MONO = QFont("DejaVu Sans Mono", 9)

    class DataSpaceView(QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setStyleSheet(DARK)
            v = QVBoxLayout(self)
            v.setContentsMargins(8, 6, 8, 6)
            v.setSpacing(6)

            head = QHBoxLayout()
            self.lbl = QLabel("加载中…")
            self.lbl.setStyleSheet("font-size:12px; color:#e6edf3;")
            head.addWidget(self.lbl, 1)
            head.addWidget(QLabel("档位:"))
            self.cmb = QComboBox()
            self.cmb.addItems(MODE_ORDER)
            head.addWidget(self.cmb)
            self.btn_mode = QPushButton("切换档位")
            self.btn_ref = QPushButton("刷新")
            self.btn_csv = QPushButton("导出 CSV")
            self.btn_json = QPushButton("复制 JSON")
            for b in (self.btn_mode, self.btn_ref, self.btn_csv, self.btn_json):
                head.addWidget(b)
            v.addLayout(head)

            self.tabs = into_tabs if into_tabs is not None else QTabWidget()
            _own = into_tabs is None
            # ① 频道
            self.t_ch = QTableWidget(0, 9)
            self.t_ch.setHorizontalHeaderLabels(["话题", "类型", "实测Hz/设计", "帧龄s", "条数",
                                                 "配对", "裁决", "本档", "问题"])
            self.t_ch.setFont(MONO)
            self.t_ch.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
            self.t_ch.horizontalHeader().setSectionResizeMode(8, QHeaderView.Stretch)
            self.t_ch.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.t_ch.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.t_ch.itemSelectionChanged.connect(self._show_fields)
            self.tabs.addTab(self.t_ch, "📡 频道 (topic)")
            # ② 闭环
            self.t_lp = QTableWidget(0, 4)
            self.t_lp.setHorizontalHeaderLabels(["环节", "裁决", "门", "证据"])
            self.t_lp.setFont(MONO)
            self.t_lp.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
            self.t_lp.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.tabs.addTab(self.t_lp, "🔁 数据闭环")
            # ③ 告警
            self.t_al = QTableWidget(0, 3)
            self.t_al.setHorizontalHeaderLabels(["级别", "对象", "问题"])
            self.t_al.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
            self.t_al.setFont(MONO)
            self.t_al.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.tabs.addTab(self.t_al, "⚠ 质量告警")
            # ④ 字段真值
            self.txt = QTextEdit()
            self.txt.setReadOnly(True)
            self.txt.setFont(MONO)
            self.tabs.addTab(self.txt, "🔎 字段真值")
            if _own:
                v.addWidget(self.tabs, 1)

            self.btn_ref.clicked.connect(self.refresh)
            self.btn_mode.clicked.connect(self._do_mode)
            self.btn_csv.clicked.connect(self._csv)
            self.btn_json.clicked.connect(self._json)
            self.refresh()
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.refresh)      # 只读本地 JSON ⇒ 主线程直接刷(无网络)
            self.timer.start(2000)

        # ── 渲染 ──────────────────────────────────────────────
        def refresh(self):
            s = summary_line()
            color = {"prod": DIM, "diag": OK, "calib": WARN, "test": "#58a6ff"}.get(s["mode"], DIM)
            self.lbl.setText(
                "档位 <b style='color:%s'>%s</b>(%s) · 本档允许 <b>%s</b>/注册 %s 话题 · 活着 %s · "
                "live.json 龄 %ss · 闭环 pass %s/9(卡在 %s) · 告警 %s 条"
                % (color, s["mode"], s["mode_src"], s["n_allowed"], s["n_reg"], s["alive"],
                   s["live_age_s"], (s["loop"] or {}).get("pass", "?"), s["stuck_at"], s["n_alerts"]))
            self.lbl.setTextFormat(Qt.RichText)
            self.cmb.setCurrentText(s["mode"] if s["mode"] in MODE_ORDER else "prod")

            rows = channel_rows()
            self.t_ch.setRowCount(len(rows))
            for i, r in enumerate(rows):
                vcol = {"ok": OK, "warn": WARN, "veto": BAD, "-": DIM}.get(r["verdict"], DIM)
                cells = [r["topic"], r["type"],
                         "%.2f / %s" % (r["hz"], r["hz_design"]),
                         "%.1f" % r["age_s"] if r["age_s"] is not None else "—",
                         str(r["count"]), str(r["matched"]), r["verdict"],
                         "✓" if r["allowed"] else "✗", r["bad"]]
                for c, t in enumerate(cells):
                    it = QTableWidgetItem(t)
                    if c == 6:
                        it.setForeground(QColor(vcol))
                    elif c == 3 and r["age_s"] is not None and r["age_s"] > 5:
                        it.setForeground(QColor(WARN))
                    self.t_ch.setItem(i, c, it)

            stages, cnt, stuck = loop_rows()
            self.t_lp.setRowCount(len(stages))
            for i, st in enumerate(stages):
                icon = {"pass": "✅ 过", "fail": "❌ 未过", "unknown": "❔ 缺证据"}.get(st.get("status"), "?")
                for c, t in enumerate([ "%s %s" % (st.get("id"), st.get("name")), icon,
                                       st.get("gate", "")[:70], st.get("evidence", "")]):
                    self.t_lp.setItem(i, c, QTableWidgetItem(t))
            al = alerts()
            self.t_al.setRowCount(len(al))
            for i, (lv, obj, msg, _a) in enumerate(al):
                for c, t in enumerate([lv, obj, msg]):
                    self.t_al.setItem(i, c, QTableWidgetItem(t))

        def _show_fields(self):
            r = self.t_ch.currentRow()
            rows = channel_rows()
            if r < 0 or r >= len(rows):
                return
            x = rows[r]
            self.txt.setPlainText(json.dumps({
                "话题": x["topic"], "类型": x["type"], "QoS": x["qos"],
                "实测Hz": x["hz"], "设计Hz": x["hz_design"], "帧龄s": x["age_s"],
                "发布者": x["producer"], "消费者": x["consumers"],
                "最新字段真值": x["fields"],
                "质量问题": x["bad"] or "无",
            }, ensure_ascii=False, indent=1))

        def _do_mode(self):
            ok, msg = set_mode(self.cmb.currentText())
            self.lbl.setToolTip(msg)
            self.refresh()

        def _csv(self):
            from PyQt5.QtWidgets import QApplication
            QApplication.clipboard().setText(export_csv())
            self.lbl.setToolTip("CSV 已复制到剪贴板(%d 行)" % len(channel_rows()))

        def _json(self):
            from PyQt5.QtWidgets import QApplication
            QApplication.clipboard().setText(export_json())
            self.lbl.setToolTip("JSON 已复制到剪贴板")

    w = DataSpaceView(parent)
    return w


if __name__ == "__main__":          # 自检/独立查看: QT_QPA_PLATFORM=offscreen python dds_space.py --dump
    import sys
    if "--dump" in sys.argv:
        print(json.dumps({"summary": summary_line(), "channels": channel_rows()},
                         ensure_ascii=False, indent=1)[:2600])
    else:
        from PyQt5.QtWidgets import QApplication
        app = QApplication(sys.argv)
        w = build_widget()
        w.resize(1180, 620)
        w.show()
        sys.exit(app.exec_())
