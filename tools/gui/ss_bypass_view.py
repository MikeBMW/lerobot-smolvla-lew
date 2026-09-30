#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ss_bypass_view.py — 📈 旁路实时可视化窗 (状态空间可视化层观察器)

老倪 2026-09-16: 「旁路接到控制台做实时可视化 (当前阶段/残差/接触概率曲线)」

数据源: 旁路运行器心跳 + 逐帧记录 (tools/ss_bypass_run.py → ~/zmax_data/ss_bypass/)
        与 真机感知最新帧 (ss_remote_tap → ~/zmax_ss_remote/)
显示:   ① 数值面板: 当前阶段(13 段状态机) · 残差 · 接触概率 · 旁路步数/采样 · 六层调用数
                    · 零下行自证 (rclpy/publishers/sockets/writes_to_orin) · 缺口计数 · 数据源新鲜度
        ② 两条实时曲线: 残差 (米) 与 接触概率 (0~1), 取最近 N 帧逐帧记录
刷新:   500 ms (QTimer), 数据不新鲜 → 明确显示 "数据流过期 xx s" (不用旧帧冒充实时)
"""
import os
import sys
import time

from PyQt5 import QtCore, QtGui, QtWidgets

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _load_src():
    """旁路数据源模块 (框架层 src/lerobot/datasets/bypass_sensor_source.py)"""
    import importlib.util
    root = os.environ.get("ZMAX_REPO_ROOT") or os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    path = os.path.join(root, "src", "lerobot", "datasets", "bypass_sensor_source.py")
    if not os.path.exists(path):
        for up in range(6):
            cand = os.path.join(os.path.dirname(os.path.abspath(__file__)), *([".."] * up),
                                "src", "lerobot", "datasets", "bypass_sensor_source.py")
            cand = os.path.normpath(cand)
            if os.path.exists(cand):
                path = cand
                break
    spec = importlib.util.spec_from_file_location("bypass_sensor_source", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


BG = "#0d1117"
PANEL = "#161b22"
FG = "#e6edf3"
DIM = "#8b949e"
C_RES = "#ffa657"      # 残差 = 橙
C_CON = "#58a6ff"      # 接触概率 = 蓝
C_OK = "#3fb950"
C_BAD = "#f85149"

# ── 波形通道定义 (每通道一条独立泳道; min_span = 静止时的最小量程, 防噪声被放大成假波动) ──
BANDS_SS = [
    {"key": "residual", "title": "残差", "unit": "m", "color": C_RES,
     "fmt": (lambda v: f"{v:.4f}"), "min_span": 0.002},
    {"key": "contact_p", "title": "接触概率", "unit": "", "color": C_CON,
     "fmt": (lambda v: f"{v:.3f}"), "fixed": "01"},
    {"key": "dx_real", "title": "真机位移速率", "unit": "m/s", "color": C_OK,
     "fmt": (lambda v: f"{v:.4f}"), "min_span": 0.01},
]
BANDS_REAL = [
    {"key": "tcp_x", "title": "TCP X", "unit": "m", "color": "#ffa657",
     "fmt": (lambda v: f"{v:+.4f}"), "min_span": 1e-4},
    {"key": "tcp_y", "title": "TCP Y", "unit": "m", "color": "#3fb950",
     "fmt": (lambda v: f"{v:+.4f}"), "min_span": 1e-4},
    {"key": "tcp_z", "title": "TCP Z", "unit": "m", "color": "#58a6ff",
     "fmt": (lambda v: f"{v:+.4f}"), "min_span": 1e-4},
    {"key": "force_mag", "title": "插入力 |F|", "unit": "N", "color": "#f778ba",
     "fmt": (lambda v: f"{v:.2f}"), "min_span": 0.1},
    {"key": "force_fz", "title": "轴向力 Fz", "unit": "N", "color": "#d29922",
     "fmt": (lambda v: f"{v:+.2f}"), "min_span": 0.1},
]
SS = (f"QWidget {{ background:{BG}; color:{FG}; font-family:'Noto Sans CJK SC','Microsoft YaHei',sans-serif; }}"
      f"QLabel {{ color:{FG}; font-size:15px; }}"
      f"QGroupBox {{ border:1px solid #30363d; border-radius:6px; margin-top:14px; padding:10px; }}"
      f"QGroupBox {{ color:{DIM}; font-size:14px; }}"
      f"QGroupBox::title {{ subcontrol-origin: margin; left:12px; padding:0 4px; color:{DIM}; font-size:14px; }}")


class CurveWidget(QtWidgets.QWidget):
    """多泳道实时波形 — 纯 QPainter, 无 GL/第三方依赖

    排版铁律 (老倪 2026-09-18「波形名称和描述的字体有重叠 / 字太小」):
      · 每个通道一条**独立泳道**: 左侧栏放「通道名 + 当前值」, 右侧栏放该泳道量程上下限,
        绘图区只画曲线 —— 文字三处物理分离, 结构上不可能重叠 (旧版名与量程都挤在同一 x 位置)。
      · 字号显式指定 (通道名 13px 粗 / 当前值 17px / 刻度 12px), 不受系统默认小字影响。
    """

    FAM = "Noto Sans CJK SC"

    def __init__(self, bands, title="", parent=None):
        super().__init__(parent)
        self.bands = bands            # [{"key","title","unit","color","fmt","min_span","fixed"}]
        self.title = title
        self.data = {b["key"]: [] for b in bands}
        self.setMinimumHeight(30 + 112 * max(1, len(bands)))
        f = self.font()
        f.setFamily(self.FAM)
        f.setPointSizeF(11.0)
        self.setFont(f)

    def set_series(self, key, pts):
        if key in self.data:
            self.data[key] = list(pts or [])
            self.update()

    def _fonts(self):
        fam = self.font().family() or self.FAM
        return (QtGui.QFont(fam, 12, QtGui.QFont.Bold),      # 通道名
                QtGui.QFont(fam, 16, QtGui.QFont.DemiBold),  # 当前值
                QtGui.QFont(fam, 11),                        # 量程刻度 / 脚注
                QtGui.QFont(fam, 14, QtGui.QFont.DemiBold))  # 组件标题

    def layout(self):
        """绘制几何 — paintEvent 与自检**共用同一套矩形** (自检断言的就是真实绘制位置)"""
        f_t, f_v, f_a, _fh = self._fonts()
        fm_t, fm_v, fm_a = QtGui.QFontMetrics(f_t), QtGui.QFontMetrics(f_v), QtGui.QFontMetrics(f_a)
        W, H = self.width(), self.height()
        n = max(1, len(self.bands))
        head = 30 if self.title else 6
        foot, gap = 24, 10
        band_h = max(fm_t.height() + fm_v.height() + 16, (H - head - foot - gap * (n - 1)) // n)
        gutter = max(fm_t.horizontalAdvance(b["title"]) for b in self.bands) + 20
        right_w = max(fm_a.horizontalAdvance("-0.0000"), fm_a.horizontalAdvance("-100.0")) + 16
        x0, x1 = gutter, max(gutter + 60, W - right_w - 8)
        info = {"x0": x0, "x1": x1, "band_h": band_h, "head": head, "gap": gap, "gutter": gutter,
                "right_w": right_w, "fm_t": fm_t, "fm_v": fm_v, "fm_a": fm_a, "bands": []}
        for i, b in enumerate(self.bands):
            y0 = head + i * (band_h + gap)
            tb = y0 + fm_t.ascent() + 4                        # 通道名基线
            vb = tb + fm_t.descent() + 6 + fm_v.ascent()       # 当前值基线 (在通道名下方)
            info["bands"].append({
                "y0": y0, "title_baseline": tb, "value_baseline": vb,
                "title_rect": QtCore.QRect(6, tb - fm_t.ascent(),
                                           fm_t.horizontalAdvance(b["title"]), fm_t.height()),
                "value_rect": QtCore.QRect(6, vb - fm_v.ascent(), 0, fm_v.height()),
                "hi_rect": QtCore.QRect(x1 + 5, y0 + 2, right_w - 8, fm_a.height()),
                "lo_rect": QtCore.QRect(x1 + 5, y0 + band_h - fm_a.height() - 2,
                                        right_w - 8, fm_a.height()),
            })
        return info

    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QtGui.QColor(PANEL))
        f_t, f_v, f_a, f_h = self._fonts()
        g = self.layout()
        x0, x1, band_h = g["x0"], g["x1"], g["band_h"]
        W, H = self.width(), self.height()

        if self.title:
            p.setFont(f_h)
            p.setPen(QtGui.QPen(QtGui.QColor(FG), 1))
            p.drawText(8, 21, self.title)

        npts_max = 0
        for i, b in enumerate(self.bands):
            gi = g["bands"][i]
            y0 = gi["y0"]
            series = self.data.get(b["key"]) or []
            npts_max = max(npts_max, len(series))
            vals = [v for _, v in series]
            fmt = b.get("fmt") or (lambda v: f"{v:.4f}")
            if b.get("fixed") == "01":
                lo, hi = 0.0, 1.0
            elif vals:
                vmin, vmax = min(vals), max(vals)
                span = max(vmax - vmin, float(b.get("min_span", 0.0)) or 1e-9)
                pad = span * 0.15
                lo, hi = vmin - pad, vmax + pad
            else:
                lo, hi = 0.0, 1.0

            # 网格 + 边框 (绘图区)
            p.setPen(QtGui.QPen(QtGui.QColor("#21262d"), 1))
            for k in range(3):
                p.drawLine(x0, y0 + int(band_h * k / 2), x1, y0 + int(band_h * k / 2))
            p.setPen(QtGui.QPen(QtGui.QColor("#30363d"), 1))
            p.drawRect(x0, y0, x1 - x0, band_h)

            # 左栏: 通道名 (上) + 当前值 (下) — 两行分层, 基线由 layout() 保证不叠
            p.setFont(f_t)
            p.setPen(QtGui.QPen(QtGui.QColor(DIM), 1))
            p.drawText(6, gi["title_baseline"], b["title"])
            p.setFont(f_v)
            p.setPen(QtGui.QPen(QtGui.QColor(b["color"]), 1))
            p.drawText(6, gi["value_baseline"], (fmt(vals[-1]) if vals else "—")
                       + ((" " + b["unit"]) if b.get("unit") else ""))

            # 右栏: 量程上限 (顶) / 下限 (底) — 与左栏 x 区间完全分离
            p.setFont(f_a)
            p.setPen(QtGui.QPen(QtGui.QColor(DIM), 1))
            p.drawText(gi["hi_rect"], QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter, fmt(hi))
            p.drawText(gi["lo_rect"], QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter, fmt(lo))

            if len(series) < 2:
                p.setPen(QtGui.QPen(QtGui.QColor(DIM), 1))
                p.drawText(x0 + 14, y0 + band_h // 2 + 5, b.get("empty") or "等待数据…")
                continue
            m = len(series)
            span_v = max(1e-12, hi - lo)
            pts = []
            for j, (_, v) in enumerate(series):
                xx = x0 + 2 + int((x1 - x0 - 4) * j / (m - 1))
                yy = y0 + band_h - 3 - int((band_h - 6) * (max(lo, min(hi, v)) - lo) / span_v)
                pts.append(QtCore.QPoint(xx, yy))
            p.setPen(QtGui.QPen(QtGui.QColor(b["color"]), 2))
            p.drawPolyline(QtGui.QPolygon(pts))
            p.setBrush(QtGui.QBrush(QtGui.QColor(b["color"])))
            p.setPen(QtCore.Qt.NoPen)
            p.drawEllipse(pts[-1], 3, 3)

        p.setFont(f_a)
        p.setPen(QtGui.QPen(QtGui.QColor(DIM), 1))
        p.drawText(8, H - 7, f"横轴 = 最近 {npts_max} 帧 (等距 · 10Hz 采集 ≈ {npts_max / 10.0:.0f}s) ·"
                             f" 纵轴各自自适应量程 · 缺通道显示等待, 不填假值")


class SSBypassView(QtWidgets.QWidget):
    """旁路实时可视化窗口 (非模态, 可常开)"""

    def __init__(self, module=None):
        super().__init__(None, QtCore.Qt.Window)
        self.module = module
        self.setWindowTitle("📈 旁路实时可视化 — 状态空间 (当前阶段 / 残差 / 接触概率 / 真机位姿 XYZ / 插入力)")
        self.resize(1660, 1060)
        self.setStyleSheet(SS)
        self.src = _load_src()
        self._build()
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(500)
        self.refresh()

    def _row(self, k):
        lab = QtWidgets.QLabel("-")
        lab.setStyleSheet(f"color:{FG};font-size:19px;")
        kk = QtWidgets.QLabel(k)
        kk.setStyleSheet(f"color:{DIM};font-size:14px;")
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        v.setContentsMargins(2, 2, 2, 2)
        v.setSpacing(2)
        v.addWidget(kk)
        v.addWidget(lab)
        return w, lab

    def _build(self):
        root = QtWidgets.QVBoxLayout(self)
        head = QtWidgets.QLabel("🔭 可视化层 · 旁路观察器 (回路外, 不参与控制) — 数据源: 旁路真机传感器 (Orin 远程只读)")
        head.setStyleSheet(f"color:{DIM};font-size:15px;")
        root.addWidget(head)

        gb = QtWidgets.QGroupBox("旁路运行状态 (六层真源码逐帧)")
        g = QtWidgets.QGridLayout(gb)
        self.lab_stage, self.lab_res, self.lab_con = None, None, None
        keys = [("当前阶段 (13 段)", "stage"), ("残差 (m)", "residual"), ("接触概率", "contact_p"),
                ("旁路步 / 采样", "steps"), ("六层调用", "layers"), ("零下行自证", "zero"),
                ("缺口 (逐帧计数)", "gaps"), ("数据源新鲜度", "fresh")]
        self.labs = {}
        for i, (title, key) in enumerate(keys):
            w, lab = self._row(title)
            self.labs[key] = lab
            g.addWidget(w, i // 4, i % 4)
        root.addWidget(gb)

        gb2 = QtWidgets.QGroupBox("真机感知最新帧 (旁路数据源)")
        g2 = QtWidgets.QGridLayout(gb2)
        for i, (title, key) in enumerate([("TCP 位置 (m)", "tcp"), ("关节速度范数", "vnorm"),
                                          ("夹爪开度", "grip"), ("六维力", "ft"),
                                          ("场景几何 z7", "z7"), ("产线阶段", "prod")]):
            w, lab = self._row(title)
            self.labs["src_" + key] = lab
            g2.addWidget(w, i // 3, i % 3)
        root.addWidget(gb2)

        gbp = QtWidgets.QGroupBox("真机位姿 (实时 · 远程只读 Orin)")
        gp = QtWidgets.QGridLayout(gbp)
        for i, (t_, k, h_) in enumerate([("TCP X / Y / Z", "pose_xyz", "m · base_link 末端位置"),
                                         ("姿态四元数", "pose_quat", "x,y,z,w · 末端朝向"),
                                         ("六关节位置", "pose_q", "rad · q1..q6"),
                                         ("六关节速度", "pose_dq", "rad/s · 全 0 = 机器静止"),
                                         ("位置变化率", "pose_dx", "m/s · 由真实帧差分 (产线在动)"),
                                         ("机器人状态", "pose_rs", "电源 / 运行 / 报警 / 急停 / 碰撞"),
                                         ("插入力 |F|", "pose_fmag", "N · 合力 = √(Fx²+Fy²+Fz²) · 真实力信号"),
                                         ("轴向插入力 Fz", "pose_fz", "N · 工具轴接触反馈力 (插装判据)"),
                                         ("六维力 Fx,Fy,Fz", "pose_f3", "N · 腕部力觉三分量 · 50Hz")]):
            w, lab = self._row(t_)
            self.labs["p_" + k] = lab
            gp.addWidget(w, i // 5, i % 5)          # 5 列 → 9 格只占 2 行 (窗口别太高)
        root.addWidget(gbp)

        gbimg = QtWidgets.QGroupBox("实时图像 (RealSense 彩色优先 / FoundationPose 调试帧兜底)")
        gi = QtWidgets.QHBoxLayout(gbimg)
        self.img_view = QtWidgets.QLabel("(无图像)")
        self.img_view.setFixedSize(260, 195)
        self.img_view.setStyleSheet("background:#161b22; color:#8b949e; border:1px solid #30363d;")
        self.img_view.setAlignment(QtCore.Qt.AlignCenter)
        self.img_meta = QtWidgets.QLabel("-")
        self.img_meta.setStyleSheet(f"color:{FG};font-size:12px;")
        self.img_meta.setWordWrap(True)
        gi.addWidget(self.img_view)
        gi.addWidget(self.img_meta, 1)
        root.addWidget(gbimg)

        self.curve = CurveWidget(BANDS_SS, title="状态空间通道 (旁路六层真源码逐帧)")
        self.curve_real = CurveWidget(BANDS_REAL, title="真机通道 (Orin 远程只读 · 位姿 50Hz/落盘 10Hz · 力 49.5Hz)")
        box = QtWidgets.QHBoxLayout()
        box.setSpacing(12)
        box.addWidget(self.curve, 1)
        box.addWidget(self.curve_real, 1)
        root.addLayout(box, 1)
        self.lab_foot = QtWidgets.QLabel("")
        self.lab_foot.setStyleSheet(f"color:{DIM};font-size:14px;")
        self.lab_foot.setWordWrap(True)
        root.addWidget(self.lab_foot)

    def _feed_curves(self):
        """把最近一段真实逐帧记录喂给两条波形 (旁路通道 + 真机位姿/插入力); 缺的通道留空, 不填假值"""
        rows = self.src.tail_bypass(240)
        self.curve.set_series("residual", [(float(r.get("t", 0)), float(r.get("residual", 0) or 0))
                                           for r in rows])
        self.curve.set_series("contact_p", [(float(r.get("t", 0)), float(r.get("contact_p", 0) or 0))
                                            for r in rows])
        self.curve.set_series("dx_real", [(float(r.get("t", 0)), float(r.get("dx_real", 0) or 0))
                                          for r in rows])
        xs, ys, zs, mag, fz = [], [], [], [], []
        for r in (self.src.tail_state(240) or []):
            t = float(r.get("t", 0) or 0)
            q = r.get("tcp") or []
            if len(q) >= 3:
                xs.append((t, float(q[0])))
                ys.append((t, float(q[1])))
                zs.append((t, float(q[2])))
            w = r.get("ft") or []
            if len(w) >= 3:
                fx, fy, fzz = float(w[0]), float(w[1]), float(w[2])
                mag.append((t, (fx * fx + fy * fy + fzz * fzz) ** 0.5))
                fz.append((t, fzz))
        self.curve_real.set_series("tcp_x", xs)
        self.curve_real.set_series("tcp_y", ys)
        self.curve_real.set_series("tcp_z", zs)
        self.curve_real.set_series("force_mag", mag)
        self.curve_real.set_series("force_fz", fz)

    def refresh(self):
        try:
            s = self.src.read_bypass_status()
            last = (s.get("last") or {}) if s.get("ok") else {}
            self.labs["stage"].setText(str(last.get("stage", "-")))
            self.labs["residual"].setText(f"{last.get('residual', '-')}")
            self.labs["contact_p"].setText(f"{last.get('contact_p', '-')}")
            self.labs["steps"].setText(f"{s.get('steps', '-')} / {s.get('samples', '-')}")
            lc = s.get("layer_calls") or {}
            self.labs["layers"].setText(" · ".join(f"{k[:4]}={v}" for k, v in lc.items()) or "-")
            zd = s.get("zero_downlink") or {}
            zt = ("✅ 无 rclpy/无 socket/零写回" if zd and not zd.get("rclpy_imported")
                  else f"⚠️ {zd}")
            self.labs["zero"].setText(zt)
            self.labs["zero"].setStyleSheet(f"color:{C_OK if '✅' in zt else C_BAD};font-size:14px;")
            gaps = s.get("gap") or {}
            self.labs["gaps"].setText(" · ".join(f"{k.split('(')[0]}×{v}" for k, v in gaps.items()) or "无")
            age = s.get("age_s")
            fresh = s.get("fresh")
            self.labs["fresh"].setText(("✅ " if fresh else "⚠️ 过期 ") + f"{age}s" if age is not None else "-")
            self.labs["fresh"].setStyleSheet(f"color:{C_OK if fresh else C_BAD};font-size:14px;")

            p = self.src.read_latest()
            self.labs["src_tcp"].setText(str([round(x, 4) for x in p["tcp"]]) if p.get("tcp") else "-")
            jv = p.get("jvel")
            self.labs["src_vnorm"].setText(f"{sum(v * v for v in jv) ** 0.5:.4f}" if jv else "缺")
            self.labs["src_grip"].setText(str(p.get("gripper")) if p.get("gripper") is not None else "缺(无发布者)")
            self.labs["src_ft"].setText(str(p.get("ft")) if p.get("ft") is not None else "缺(无发布者)")
            ft6 = p.get("ft") or []
            _fm = (sum(v * v for v in ft6[:3]) ** 0.5) if len(ft6) >= 3 else None
            self.labs["p_pose_fmag"].setText(f"{_fm:.2f} N" if _fm is not None else "缺")
            self.labs["p_pose_fmag"].setStyleSheet(
                f"color:{'#f778ba' if _fm is not None else C_BAD};font-size:19px;")
            self.labs["p_pose_fz"].setText(f"{ft6[2]:+.2f} N" if len(ft6) >= 3 else "缺")
            self.labs["p_pose_f3"].setText(", ".join(f"{v:+.2f}" for v in ft6[:3]) if len(ft6) >= 3 else "缺")
            self.labs["src_z7"].setText("未示教 (拒算)" if p.get("z7") is None else str(p["z7"]))
            self.labs["src_prod"].setText(p.get("stage_prod") or "空闲")

            # 真机位姿 (TCP + 四元数 + 六关节 + 机器人状态)
            tcp = p.get("tcp") or []
            self.labs["p_pose_xyz"].setText(", ".join(f"{v:+.4f}" for v in tcp) + f"  ({p.get('tcp_frame')})" if tcp else "-")
            q = p.get("tcp_quat") or []
            self.labs["p_pose_quat"].setText(", ".join(f"{v:+.3f}" for v in q) if q else "缺")
            jp = p.get("jpos") or []
            jv = p.get("jvel") or []
            self.labs["p_pose_q"].setText(" ".join(f"{v:+.3f}" for v in jp) if jp else "缺")
            self.labs["p_pose_dq"].setText(" ".join(f"{v:+.3f}" for v in jv) if jv else "缺")
            moving = bool(jv) and max(abs(v) for v in jv) > 1e-4
            self.labs["p_pose_dq"].setStyleSheet(f"color:{C_OK if moving else DIM};font-size:19px;")
            dxr = (last.get("dx_real") if last else None)
            self.labs["p_pose_dx"].setText(f"{dxr:.4f}" if isinstance(dxr, (int, float)) else "-")
            self.labs["p_pose_dx"].setStyleSheet(
                f"color:{C_OK if isinstance(dxr, (int, float)) and dxr > 0.002 else DIM};font-size:19px;")
            import json as _json
            import re as _re
            _rsraw = p.get("robot_status") or ""
            try:
                rs = _json.loads(_rsraw)
            except Exception:                      # 截断/非完整 JSON → 正则兜底 (如实取值, 不猜)
                rs = {}
                for _k in ("power_state", "operation_state", "error_reason"):
                    _m = _re.search(r'"%s"\s*:\s*"([^"]*)"' % _k, _rsraw)
                    if _m:
                        rs[_k] = _m.group(1)
                for _k in ("has_error", "estop_detected", "collision_detected"):
                    rs[_k] = ('"%s": true' % _k) in _rsraw.replace(" ", "")
            if rs:
                st_txt = (f"{rs.get('power_state', '?')} / {rs.get('operation_state', '?')} / "
                          + ("报警 " + str(rs.get("error_reason", "")) if rs.get("has_error")
                             else ("急停" if rs.get("estop_detected") else
                                   ("碰撞" if rs.get("collision_detected") else "正常"))))
            else:
                st_txt = "缺 (无 /robot_status)"
            self.labs["p_pose_rs"].setText(st_txt)

            # 实时图像 (多话题状态如实显示) —— L2 YOLO 标注图优先 (旁路可视化唯一出口)
            import json as _json2
            _ydp = os.path.join(os.path.expanduser("~/zmax_data/ss_bypass"), "yolo_detections.json")
            _yimg = os.path.join(os.path.expanduser("~/zmax_data/ss_bypass"), "yolo_annotated.png")
            try:
                _yd = _json2.load(open(_ydp)) if os.path.exists(_ydp) else None
            except Exception:
                _yd = None
            if _yd and os.path.exists(_yimg) and (time.time() - os.path.getmtime(_yimg)) <= 6.0:
                _pm = QtGui.QPixmap(_yimg)
                if not _pm.isNull():
                    self.img_view.setPixmap(_pm.scaled(self.img_view.size(), QtCore.Qt.KeepAspectRatio,
                                                       QtCore.Qt.SmoothTransformation))
                _peg = _yd.get("peg_optical_module")
                _dt = " · ".join(f"{d['cls']}={d['conf']}" for d in (_yd.get("detections") or [])[:4]) or "无检出"
                self.img_meta.setText(
                    f"🎯 L2 YOLO 旁路检测 (输出=可视化, 零下行)\n源图: {_yd.get('image')} "
                    f"[{_yd.get('source_kind')}] {_yd.get('size')} · age={_yd.get('frame_age_s')}s\n"
                    f"检出: {_dt}\n" +
                    (f"✅ 光模块(peg) conf={_peg['conf']} box={_peg['xyxy']}" if _peg else "⚠️ 未检出光模块(peg)"))
                self._feed_curves()
                self.lab_foot.setText(f"旁路可视化: 真机位姿 + L2 YOLO 标注图 (唯一输出, 无任何下行) · "
                                      f"权重 {os.path.basename(str(_yd.get('weights', '')))} · imgsz={_yd.get('imgsz')} "
                                      f"conf_th={_yd.get('conf_th')}")
                return
            byt = p.get("images_by_topic") or {}
            pick, pick_t = None, None
            for t, v in byt.items():                     # RealSense 优先 (只认新鲜帧 ≤5s)
                if v.get("png") and "realsense" in t and (v.get("age") or 99) <= 5.0:
                    pick, pick_t = v, t
            if pick is None:
                for t, v in byt.items():
                    if v.get("png") and (v.get("age") or 99) <= 5.0:
                        pick, pick_t = v, t
            if pick and os.path.exists(pick["png"]):
                pm = QtGui.QPixmap(pick["png"])
                if not pm.isNull():
                    self.img_view.setPixmap(pm.scaled(self.img_view.size(), QtCore.Qt.KeepAspectRatio,
                                                      QtCore.Qt.SmoothTransformation))
                self.img_meta.setText(
                    f"显示: {pick_t}\n{('RealSense 彩色' if 'realsense' in str(pick_t) else 'FoundationPose 调试帧')} "
                    f"{pick.get('w')}×{pick.get('h')} {pick.get('encoding')} · 对比度 std={pick.get('std')} "
                    f"(>5 判真图)\n新鲜度: {pick.get('age')}s\n各话题: " +
                    " / ".join(f"{t.split('/')[-1]}={'有帧' if v.get('png') else '无帧'}" for t, v in byt.items()))
            else:
                _pubs = (p.get("pubs") or {})
                _rs = _pubs.get("/realsense/color/image_raw")
                _fp = _pubs.get("/foundationpose/tray_reference/debug_image")
                if _rs and _rs > 0:
                    self.img_view.setText("(RealSense 在线, 等待帧)")
                elif _fp:
                    self.img_view.setText("(FoundationPose 在线, 当前无帧)")
                else:
                    self.img_view.setText("(无图像发布者)")
                self.img_meta.setText(
                    f"当前无图像帧 — 发布者计数: RealSense 彩色={_rs} (D405 已接, Orin 未装 realsense2_camera), "
                    f"FoundationPose 调试帧={_fp} (vision_tag, 产线视觉空闲时不发帧)\n"
                    f"触觉 interfaces/msg/TactileSensor = 自定义消息, 容器无类型定义 → 暂不可订\n"
                    f"💡 现场一旦有帧 (驱动起来/产线跑) 这里会立即显示真图, 不会用旧帧或占位图冒充")

            self._feed_curves()
            self.lab_foot.setText(f"数据源: {p.get('file')} · 旁路记录 {os.path.basename(str(s.get('bypass_file', self.src.probe().get('bypass_file'))))}"
                                  f" · 刷新 500ms · 缺口/未示教项按缺报缺 (不填假值)")
        except Exception as e:
            self.lab_foot.setText(f"⚠️ 刷新异常: {type(e).__name__}: {e}")


class Z700SignalsView(QtWidgets.QWidget):
    """🖥 Z700 真机信号面板 (可视化层观察器, 输入=物理世界输出)

    显示**全部真机信号** (Orin 生产机器人 XMS5-R800 · 4060 远程只读):
      TCP 位姿(位置+四元数+坐标系) · 六关节位置/速度 · 六维力/力矩 · 夹爪开度 · 触觉 4D
      · 机器人状态(电源/运行/错误/急停/碰撞) · 产线阶段 · 采样率与新鲜度 · 缺通道清单
    另附状态空间旁路当前值 (阶段/残差/接触概率) — 物理世界输出 → 状态校正闭环的即时观测量。
    数据不新鲜 → 显示过期秒数; 通道缺失 → 显式"缺(无发布者)", 不用 0 冒充。
    """

    def __init__(self, module=None):
        super().__init__(None, QtCore.Qt.Window)
        self.module = module
        self.setWindowTitle("🖥 Z700 真机信号 — 全信号观测 (物理世界输出)")
        self.resize(1040, 620)
        self.setStyleSheet(SS)
        self.src = _load_src()
        self._build()
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(500)
        self.refresh()

    def _cell(self, title, hint=""):
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        v.setContentsMargins(4, 3, 4, 3)
        v.setSpacing(1)
        t = QtWidgets.QLabel(title)
        t.setStyleSheet(f"color:{DIM};font-size:11px;")
        val = QtWidgets.QLabel("-")
        val.setStyleSheet(f"color:{FG};font-size:14px;")
        v.addWidget(t)
        v.addWidget(val)
        if hint:
            h = QtWidgets.QLabel(hint)
            h.setStyleSheet(f"color:{DIM};font-size:10px;")
            v.addWidget(h)
        return w, val

    def _build(self):
        root = QtWidgets.QVBoxLayout(self)
        head = QtWidgets.QLabel("🖥 Z700 真机信号 — 来源: 🌍 物理世界 输出 / 旁路真机传感器 (Orin 192.168.23.66 远程只读, 不接管)")
        head.setStyleSheet(f"color:{DIM};font-size:12px;")
        root.addWidget(head)
        self.labs = {}

        gb1 = QtWidgets.QGroupBox("真机 TCP 位姿 (base_link)")
        g1 = QtWidgets.QGridLayout(gb1)
        for i, (t_, k, h) in enumerate([("TCP X", "x", "m · 末端横向"), ("TCP Y", "y", "m · 末端纵向"),
                                        ("TCP Z", "z", "m · 末端高度"), ("姿态四元数", "quat", "x,y,z,w · 末端朝向"),
                                        ("位置变化率", "dx", "m/s · 由连续帧差分 (真机运动)"),
                                        ("坐标系", "frame", "TCP 位姿参考系")]):
            w, lab = self._cell(t_, h)
            self.labs["tcp_" + k] = lab
            g1.addWidget(w, i // 3, i % 3)
        root.addWidget(gb1)

        gb2 = QtWidgets.QGroupBox("六关节 (珞石 XMS5-R800 · /real_joint_states)")
        g2 = QtWidgets.QGridLayout(gb2)
        for i in range(6):
            w, lab = self._cell(f"关节 {i+1} 位置", "rad · 位置反馈")
            self.labs[f"q{i}"] = lab
            g2.addWidget(w, 0, i)
            w2, lab2 = self._cell(f"关节 {i+1} 速度", "rad/s · 速度反馈")
            self.labs[f"dq{i}"] = lab2
            g2.addWidget(w2, 1, i)
        root.addWidget(gb2)

        gb3 = QtWidgets.QGroupBox("力觉 / 夹爪 / 触觉 / 机器人状态")
        g3 = QtWidgets.QGridLayout(gb3)
        for i, (t_, k, h) in enumerate([("六维力 Fx,Fy,Fz", "force", "N · 腕部力觉"),
                                        ("力矩 Tx,Ty,Tz", "torque", "N·m · 腕部力矩"),
                                        ("夹爪开度", "grip", "0~1000 · 传感器反馈"),
                                        ("触觉 4D", "tactile", "grasp/contact/dirx/diry"),
                                        ("电源状态", "power", "真机 /robot_status"),
                                        ("运行状态", "op", "idle/moving · 产线是否在动"),
                                        ("报警 / 急停 / 碰撞", "err", "has_error / estop / collision"),
                                        ("侧频 / 新鲜度", "rate", "Hz · 我方采集 10Hz 落盘")]):
            w, lab = self._cell(t_, h)
            self.labs["s_" + k] = lab
            g3.addWidget(w, i // 4, i % 4)
        root.addWidget(gb3)

        gbi = QtWidgets.QGroupBox("真机图像 (现场唯一有发布者的图像话题)")
        gi = QtWidgets.QHBoxLayout(gbi)
        self.img_view = QtWidgets.QLabel("(无图像)")
        self.img_view.setFixedSize(240, 180)
        self.img_view.setStyleSheet("background:#161b22; color:#8b949e; border:1px solid #30363d;")
        self.img_view.setAlignment(QtCore.Qt.AlignCenter)
        self.img_meta = QtWidgets.QLabel("-")
        self.img_meta.setStyleSheet(f"color:{FG};font-size:12px;")
        self.img_meta.setWordWrap(True)
        gi.addWidget(self.img_view)
        gi.addWidget(self.img_meta, 1)
        root.addWidget(gbi)

        gb4 = QtWidgets.QGroupBox("状态空间旁路 (物理世界输出 → 状态校正闭环)")
        g4 = QtWidgets.QGridLayout(gb4)
        for i, (t_, k, h) in enumerate([("当前阶段", "stage", "13 段状态机 · 旁路判定"),
                                        ("残差", "res", "m · 测量 vs 先验 (状态校正器)"),
                                        ("接触概率", "con", "σ(残差) · 接触判据"),
                                        ("旁路步 / 采样", "steps", "逐帧六层真源码"),
                                        ("零下行自证", "zero", "无 rclpy/socket/写回"),
                                        ("缺口", "gaps2", "缺通道与未示教项")]):
            w, lab = self._cell(t_, h)
            self.labs["b_" + k] = lab
            g4.addWidget(w, i // 3, i % 3)
        root.addWidget(gb4)
        self.lab_foot = QtWidgets.QLabel("")
        self.lab_foot.setStyleSheet(f"color:{DIM};font-size:11px;")
        root.addWidget(self.lab_foot)

    def refresh(self):
        try:
            p = self.src.read_latest()
            tcp = p.get("tcp")
            for k, i in (("x", 0), ("y", 1), ("z", 2)):
                self.labs["tcp_" + k].setText(f"{tcp[i]:+.4f}" if tcp else "-")
            q = p.get("tcp_quat")
            self.labs["tcp_quat"].setText(", ".join(f"{v:+.3f}" for v in q) if q else "缺")
            self.labs["tcp_frame"].setText(p.get("tcp_frame") or "-")
            # 位置变化率 (本窗口内相邻两次刷新差分, 真实运动指示)
            now = time.time()
            if tcp and getattr(self, "_last_tcp", None) is not None and now > getattr(self, "_last_t", 0):
                dt = now - self._last_t
                dx = sum((a - b) ** 2 for a, b in zip(tcp, self._last_tcp)) ** 0.5 / dt
                self.labs["tcp_dx"].setText(f"{dx:.4f}")
                self.labs["tcp_dx"].setStyleSheet(
                    f"color:{C_OK if dx > 0.002 else DIM};font-size:14px;")
            if tcp:
                self._last_tcp, self._last_t = tcp, now
            jp, jv = p.get("jpos") or [], p.get("jvel") or []
            for i in range(6):
                self.labs[f"q{i}"].setText(f"{jp[i]:+.4f}" if len(jp) > i else "-")
                self.labs[f"dq{i}"].setText(f"{jv[i]:+.4f}" if len(jv) > i else "缺")
            ft = p.get("ft")
            self.labs["s_force"].setText(", ".join(f"{v:+.3f}" for v in ft[:3]) if ft else "缺(无发布者)")
            self.labs["s_torque"].setText(", ".join(f"{v:+.3f}" for v in ft[3:6]) if ft else "缺(无发布者)")
            self.labs["s_grip"].setText(str(p.get("gripper")) if p.get("gripper") is not None else "缺(无发布者)")
            self.labs["s_tactile"].setText("缺(触觉话题未接)" if not p.get("tactile") else str(p["tactile"]))
            rs = {}
            try:
                import json as _j
                rs = _j.loads(p.get("robot_status") or "{}")
            except Exception:
                rs = {}
            self.labs["s_power"].setText(str(rs.get("power_state", "缺")))
            op = str(rs.get("operation_state", "缺"))
            self.labs["s_op"].setText(op)
            self.labs["s_op"].setStyleSheet(f"color:{C_OK if op == 'moving' else FG};font-size:14px;")
            self.labs["s_err"].setText(("有报警 " + str(rs.get("error_reason", ""))) if rs.get("has_error")
                                       else ("急停" if rs.get("estop_detected") else
                                             ("碰撞" if rs.get("collision_detected") else "正常")))
            st = self.src.probe()
            recv = st.get("recv") or {}
            self.labs["s_rate"].setText(("✅ " if p.get("fresh") else "⚠️过期 ") + f"{p.get('age_s')}s"
                                        + f" · tcp×{recv.get('tcp', 0)} joint×{recv.get('joint', 0)}")
            im = p.get("image") or {}
            png = im.get("png")
            if png and os.path.exists(png):
                pm = QtGui.QPixmap(png)
                if not pm.isNull():
                    self.img_view.setPixmap(pm.scaled(self.img_view.size(), QtCore.Qt.KeepAspectRatio,
                                                      QtCore.Qt.SmoothTransformation))
                self.img_meta.setText(f"话题: {im.get('topic')}\n尺寸: {im.get('w')}×{im.get('h')} "
                                      f"编码: {im.get('encoding')}\n对比度 std: {im.get('std')} "
                                      f"(>5 判真图)\n新鲜度: {im.get('age')}s\n文件: {os.path.basename(png)}")
            else:
                _pubs = (p.get("pubs") or {})
                _n = _pubs.get("/foundationpose/tray_reference/debug_image")
                _rs = _pubs.get("/realsense/color/image_raw")
                if _n:
                    self.img_view.setText("(话题在线, 当前无帧)")
                    self.img_meta.setText(f"话题: /foundationpose/tray_reference/debug_image\n发布者: {_n} (vision_tag) "
                                          f"— 在线但产线视觉空闲 → 无帧\nRealSense 彩色话题发布者: {_rs} "
                                          f"(D405 已接, Orin 未装 realsense2_camera)\n触觉: interfaces/msg/TactileSensor "
                                          f"(自定义消息, 容器无类型定义 → 暂不可订)")
                else:
                    self.img_view.setText("(无图像发布者)")
                    self.img_meta.setText("真机图像话题当前无发布者 (现场视觉节点未起)")
            b = self.src.read_bypass_status()
            last = b.get("last") or {}
            self.labs["b_stage"].setText(str(last.get("stage", "-")))
            self.labs["b_res"].setText(str(last.get("residual", "-")))
            self.labs["b_con"].setText(str(last.get("contact_p", "-")))
            self.labs["b_steps"].setText(f"{b.get('steps', '-')} / {b.get('samples', '-')}")
            zd = b.get("zero_downlink") or {}
            okz = bool(zd) and not zd.get("rclpy_imported")
            self.labs["b_zero"].setText("✅ 零下行" if okz else str(zd or "无心跳"))
            self.labs["b_zero"].setStyleSheet(f"color:{C_OK if okz else C_BAD};font-size:14px;")
            gaps = (b.get("gap") or {})
            gtxt = " · ".join(f"{k.split('(')[0]}×{v}" for k, v in gaps.items()) or "无"
            self.labs["b_gaps2"].setText(gtxt[:70])
            self.lab_foot.setText(f"数据源 {p.get('file')} · 关节名 {', '.join((p.get('jnames') or ['-'])[:2])}…"
                                  f" · 刷新 500ms · 缺通道按缺报缺 (不填假值)")
        except Exception as e:
            self.lab_foot.setText(f"⚠️ 刷新异常: {type(e).__name__}: {e}")


def open_z700_signals(module=None):
    """打开 Z700 真机信号面板 (单例由调用方持有)"""
    w = Z700SignalsView(module)
    w.show()
    return w


def open_bypass_view(module=None):
    """打开/复用窗口 (单例由调用方持有引用)"""
    w = SSBypassView(module)
    w.show()
    return w


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    win = SSBypassView()
    win.show()
    sys.exit(app.exec_())
