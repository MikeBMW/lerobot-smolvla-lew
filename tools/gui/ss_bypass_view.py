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
SS = (f"QWidget {{ background:{BG}; color:{FG}; font-family:'Noto Sans CJK SC','Microsoft YaHei',sans-serif; }}"
      f"QLabel {{ color:{FG}; font-size:13px; }}"
      f"QGroupBox {{ border:1px solid #30363d; border-radius:6px; margin-top:10px; padding:8px; color:{DIM}; }}"
      f"QGroupBox::title {{ subcontrol-origin: margin; left:10px; color:{DIM}; }}")


class CurveWidget(QtWidgets.QWidget):
    """双通道时间序列 (残差 / 接触概率) — 纯 QPainter, 无 GL/第三方依赖"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(260)
        self.res = []          # [(t, residual)]
        self.con = []          # [(t, contact_p)]
        self.dx = []           # [(t, 真机位移速率 m/s)] — 真口径接入前唯一有分辨力的真实通道
        self.rows = 0

    def set_data(self, rows):
        self.rows = len(rows)
        self.res = [(float(r.get("t", 0)), float(r.get("residual", 0) or 0)) for r in rows]
        self.con = [(float(r.get("t", 0)), float(r.get("contact_p", 0) or 0)) for r in rows]
        self.dx = [(float(r.get("t", 0)), float(r.get("dx_real", 0) or 0)) for r in rows]
        self.update()

    def _draw(self, p, series, color, label, y0, h, ymin, ymax, fmt):
        w = max(1, self.width() - 70)
        p.setPen(QtGui.QPen(QtGui.QColor("#21262d"), 1))
        p.drawLine(60, y0, 60 + w, y0)
        p.drawLine(60, y0 + h, 60 + w, y0 + h)
        p.setPen(QtGui.QPen(QtGui.QColor(DIM), 1))
        p.drawText(6, y0 + 12, label)
        p.drawText(6, y0 + h, fmt(ymin))
        p.drawText(6, y0 + 14, fmt(ymax))
        if len(series) < 2:
            p.setPen(QtGui.QPen(QtGui.QColor(DIM), 1))
            p.drawText(70, y0 + h // 2, "等待旁路逐帧记录…")
            return
        n = len(series)
        span = max(1e-9, ymax - ymin)
        pts = []
        for i, (_, v) in enumerate(series):
            x = 60 + int(w * i / (n - 1))
            y = y0 + h - int(h * (max(ymin, min(ymax, v)) - ymin) / span)
            pts.append(QtCore.QPoint(x, y))
        p.setPen(QtGui.QPen(QtGui.QColor(color), 2))
        p.drawPolyline(QtGui.QPolygon(pts))
        p.setBrush(QtGui.QBrush(QtGui.QColor(color)))
        p.setPen(QtCore.Qt.NoPen)
        p.drawEllipse(pts[-1], 3, 3)
        p.setPen(QtGui.QPen(QtGui.QColor(FG), 1))
        p.drawText(70 + w - 160, y0 + 12, f"最新 {series[-1][1]:.4f} · 最近 {n} 帧")

    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor(PANEL))
        h = (self.height() - 42) // 3
        rmax = max([v for _, v in self.res] + [1e-6])
        dmax = max([v for _, v in self.dx] + [1e-6])
        self._draw(p, self.res, C_RES, "残差 (m)", 4, h, 0.0, rmax * 1.15 + 1e-9, lambda v: f"{v:.4f}")
        self._draw(p, self.con, C_CON, "接触概率", 4 + h + 14, h, 0.0, 1.0, lambda v: f"{v:.2f}")
        self._draw(p, self.dx, C_OK, "真机位移速率 (m/s)",
                   4 + 2 * (h + 14), h, 0.0, dmax * 1.15 + 1e-9, lambda v: f"{v:.4f}")
        p.setPen(QtGui.QPen(QtGui.QColor(DIM), 1))
        p.drawText(60, self.height() - 4, f"逐帧记录 {self.rows} 条 · 横轴=时间(等距) · 纵轴各自归一")


class SSBypassView(QtWidgets.QWidget):
    """旁路实时可视化窗口 (非模态, 可常开)"""

    def __init__(self, module=None):
        super().__init__(None, QtCore.Qt.Window)
        self.module = module
        self.setWindowTitle("📈 旁路实时可视化 — 状态空间 (当前阶段 / 残差 / 接触概率)")
        self.resize(980, 560)
        self.setStyleSheet(SS)
        self.src = _load_src()
        self._build()
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(500)
        self.refresh()

    def _row(self, k):
        lab = QtWidgets.QLabel("-")
        lab.setStyleSheet(f"color:{FG};font-size:14px;")
        kk = QtWidgets.QLabel(k)
        kk.setStyleSheet(f"color:{DIM};font-size:12px;")
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
        head.setStyleSheet(f"color:{DIM};font-size:12px;")
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
                                         ("机器人状态", "pose_rs", "电源 / 运行 / 报警 / 急停 / 碰撞")]):
            w, lab = self._row(t_)
            lab.setStyleSheet(f"color:{FG};font-size:12px;")
            self.labs["p_" + k] = lab
            gp.addWidget(w, i // 3, i % 3)
        root.addWidget(gbp)

        gbimg = QtWidgets.QGroupBox("实时图像 (RealSense 彩色优先 / FoundationPose 调试帧兜底)")
        gi = QtWidgets.QHBoxLayout(gbimg)
        self.img_view = QtWidgets.QLabel("(无图像)")
        self.img_view.setFixedSize(320, 240)
        self.img_view.setStyleSheet("background:#161b22; color:#8b949e; border:1px solid #30363d;")
        self.img_view.setAlignment(QtCore.Qt.AlignCenter)
        self.img_meta = QtWidgets.QLabel("-")
        self.img_meta.setStyleSheet(f"color:{FG};font-size:12px;")
        self.img_meta.setWordWrap(True)
        gi.addWidget(self.img_view)
        gi.addWidget(self.img_meta, 1)
        root.addWidget(gbimg)

        self.curve = CurveWidget()
        root.addWidget(self.curve, 1)
        self.lab_foot = QtWidgets.QLabel("")
        self.lab_foot.setStyleSheet(f"color:{DIM};font-size:11px;")
        root.addWidget(self.lab_foot)

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
            self.labs["p_pose_dq"].setStyleSheet(f"color:{C_OK if moving else DIM};font-size:12px;")
            dxr = (last.get("dx_real") if last else None)
            self.labs["p_pose_dx"].setText(f"{dxr:.4f}" if isinstance(dxr, (int, float)) else "-")
            self.labs["p_pose_dx"].setStyleSheet(
                f"color:{C_OK if isinstance(dxr, (int, float)) and dxr > 0.002 else DIM};font-size:12px;")
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

            # 实时图像 (多话题状态如实显示)
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

            rows = self.src.tail_bypass(240)
            self.curve.set_data(rows)
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
