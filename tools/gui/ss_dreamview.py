# -*- coding: utf-8 -*-
"""
ss_dreamview.py — 🧭 状态空间 3D 分层视图 (参考百度 Apollo Dreamview, 2026-08-25 老倪)

在同一个 3D 空间 (与操作视频 gen_state_space_video.py 的物理世界坐标一致) 里,
叠加渲染状态空间仿真的所有处理层数据, 每层可独立开关 (Apollo Layer 风格):

  坐标世界: 工作台平面 + 孔位插座(红) + 光模块 peg(金) + 末端夹爪(蓝)
  处理层:
    🎯 YOLO 检测框  — hand/peg/hole 三个 3D 半透明立方体框
    📍 末端轨迹     — 末端历史 3D 轨迹线 (旧→新 渐亮)
    ⚡ 前馈建议 u_ff — 绿色箭头 (快通道·神经网络原始动作)
    🔄 反馈校正 u_fb — 蓝色箭头 (慢通道·卡尔曼残差方向)
    🧭 融合指令 u    — 金黄大箭头 + 目标点大球 (动作调制器输出, action 主图标)
    🛡 安全限幅 u_sat— 红色箭头 (限幅后指令)
    🔮 状态估计 latent — 潜状态轨迹点
    🧲 残差/接触     — 接触概率热力球 (接触时亮起)

用法:
  from ss_dreamview import DreamView3D
  dv = DreamView3D(tr)   # tr = state_space_sim.run() 的返回
  dv.show()
"""
import os
import numpy as np

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
                             QSlider, QPushButton, QFrame)

import pyqtgraph.opengl as gl

# 世界坐标边界 (与 gen_state_space_video.py 一致)
_X0, _X1 = 0.04, 0.31
_Y0, _Y1 = -0.11, 0.11
_Z0, _Z1 = 0.0, 0.16

# 场景锚点 (state_space_sim 物理世界)
_HOLE = np.array([0.25, 0.0, 0.05])   # 孔位插座


# ────────────────────────────────────────────────────────────
# 3D 几何 helper
# ────────────────────────────────────────────────────────────
def _box_mesh(center, size):
    """生成长方体 meshdata (12 三角形) — 用于场景几何体"""
    x0, y0, z0 = center
    sx, sy, sz = size
    v = np.array([[x0 + dx * sx / 2, y0 + dy * sy / 2, z0 + dz * sz / 2]
                  for dx in (-1, 1) for dy in (-1, 1) for dz in (-1, 1)], dtype=float)
    # 8 顶点 24 三角面
    faces = np.array([
        [0, 1, 3], [0, 3, 2],   # 前 z+
        [4, 6, 5], [4, 7, 6],   # 后 z-
        [0, 4, 5], [0, 5, 1],   # 底 y-
        [2, 3, 7], [2, 7, 6],   # 顶 y+
        [0, 2, 6], [0, 6, 4],   # 左 x-
        [1, 5, 7], [1, 7, 3],   # 右 x+
    ], dtype=int)
    return gl.MeshData(vertexes=v, faces=faces)


def _bbox_lines(center, size):
    """生成立方体 12 条边 (8 顶点 + 12 边索引) — 用于检测框"""
    x0, y0, z0 = center
    sx, sy, sz = size
    v = np.array([[x0 + dx * sx / 2, y0 + dy * sy / 2, z0 + dz * sz / 2]
                  for dx in (-1, 1) for dy in (-1, 1) for dz in (-1, 1)], dtype=float)
    # 12 条边 (顶点对)
    edges = np.array([
        [0, 1], [2, 3], [4, 5], [6, 7],   # z 向
        [0, 2], [1, 3], [4, 6], [5, 7],   # y 向
        [0, 4], [1, 5], [2, 6], [3, 7],   # x 向
    ], dtype=int)
    return v, edges


def _arrow(pos, action, scale=0.08):
    """由末端位置 pos + 动作向量 action(3D 速度指令) 生成箭头几何:
    返回 (line_pts 2x3, tip 目标点 3D, length 幅度)
    方向 = action 归一化, 长度 = clip(幅度, 0, 1) * scale (编码动作幅度)"""
    a = np.asarray(action[:3], dtype=float)
    mag = float(np.linalg.norm(a))
    if mag < 1e-9:
        return None, None, 0.0
    d = a / mag
    length = float(np.clip(mag, 0.0, 1.0)) * scale
    tip = np.asarray(pos, dtype=float) + d * length
    return np.array([pos[:3], tip], dtype=float), tip, length


def _cylinder_mesh(p1, p2, radius, cols=16):
    """生成两点之间的圆柱体 meshdata (p1→p2 轴向, 半径 radius)"""
    p1 = np.asarray(p1, dtype=float)
    p2 = np.asarray(p2, dtype=float)
    axis = p2 - p1
    length = float(np.linalg.norm(axis))
    if length < 1e-9:
        length = 1e-6
    z = np.array([0.0, 0.0, 1.0])
    d = axis / length
    # 旋转 z 轴对齐到 d (Rodrigues)
    v = np.cross(z, d)
    s = float(np.linalg.norm(v))
    c = float(np.dot(z, d))
    if s < 1e-9:
        R = np.eye(3) if c > 0 else np.diag([1.0, 1.0, -1.0])
    else:
        K = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
        R = np.eye(3) + K + K @ K * ((1 - c) / (s * s))
    md = gl.MeshData.cylinder(rows=1, cols=cols, radius=[radius, radius], length=length)
    verts = md.vertexes()
    # cylinder 顶点沿 z 从 0 到 length → 先平移到 -length/2, 再旋转, 再移到中点
    verts = verts - np.array([0, 0, length / 2.0])
    verts = verts @ R.T
    verts = verts + (p1 + p2) / 2.0
    return gl.MeshData(vertexes=verts, faces=md.faces())


def _sphere_mesh(center, radius, rows=8, cols=12):
    """生成球体 meshdata (中心在 center)"""
    md = gl.MeshData.sphere(rows=rows, cols=cols, radius=radius)
    verts = md.vertexes() + np.asarray(center, dtype=float)
    return gl.MeshData(vertexes=verts, faces=md.faces())


def _ik_sawyer(target, base, L1=0.16, L2=0.15):
    """Sawyer 机械臂 2 连杆 IK: 由末端 target + 底座 base → 肩/肘/腕关节位置
    底座竖直, 肩在 base 上方 H_base, 肘在肩下方弯曲 (Sawyer 肘上翻)
    返回 dict: base(底), shoulder(肩), elbow(肘), wrist(腕=target)"""
    t = np.asarray(target, dtype=float)
    b = np.asarray(base, dtype=float)
    H_BASE = 0.09          # 底座立柱高度
    shoulder = b + np.array([0.0, 0.0, H_BASE])
    # 腕 = 末端 target; 求肘 (平面内 2 连杆)
    r = t - shoulder
    d = float(np.linalg.norm(r))
    d = float(np.clip(d, abs(L1 - L2) + 1e-4, L1 + L2 - 1e-4))
    # 余弦定理求肘位置 (肘在 shoulder→wrist 连线"上方"弯曲, 取 z 分量偏上)
    a = (L1 * L1 - L2 * L2 + d * d) / (2.0 * d)   # shoulder→肘投影距离
    h = float(np.sqrt(max(0.0, L1 * L1 - a * a)))  # 肘到连线垂距
    u = r / d if d > 1e-9 else np.array([1.0, 0.0, 0.0])
    # 弯曲方向: 尽量朝 +z (肘上翻), 与 u 正交
    bend = np.array([0.0, 0.0, 1.0])
    bend = bend - np.dot(bend, u) * u
    bn = float(np.linalg.norm(bend))
    if bn < 1e-6:
        bend = np.array([0.0, 1.0, 0.0]) - np.dot(np.array([0.0, 1.0, 0.0]), u) * u
        bn = float(np.linalg.norm(bend))
    bend = bend / bn
    elbow = shoulder + a * u + h * bend
    return {"base": b, "shoulder": shoulder, "elbow": elbow, "wrist": t}


# ────────────────────────────────────────────────────────────
# 图层定义 (Apollo Layer)
# ────────────────────────────────────────────────────────────
_LAYER_COLORS = {
    "uff":     (0.20, 0.85, 0.35, 1.0),   # 绿  前馈建议
    "ufb":     (0.35, 0.62, 1.00, 1.0),   # 蓝  反馈校正
    "ufuse":   (1.00, 0.78, 0.12, 1.0),   # 金黄 融合指令 (action 主图标)
    "ulimit":  (1.00, 0.30, 0.30, 1.0),   # 红  安全限幅
    "yolo_hand": (0.35, 0.65, 1.00, 0.55),
    "yolo_peg":  (0.00, 0.83, 0.66, 0.55),
    "yolo_hole": (1.00, 0.65, 0.00, 0.55),
}


class DreamView3D(QWidget):
    """Apollo Dreamview 风格 3D 分层视图"""

    def __init__(self, tr=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🧭 状态空间 3D 分层视图 (Apollo 风格)")
        self.resize(1180, 820)
        self.setStyleSheet("QWidget{background:#0d1117; color:#e6edf3;}")

        self.tr = tr
        self._idx = 0
        self._playing = False
        self._gl_items = {}       # layer -> GL item(s)
        self._layer_on = {}       # layer -> bool

        # ── 主布局: 左(图层面板) | 3D 视图 ──
        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # 左侧图层开关面板 (Apollo Layer Menu)
        panel = QFrame()
        panel.setFixedWidth(230)
        panel.setStyleSheet("QFrame{background:#161b22; border:1px solid #30363d; border-radius:6px;}")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(12, 12, 12, 12)
        pl.setSpacing(6)
        title = QLabel("🗂 图层 (Layers)")
        title.setStyleSheet("color:#58a6ff; font-size:15px; font-weight:700;")
        pl.addWidget(title)
        hint = QLabel("勾选要观察的处理层")
        hint.setStyleSheet("color:#8b949e; font-size:11px;")
        pl.addWidget(hint)
        pl.addSpacing(6)

        # 图层: (key, 中文名, 默认开, 提示)
        self._layers_def = [
            ("scene",     "🏗 场景 (工作台/孔位/夹爪)", True,  "基础几何体, 建议常开"),
            ("yolo",      "🎯 YOLO 检测框",             True,  "hand/peg/hole 3D 框"),
            ("traj",      "📍 末端轨迹",                True,  "末端历史运动轨迹"),
            ("uff",       "⚡ 前馈建议 u_ff",           True,  "快通道·神经网络原始动作"),
            ("ufb",       "🔄 反馈校正 u_fb",           False, "慢通道·卡尔曼残差方向"),
            ("ufuse",     "🧭 融合指令 u (action输出)", True,  "动作调制器输出·主图标"),
            ("ulimit",    "🛡 安全限幅 u_sat",          False, "限幅后的最终指令"),
            ("latent",    "🔮 状态估计 latent",         False, "潜状态轨迹点"),
            ("contact",   "🧲 残差/接触",               True,  "接触概率热力球"),
        ]
        self._chk = {}
        for key, name, on, tip in self._layers_def:
            cb = QCheckBox(name)
            cb.setChecked(on)
            cb.setToolTip(tip)
            cb.setStyleSheet("QCheckBox{color:#e6edf3; font-size:13px;} QCheckBox::indicator{width:15px;height:15px;}")
            cb.toggled.connect(lambda checked, k=key: self._toggle_layer(k, checked))
            self._chk[key] = cb
            self._layer_on[key] = on
            pl.addWidget(cb)
        pl.addStretch(1)

        # 底部时间轴信息
        self.lbl_t = QLabel("t=0.00s · 帧 0/0")
        self.lbl_t.setStyleSheet("color:#8b949e; font-size:11px;")
        pl.addWidget(self.lbl_t)

        # 右侧 3D 视图
        right = QVBoxLayout()
        right.setSpacing(6)
        self.view = gl.GLViewWidget()
        self.view.setCameraPosition(distance=0.62, elevation=88, azimuth=180)
        self.view.setBackgroundColor('#0d1117')
        right.addWidget(self.view, 1)

        # 底部控制条
        ctrl = QHBoxLayout()
        ctrl.setSpacing(8)
        self.btn_play = QPushButton("▶ 播放")
        self.btn_play.setStyleSheet(
            "QPushButton{background:#1f6feb; color:#fff; border:none; border-radius:4px; padding:6px 16px; font-size:13px;}"
            "QPushButton:hover{background:#2f7ff0;}")
        self.btn_play.clicked.connect(self._toggle_play)
        ctrl.addWidget(self.btn_play)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.sliderMoved.connect(self._on_slider)
        self.slider.sliderPressed.connect(self._pause)
        ctrl.addWidget(self.slider, 1)

        self.lbl_frame = QLabel("0 / 0")
        self.lbl_frame.setStyleSheet("color:#8b949e; font-size:12px; min-width:70px;")
        ctrl.addWidget(self.lbl_frame)
        right.addLayout(ctrl)

        root.addWidget(panel)
        root.addLayout(right, 1)

        # 播放定时器
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

        if tr is not None:
            self.set_trajectory(tr)

    # ── 数据装载 ──
    def set_trajectory(self, tr):
        self.tr = tr
        n = len(tr.get("x", []))
        self._n = n
        self.slider.setRange(0, max(0, n - 1))
        self._build_scene()
        if n > 0:
            self._update_frame(0)
            self.lbl_frame.setText(f"0 / {n - 1}")

    # ── 场景构建 ──
    def _build_scene(self):
        for it in self._gl_items.values():
            if isinstance(it, list):
                for x in it:
                    self.view.removeItem(x)
            else:
                self.view.removeItem(it)
        self._gl_items.clear()

        # 地面网格 (z=0)
        gz = gl.GLGridItem()
        gz.setSize(0.4, 0.3)
        gz.setSpacing(0.05, 0.05)
        gz.translate(0.17, 0.0, 0.0)
        self._gl_items["_grid"] = gz
        self.view.addItem(gz)

        # 坐标轴
        ax = gl.GLAxisItem()
        ax.setSize(0.12, 0.12, 0.12)
        self._gl_items["_axis"] = ax
        self.view.addItem(ax)

        # 场景层 (静态几何: 工作台 + 孔位插座; peg/夹爪动态, 见 _update_frame)
        scene = []
        # 工作台 (薄板)
        table = gl.GLMeshItem(meshdata=_box_mesh((0.17, 0.0, -0.015), (0.34, 0.28, 0.03)),
                              color=(0.16, 0.18, 0.22, 1.0), smooth=False, shader='shaded')
        self.view.addItem(table)
        scene.append(table)
        # 孔位插座 (红, 醒目) + 深色孔口 (插销目标)
        # 注意: 插座压矮 (z 0~0.03), 末端插销最低 z=0.048 始终露在插座上方, 俯视可见
        hole = gl.GLMeshItem(meshdata=_box_mesh((_HOLE[0], _HOLE[1], 0.015), (0.13, 0.13, 0.03)),
                             color=(0.95, 0.22, 0.14, 1.0), smooth=False, shader='shaded')
        self.view.addItem(hole)
        scene.append(hole)
        # 孔口 (深色凹陷, 插销插入位置)
        hole_mouth = gl.GLMeshItem(meshdata=_box_mesh((_HOLE[0], _HOLE[1], 0.035), (0.06, 0.06, 0.008)),
                                   color=(0.05, 0.04, 0.03, 1.0), smooth=False, shader='shaded')
        self.view.addItem(hole_mouth)
        scene.append(hole_mouth)
        self._gl_items["scene"] = scene

        # 🤖 Sawyer 机械臂 (2026-08-25 老倪: 形象渲染 — 底座+肩+肘+腕+夹爪)
        self._arm_base = np.array([0.12, -0.20, 0.0])   # 底座固定在工作区后方
        arm = []
        # 底座立柱 (竖直圆柱)
        arm_base = gl.GLMeshItem(meshdata=_cylinder_mesh(self._arm_base, self._arm_base + [0, 0, 0.09], 0.035),
                                 color=(0.30, 0.32, 0.36, 1.0), smooth=True, shader='shaded')
        self.view.addItem(arm_base)
        arm.append(arm_base)
        # 肩/肘/腕关节球 + 上臂/前臂圆柱 (动态更新, 先占位)
        arm_upper = gl.GLMeshItem(meshdata=_cylinder_mesh([0, 0, 0], [0, 0, 0.001], 0.022),
                                  color=(0.85, 0.30, 0.18, 1.0), smooth=True, shader='shaded')
        self.view.addItem(arm_upper)
        arm.append(arm_upper)
        arm_fore = gl.GLMeshItem(meshdata=_cylinder_mesh([0, 0, 0], [0, 0, 0.001], 0.018),
                                 color=(0.85, 0.30, 0.18, 1.0), smooth=True, shader='shaded')
        self.view.addItem(arm_fore)
        arm.append(arm_fore)
        arm_shoulder = gl.GLMeshItem(meshdata=_sphere_mesh([0, 0, 0], 0.030),
                                     color=(0.40, 0.42, 0.46, 1.0), smooth=True, shader='shaded')
        self.view.addItem(arm_shoulder)
        arm.append(arm_shoulder)
        arm_elbow = gl.GLMeshItem(meshdata=_sphere_mesh([0, 0, 0], 0.026),
                                  color=(0.40, 0.42, 0.46, 1.0), smooth=True, shader='shaded')
        self.view.addItem(arm_elbow)
        arm.append(arm_elbow)
        arm_wrist = gl.GLMeshItem(meshdata=_sphere_mesh([0, 0, 0], 0.022),
                                  color=(0.40, 0.42, 0.46, 1.0), smooth=True, shader='shaded')
        self.view.addItem(arm_wrist)
        arm.append(arm_wrist)
        # 夹爪两瓣 (动态开合)
        arm_jaw_l = gl.GLMeshItem(meshdata=_box_mesh([0, 0, 0], (0.012, 0.018, 0.04)),
                                  color=(0.55, 0.60, 0.68, 1.0), smooth=True, shader='shaded')
        self.view.addItem(arm_jaw_l)
        arm.append(arm_jaw_l)
        arm_jaw_r = gl.GLMeshItem(meshdata=_box_mesh([0, 0, 0], (0.012, 0.018, 0.04)),
                                  color=(0.55, 0.60, 0.68, 1.0), smooth=True, shader='shaded')
        self.view.addItem(arm_jaw_r)
        arm.append(arm_jaw_r)
        # 光模块 peg (金色插销, 被夹爪夹持, 随末端移动)
        arm_peg = gl.GLMeshItem(meshdata=_box_mesh([0, 0, 0], (0.07, 0.05, 0.05)),
                                color=(0.95, 0.72, 0.10, 1.0), smooth=True, shader='shaded')
        self.view.addItem(arm_peg)
        arm.append(arm_peg)
        self._gl_items["arm"] = arm
        self._arm_idx = {"upper": 1, "fore": 2, "shoulder": 3, "elbow": 4,
                         "wrist": 5, "jaw_l": 6, "jaw_r": 7, "peg": 8}

        # 动态层占位 (创建空 item, 更新时 setData)
        # 轨迹线
        traj = gl.GLLinePlotItem(pos=np.zeros((2, 3)), color=(0.35, 0.65, 1.0, 1.0), width=2)
        self.view.addItem(traj)
        self._gl_items["traj"] = traj

        # 箭头线 (4 层动作)
        for key in ("uff", "ufb", "ufuse", "ulimit"):
            col = _LAYER_COLORS[key]
            ln = gl.GLLinePlotItem(pos=np.zeros((2, 3)), color=col, width=(6 if key == "ufuse" else 3))
            self.view.addItem(ln)
            self._gl_items[key + "_line"] = ln
            # 箭头头 (小锥体 / 目标点球)
            tip = gl.GLScatterPlotItem(pos=np.zeros((1, 3)), color=col,
                                       size=(14 if key == "ufuse" else 8))
            self.view.addItem(tip)
            self._gl_items[key + "_tip"] = tip

        # 融合指令目标点大球 (action 主图标 — 明显醒目)
        fuse_sphere = gl.GLScatterPlotItem(pos=np.zeros((1, 3)), color=_LAYER_COLORS["ufuse"], size=18)
        self.view.addItem(fuse_sphere)
        self._gl_items["ufuse_sphere"] = fuse_sphere

        # YOLO 检测框 (3 个立方体线框)
        yolo = []
        for cls, col in (("hand", _LAYER_COLORS["yolo_hand"]),
                         ("peg", _LAYER_COLORS["yolo_peg"]),
                         ("hole", _LAYER_COLORS["yolo_hole"])):
            ln = gl.GLLinePlotItem(pos=np.zeros((12, 3)), color=col, width=2, mode='lines')
            self.view.addItem(ln)
            self._gl_items["yolo_" + cls] = ln
            yolo.append(ln)
        self._gl_items["yolo"] = yolo

        # 状态估计 latent 轨迹点
        latent = gl.GLScatterPlotItem(pos=np.zeros((1, 3)), color=(0.85, 0.45, 0.95, 1.0), size=6)
        self.view.addItem(latent)
        self._gl_items["latent"] = latent

        # 接触热力球
        contact = gl.GLScatterPlotItem(pos=np.zeros((1, 3)), color=(1.0, 0.4, 0.0, 1.0), size=10)
        self.view.addItem(contact)
        self._gl_items["contact"] = contact

        # 应用当前图层开关状态
        for key, on in self._layer_on.items():
            self._apply_layer_visibility(key, on)

    def _apply_layer_visibility(self, key, on):
        items = self._gl_items.get(key)
        if items is None:
            return
        if isinstance(items, list):
            for it in items:
                it.setVisible(on)
        else:
            items.setVisible(on)
        # 🤖 机械臂随 scene 层联动开关 (2026-08-25)
        if key == "scene":
            arm = self._gl_items.get("arm")
            if arm:
                for it in arm:
                    it.setVisible(on)

    # ── 图层开关 ──
    def _toggle_layer(self, key, checked):
        self._layer_on[key] = checked
        self._apply_layer_visibility(key, checked)

    # ── 帧更新 ──
    def _update_frame(self, i):
        tr = self.tr
        if not tr or self._n == 0:
            return
        i = int(np.clip(i, 0, self._n - 1))
        self._idx = i
        xs = np.asarray(tr["x"])
        x = xs[i]

        # 末端轨迹 (0..i)
        if i >= 1:
            traj_pts = xs[:i + 1]
        else:
            traj_pts = np.array([x, x])
        self._gl_items["traj"].setData(pos=traj_pts)

        # 🤖 Sawyer 机械臂 IK (末端=peg 位置, 夹爪开合随 gripper)
        ik = _ik_sawyer(x, self._arm_base)
        arm = self._gl_items["arm"]
        arm[self._arm_idx["upper"]].setMeshData(meshdata=_cylinder_mesh(ik["shoulder"], ik["elbow"], 0.022))
        arm[self._arm_idx["fore"]].setMeshData(meshdata=_cylinder_mesh(ik["elbow"], ik["wrist"], 0.018))
        arm[self._arm_idx["shoulder"]].setMeshData(meshdata=_sphere_mesh(ik["shoulder"], 0.030))
        arm[self._arm_idx["elbow"]].setMeshData(meshdata=_sphere_mesh(ik["elbow"], 0.026))
        arm[self._arm_idx["wrist"]].setMeshData(meshdata=_sphere_mesh(ik["wrist"], 0.022))
        # 夹爪开合: gripper 0(开)→1(闭), 两瓣间距随开度
        g = float(tr["gripper"][i])
        gap = 0.010 + (1.0 - g) * 0.018
        jaw_dir = np.array([0.0, 1.0, 0.0])   # 沿 y 开合
        arm[self._arm_idx["jaw_l"]].setMeshData(meshdata=_box_mesh(ik["wrist"] + jaw_dir * gap, (0.012, 0.014, 0.04)))
        arm[self._arm_idx["jaw_r"]].setMeshData(meshdata=_box_mesh(ik["wrist"] - jaw_dir * gap, (0.012, 0.014, 0.04)))
        # peg 随末端 (被夹爪夹住)
        arm[self._arm_idx["peg"]].setMeshData(meshdata=_box_mesh(ik["wrist"], (0.07, 0.05, 0.05)))

        # 动作箭头 (4 层)
        for key in ("uff", "ufb", "ufuse", "ulimit"):
            a = tr[self._vec_key(key)][i]
            pts, tip, _ = _arrow(x, a)
            if pts is not None:
                self._gl_items[key + "_line"].setData(pos=pts)
                self._gl_items[key + "_tip"].setData(pos=np.array([tip]))
            else:
                self._gl_items[key + "_line"].setData(pos=np.array([x[:3], x[:3]]))
                self._gl_items[key + "_tip"].setData(pos=np.array([x[:3]]))

        # 融合指令目标点大球 (跟随箭头尖端)
        a_fuse = tr["u_fuse_vec"][i]
        _, tip, _ = _arrow(x, a_fuse)
        if tip is not None:
            self._gl_items["ufuse_sphere"].setData(pos=np.array([tip]))

        # YOLO 检测框: hand/peg/hole 三个框 (用场景真实 3D 坐标)
        #   hand ≈ 末端, peg ≈ 末端 (peg 随末端), hole ≈ 孔位
        boxes = [("hand", x, (0.065, 0.045, 0.02)),
                 ("peg", x, (0.055, 0.032, 0.032)),
                 ("hole", _HOLE, (0.08, 0.08, 0.04))]
        for cls, ctr, sz in boxes:
            v, edges = _bbox_lines(ctr, sz)
            # 线框: 每条边 2 顶点 → 12 条边拼成 24 点序列
            line_pts = []
            for e in edges:
                line_pts.append(v[e[0]])
                line_pts.append(v[e[1]])
            self._gl_items["yolo_" + cls].setData(pos=np.array(line_pts))

        # 状态估计 latent (位置3 + 预测力)
        latent = tr["latent_vec"][i][:3]
        # 画最近 N 步的 latent 轨迹
        win = min(i + 1, 60)
        lat_pts = np.array([tr["latent_vec"][k][:3] for k in range(i - win + 1, i + 1)])
        self._gl_items["latent"].setData(pos=lat_pts)

        # 接触热力球 (接触概率高时在末端亮起大球)
        cp = tr["contact_p"][i]
        if cp > 0.3:
            sz = 6 + 20 * min(1.0, cp)
            self._gl_items["contact"].setData(pos=np.array([x]), size=sz,
                                              color=(1.0, 0.4 - 0.3 * cp, 0.0, min(1.0, 0.4 + cp)))
        else:
            self._gl_items["contact"].setData(pos=np.array([x]), size=4,
                                              color=(1.0, 0.4, 0.0, 0.25))

        # 时间轴标签
        t = tr["t"][i]
        stage = tr["stage"][i].replace("阶段 ", "")
        self.lbl_t.setText(f"t={t:.2f}s · 帧 {i}/{self._n - 1}\n阶段 {stage}")
        self.lbl_frame.setText(f"{i} / {self._n - 1}")
        if not self.slider.isSliderDown():
            self.slider.setValue(i)

    def _vec_key(self, key):
        """动作向量在 tr 里的键名映射"""
        return {"uff": "u_ff_vec", "ufb": "u_fb_vec",
                "ufuse": "u_fuse_vec", "ulimit": "u_limit_vec"}[key]

    # ── 播放控制 ──
    def _toggle_play(self):
        if self._playing:
            self._pause()
        else:
            self._playing = True
            self.btn_play.setText("⏸ 暂停")
            self._timer.start(60)

    def _pause(self):
        self._playing = False
        self.btn_play.setText("▶ 播放")
        self._timer.stop()

    def _tick(self):
        if self._idx >= self._n - 1:
            self._pause()
            return
        self._update_frame(self._idx + 1)

    def _on_slider(self, val):
        self._update_frame(val)


# ────────────────────────────────────────────────────────────
# 命令行自测
# ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from state_space_sim import StateSpaceSim
    from PyQt5.QtWidgets import QApplication

    os.environ.setdefault("DISPLAY", ":0")
    app = QApplication(sys.argv)
    sim = StateSpaceSim(log=lambda *a: None)
    tr = sim.run()
    w = DreamView3D(tr)
    w.show()
    sys.exit(app.exec_())
