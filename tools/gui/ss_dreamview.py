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
from PyQt5.QtGui import QVector3D
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
                             QSlider, QPushButton, QFrame)

import pyqtgraph.opengl as gl


# ════════════════════════════════════════════════════════════════
# 同源 episode trace 装载 (2026-08-25 老倪: 「3D 视图和操作视频的内容/角度/轨迹都不一样」)
#   根因: 视频是 metaworld MuJoCo 真实 episode, 3D 视图画的是纯 numpy 引擎的轨迹 →
#         两套物理必然对不上。真解 = 同源: tools/gen_ss_metaworld_episode.py 让状态空间
#         六层源码直接驱动 metaworld, 一次跑出 trace(处理层向量全在) + 同一条 episode 的
#         mp4。3D 视图优先读这个 trace, 相机用 trace 里记录的 corner2 真实外参。
# ════════════════════════════════════════════════════════════════
EPISODE_NPZ = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "reports", "ss_episode_latest.npz")


def load_episode(path=EPISODE_NPZ):
    """读同源 episode trace → (tr dict, meta dict); 文件不存在返回 (None, None)

    同源自检 (2026-08-25): npz 与同名 mp4 必须是同一次运行的产物 —
    只写 npz 的跑法 (--no-video) 一旦覆盖 latest, 3D 视图与操作视频就会悄悄错位。
    这里比对 npz/mp4 的修改时间, 差 >30s 就在 meta 里挂 `pair_warn` 供 GUI 打印警告。"""
    if not os.path.isfile(path):
        return None, None
    try:
        z = np.load(path, allow_pickle=True)
        meta = dict(z["meta"][0])
        tr = {}
        for k in z.files:
            if k == "meta":
                continue
            arr = z[k]
            tr[k] = [str(s) for s in arr] if k == "stage" else arr
        mp4 = os.path.splitext(path)[0] + ".mp4"
        if not os.path.isfile(mp4):
            meta["pair_warn"] = f"缺少同名视频 {os.path.basename(mp4)} — 无法确认与操作视频同源"
        else:
            dt = abs(os.path.getmtime(path) - os.path.getmtime(mp4))
            if dt > 30:
                meta["pair_warn"] = (f"npz 与 mp4 修改时间差 {dt:.0f}s (>30s) — "
                                     f"可能不是同一条 episode, 重跑 gen_ss_metaworld_episode.py")
        tr["_meta"] = meta
        return tr, meta
    except Exception:
        return None, None


def camera_quaternion(fwd, right, up):
    """由相机基底 (视线/右/上) 构造 pyqtgraph 'quaternion' 模式所需的旋转四元数。
    pyqtgraph viewMatrix = T(0,0,-d) · R · T(-center) → R 必须把世界偏移映射到
    相机系 (x=右, y=上, z=-视线) ⇒ R 的行 = [right, up, -fwd]。"""
    from PyQt5.QtGui import QMatrix4x4, QQuaternion
    r = np.asarray(right, float) / (np.linalg.norm(right) or 1)
    u = np.asarray(up, float) / (np.linalg.norm(up) or 1)
    f = np.asarray(fwd, float) / (np.linalg.norm(fwd) or 1)
    R = np.vstack([r, u, -f])
    m = QMatrix4x4(float(R[0, 0]), float(R[0, 1]), float(R[0, 2]), 0.0,
                   float(R[1, 0]), float(R[1, 1]), float(R[1, 2]), 0.0,
                   float(R[2, 0]), float(R[2, 1]), float(R[2, 2]), 0.0,
                   0.0, 0.0, 0.0, 1.0)
    return QQuaternion.fromRotationMatrix(m.normalMatrix())


def fov_h_from_fovy(fovy_deg, w, h):
    """metaworld 相机给的是**垂直** fovy, 而 pyqtgraph opts['fov'] 是**水平** fov
    (源码: r = near·tan(fov/2); t = r·h/w) → 必须换算, 否则画幅不是正方形时
    3D 视图的缩放和视频差一截 (实测非正方形窗口下物体投影偏 60px)。"""
    import math
    w = max(1, int(w))
    h = max(1, int(h))
    return 2.0 * math.degrees(math.atan(math.tan(math.radians(fovy_deg / 2.0)) * w / h))


def project_world(view, p):
    """世界点 → 归一化屏幕 (0~1, 左上原点) — 与 pyqtgraph 投影约定严格一致。
    离屏(无 GL 上下文)也能算: 只用 viewMatrix + opts['fov'] 手算透视, 不碰 projectionMatrix。
    唯一实现, 探针 (probe_view_match / probe_view_render) 全部复用, 防口径分裂。"""
    import math
    c = view.viewMatrix().map(QVector3D(float(p[0]), float(p[1]), float(p[2])))
    depth = -c.z()
    if depth <= 1e-6:
        return None
    w, h = max(1, view.width()), max(1, view.height())
    r = math.tan(math.radians(float(view.opts.get("fov", 60.0)) / 2.0))
    t = r * h / w
    nx = (c.x() / depth) / r
    ny = (c.y() / depth) / t
    return (0.5 * (nx + 1.0), 0.5 * (1.0 - ny))

# ════════════════════════════════════════════════════════════════
# 场景锚点 — 2026-08-25 老倪: 与操作视频 (metaworld peg-insert-side-v3) 同一套真实几何
# 实测来源 tools/probe_scene_geom.py: 插销 pegGrasp(0.0966,0.5191,0.030) 沿 X 长 0.2,
# 孔口 hole(-0.1685,0.4623,0.1309), 插入终点 goal(-0.2345,0.4623,0.1309),
# 带孔盒 box 中心(-0.2645,0.4623,~0.095), 机器人底座 base(0,0,0) 肩高 0.317
# ════════════════════════════════════════════════════════════════
_HOLE = np.array([-0.2345, 0.4623, 0.1309])        # 插入终点 (goal)
_HOLE_MOUTH = np.array([-0.1685, 0.4623, 0.1309])  # 孔口 (侧插入口)
_BOX_CENTER = np.array([-0.2645, 0.4623, 0.095])   # 带孔盒中心
_BOX_SIZE = (0.19, 0.20, 0.19)                     # 带孔盒尺寸
_TABLE_CENTER = np.array([0.0, 0.58, -0.012])      # 台面板中心
_TABLE_SIZE = (0.92, 0.62, 0.024)
_PEG_SIZE = (0.20, 0.03, 0.03)                     # 插销 (沿 X 长条)
_PEG_CENTER_OFF = np.array([-0.030, 0.0, -0.010])  # 插销几何中心相对抓握点
_ARM_BASE = np.array([0.0, 0.0, 0.0])              # Sawyer 底座 (metaworld base)
_ARM_H_BASE = 0.317                                # 肩高
_ARM_L1 = _ARM_L2 = 0.42                           # 上臂/前臂 (够到 y=0.6 工作台)
# 相机 = 操作视频 metaworld corner2 换算值 (probe_video_view.py 实测):
#   cam_pos(1.3,-0.2,1.1) 视线(-0.746,0.458,-0.484) → elevation 28.9° / azimuth 328.4°
#   (视频里 aligner 分支做 np.rot90(k=2), 旋转后世界 +Z 朝屏幕上 = z-up 常规视角)
_CAM_ELEV = 28.9
_CAM_AZIM = 328.4
_CAM_CENTER = QVector3D(-0.07, 0.50, 0.08)
_CAM_DIST = 1.05


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


def _ik_sawyer(target, base, L1=_ARM_L1, L2=_ARM_L2, h_base=_ARM_H_BASE):
    """Sawyer 机械臂 2 连杆 IK: 由末端 target + 底座 base → 肩/肘/腕关节位置
    底座竖直, 肩在 base 上方 H_base, 肘在肩下方弯曲 (Sawyer 肘上翻)
    返回 dict: base(底), shoulder(肩), elbow(肘), wrist(腕=target)"""
    t = np.asarray(target, dtype=float)
    b = np.asarray(base, dtype=float)
    shoulder = b + np.array([0.0, 0.0, h_base])
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
        # 🖥 2026-08-25 老倪: 置顶 — 不被「操作视频」窗口(InferenceVideoDialog/MLPRolloutDialog, 经 _show_nonmodal 均置顶)遮挡
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setStyleSheet("QWidget{background:#0d1117; color:#e6edf3;}")

        self.tr = tr
        self._idx = 0
        self._playing = False
        self._gl_items = {}       # layer -> GL item(s)
        self._layer_on = {}       # layer -> bool
        # 场景锚点 (默认 = metaworld seed0 典型值; 同源 trace 里有 meta 就按 meta 覆盖 —
        #  metaworld 每个 seed 的插销/孔位是随机化的, 写死会和视频对不上)
        self._hole = _HOLE.copy()
        self._mouth = _HOLE_MOUTH.copy()
        self._box_c = _BOX_CENTER.copy()
        self._table_c = _TABLE_CENTER.copy()
        self._peg_center_off = _PEG_CENTER_OFF.copy()
        self._src = "状态空间 numpy 引擎"
        self._cam_fovy = 60.0     # 视频相机垂直视场 (metaworld corner2 fovy)

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
            ("latent",    "🔮 状态估计 x̂ (卡尔曼)",     False,
             "慢通道 AdaptiveStateEstimator 的后验位置估计 x̂ₖ = 预测 + K·(观测−预测);\n"
             "紫线 = 最近 60 帧估计轨迹, 大球 = 当前帧估计位置。\n"
             "与蓝色真实末端轨迹的偏离量 = 残差 (接触/扰动来源), 调度器据此判接触概率"),
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
        # rotationMethod='quaternion': 才能精确设定相机朝向 (含 roll) = 视频相机外参
        self.view = gl.GLViewWidget(rotationMethod='quaternion')
        # 🧭 2026-08-25 老倪: 视角对齐操作视频 — 不再是正俯视 (elev 88), 改成 metaworld
        # corner2 相机的斜视角 (elev 28.9 / azim 328.4, probe_video_view.py 实测换算),
        # 与视频里看到的方向一致: 世界 +X→屏幕右下 · +Y→右上 · +Z→上
        self.view.setCameraPosition(pos=_CAM_CENTER, distance=_CAM_DIST,
                                    elevation=_CAM_ELEV, azimuth=_CAM_AZIM)
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
        meta = tr.get("_meta") if isinstance(tr, dict) else None
        if meta:
            self._apply_meta(meta)
        n = len(tr.get("x", []))
        self._n = n
        self.slider.setRange(0, max(0, n - 1))
        self._build_scene()
        if n > 0:
            self._update_frame(0)
            self.lbl_frame.setText(f"0 / {n - 1}")

    # ── 同源 episode: 场景几何 + 相机 全部按 trace 里的真实值 ──
    def _apply_meta(self, meta):
        """meta 来自 gen_ss_metaworld_episode.py (与操作视频同一条 episode):
        真实孔口/插入终点/盒子/台面坐标 + corner2 相机外参 (含 rot180 等效基底)"""
        try:
            self._hole = np.asarray(meta.get("goal", self._hole), dtype=float)
            self._mouth = np.asarray(meta.get("hole_mouth", self._mouth), dtype=float)
            self._box_c = np.asarray(meta.get("box_center", self._box_c), dtype=float)
            tc = np.asarray(meta.get("table_center", self._table_c), dtype=float)
            self._table_c = np.array([tc[0], tc[1], _TABLE_CENTER[2]])
            head_off = np.asarray(meta.get("peg_head_off", np.array([-0.13, 0, -0.01])), dtype=float)
            self._peg_center_off = head_off * 0.5 + np.array([0.035, 0.0, 0.0])
            self._src = (f"操作视频同源 episode (metaworld seed={meta.get('seed')}, "
                         f"{meta.get('steps')} 步, 终态 {meta.get('stage_final')})")
            # 相机: 精确对齐视频 corner2 (四元数含 roll), 视距 = 相机到场景锚点的真实距离
            cp = np.asarray(meta["cam_pos"], dtype=float)
            cf = np.asarray(meta["cam_fwd"], dtype=float)
            cr = np.asarray(meta["cam_right"], dtype=float)
            cu = np.asarray(meta["cam_up"], dtype=float)
            self._cam_fovy = float(meta.get("cam_fovy", 60.0))
            anchor = 0.5 * (np.asarray(meta.get("peg0", self._mouth), dtype=float) + self._mouth)
            t = float(np.dot(anchor - cp, cf / (np.linalg.norm(cf) or 1)))
            center = cp + cf / (np.linalg.norm(cf) or 1) * t
            self.view.opts["rotationMethod"] = "quaternion"
            self.view.setCameraPosition(pos=QVector3D(*center.tolist()),
                                        distance=max(0.3, t),
                                        rotation=camera_quaternion(cf, cr, cu))
            self._sync_fov()
            self.setWindowTitle("🧭 状态空间 3D 分层视图 — 与操作视频同源 (metaworld corner2 视角)")
        except Exception as e:
            print(f"⚠️ 同源 trace meta 应用失败, 退回默认视角: {e}")

    def _sync_fov(self):
        """把视频的垂直 fovy 换算成 pyqtgraph 的水平 fov (随窗口尺寸变化必须重算)"""
        try:
            self.view.opts["fov"] = fov_h_from_fovy(self._cam_fovy,
                                                    self.view.width(), self.view.height())
            self.view.update()
        except Exception:
            pass

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._sync_fov()

    # ── 场景构建 ──
    def _build_scene(self):
        for it in self._gl_items.values():
            if isinstance(it, list):
                for x in it:
                    self.view.removeItem(x)
            else:
                self.view.removeItem(it)
        self._gl_items.clear()

        # 地面网格 (z=0, 覆盖整个工作区: 机器人 y=0 → 工作台 y≈0.6)
        gz = gl.GLGridItem()
        gz.setSize(1.1, 1.0)
        gz.setSpacing(0.05, 0.05)
        gz.translate(-0.05, 0.45, 0.0)
        self._gl_items["_grid"] = gz
        self.view.addItem(gz)

        # 坐标轴 (世界原点 = 机器人底座)
        ax = gl.GLAxisItem()
        ax.setSize(0.20, 0.20, 0.20)
        self._gl_items["_axis"] = ax
        self.view.addItem(ax)

        # 场景层 (静态几何: 台面 + 带孔盒 + 孔口; 插销/夹爪动态, 见 _update_frame)
        scene = []
        # 工作台面板
        table = gl.GLMeshItem(meshdata=_box_mesh(self._table_c, _TABLE_SIZE),
                              color=(0.16, 0.18, 0.22, 1.0), smooth=False, shader='shaded')
        self.view.addItem(table)
        scene.append(table)
        # 带孔盒 (红, 醒目 — 侧插目标件)
        box = gl.GLMeshItem(meshdata=_box_mesh(self._box_c, _BOX_SIZE),
                            color=(0.95, 0.22, 0.14, 1.0), smooth=False, shader='shaded')
        self.view.addItem(box)
        scene.append(box)
        # 孔口 (盒子 +X 面上的深色方口 = 插销侧插入口)
        mouth = gl.GLMeshItem(meshdata=_box_mesh(self._mouth + np.array([0.004, 0, 0]),
                                                 (0.012, 0.05, 0.05)),
                              color=(0.04, 0.03, 0.02, 1.0), smooth=False, shader=None)
        self.view.addItem(mouth)
        scene.append(mouth)
        # 插入终点标记 (goal, 半透明绿点线框)
        gv, ge = _bbox_lines(self._hole, (0.03, 0.05, 0.05))
        gpts = []
        for e in ge:
            gpts.append(gv[e[0]])
            gpts.append(gv[e[1]])
        goal = gl.GLLinePlotItem(pos=np.array(gpts), color=(0.20, 0.95, 0.55, 0.7),
                                 width=2, mode='lines')
        self.view.addItem(goal)
        scene.append(goal)
        self._gl_items["scene"] = scene

        # 🤖 Sawyer 机械臂 (2026-08-25 老倪: 形象渲染 — 底座+肩+肘+腕+夹爪)
        self._arm_base = _ARM_BASE.copy()   # metaworld 机器人底座 = 世界原点
        arm = []
        # 底座立柱 (竖直圆柱)
        arm_base = gl.GLMeshItem(meshdata=_cylinder_mesh(self._arm_base,
                                                         self._arm_base + [0, 0, _ARM_H_BASE],
                                                         0.055),
                                 color=(0.30, 0.32, 0.36, 1.0), smooth=True, shader='shaded')
        self.view.addItem(arm_base)
        arm.append(arm_base)
        # 肩/肘/腕关节球 + 上臂/前臂圆柱 (动态更新, 先占位)
        arm_upper = gl.GLMeshItem(meshdata=_cylinder_mesh([0, 0, 0], [0, 0, 0.001], 0.032),
                                  color=(0.85, 0.30, 0.18, 1.0), smooth=True, shader='shaded')
        self.view.addItem(arm_upper)
        arm.append(arm_upper)
        arm_fore = gl.GLMeshItem(meshdata=_cylinder_mesh([0, 0, 0], [0, 0, 0.001], 0.026),
                                 color=(0.85, 0.30, 0.18, 1.0), smooth=True, shader='shaded')
        self.view.addItem(arm_fore)
        arm.append(arm_fore)
        arm_shoulder = gl.GLMeshItem(meshdata=_sphere_mesh([0, 0, 0], 0.042),
                                     color=(0.40, 0.42, 0.46, 1.0), smooth=True, shader='shaded')
        self.view.addItem(arm_shoulder)
        arm.append(arm_shoulder)
        arm_elbow = gl.GLMeshItem(meshdata=_sphere_mesh([0, 0, 0], 0.034),
                                  color=(0.40, 0.42, 0.46, 1.0), smooth=True, shader='shaded')
        self.view.addItem(arm_elbow)
        arm.append(arm_elbow)
        arm_wrist = gl.GLMeshItem(meshdata=_sphere_mesh([0, 0, 0], 0.026),
                                  color=(0.40, 0.42, 0.46, 1.0), smooth=True, shader='shaded')
        self.view.addItem(arm_wrist)
        arm.append(arm_wrist)
        # 夹爪两瓣 (沿 Y 开合 — 插销是沿 X 的长条, 从 ±Y 两侧夹住; 青色纯色不被光照压暗)
        arm_jaw_l = gl.GLMeshItem(meshdata=_box_mesh([0, 0, 0], (0.05, 0.016, 0.05)),
                                  color=(0.20, 0.85, 0.90, 1.0), smooth=True, shader=None)
        self.view.addItem(arm_jaw_l)
        arm.append(arm_jaw_l)
        arm_jaw_r = gl.GLMeshItem(meshdata=_box_mesh([0, 0, 0], (0.05, 0.016, 0.05)),
                                  color=(0.20, 0.85, 0.90, 1.0), smooth=True, shader=None)
        self.view.addItem(arm_jaw_r)
        arm.append(arm_jaw_r)
        # 光模块 peg (金色插销 — 独立物体: 抓取前躺在台面, 抓取后随末端; 位置来自 tr["peg"])
        arm_peg = gl.GLMeshItem(meshdata=_box_mesh([0, 0, 0], _PEG_SIZE),
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

        # 状态估计 x̂: 紫线(最近 60 帧估计轨迹) + 当前帧估计位置大球
        #   2026-08-25 老倪「为什么显示一堆点」→ 原来是每帧一个散点(看不出是轨迹),
        #   改成连线 + 当前点大球, 一眼看出"卡尔曼估计出来的末端在哪、跟真实轨迹差多少"
        lat_line = gl.GLLinePlotItem(pos=np.zeros((2, 3)), color=(0.85, 0.45, 0.95, 0.9), width=3)
        self.view.addItem(lat_line)
        lat_now = gl.GLScatterPlotItem(pos=np.zeros((1, 3)), color=(0.95, 0.55, 1.0, 1.0), size=14)
        self.view.addItem(lat_now)
        self._gl_items["latent"] = [lat_line, lat_now]

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
        arm[self._arm_idx["upper"]].setMeshData(meshdata=_cylinder_mesh(ik["shoulder"], ik["elbow"], 0.032))
        arm[self._arm_idx["fore"]].setMeshData(meshdata=_cylinder_mesh(ik["elbow"], ik["wrist"], 0.026))
        arm[self._arm_idx["shoulder"]].setMeshData(meshdata=_sphere_mesh(ik["shoulder"], 0.042))
        arm[self._arm_idx["elbow"]].setMeshData(meshdata=_sphere_mesh(ik["elbow"], 0.034))
        arm[self._arm_idx["wrist"]].setMeshData(meshdata=_sphere_mesh(ik["wrist"], 0.026))
        # 🖐 夹爪开合 (2026-08-25 老倪: 插销是沿 X 的长条 → 夹爪从 ±Y 两侧夹住抓握点)
        #   张开 gap=0.048 (瓣在插销外侧) → 闭合 gap=0.024 (贴住插销 0.03 宽的两侧)
        g = float(tr["gripper"][i])
        gap = 0.024 + (1.0 - g) * 0.024
        jaw_dir = np.array([0.0, 1.0, 0.0])
        arm[self._arm_idx["jaw_l"]].setMeshData(
            meshdata=_box_mesh(ik["wrist"] + jaw_dir * gap, (0.05, 0.016, 0.05)))
        arm[self._arm_idx["jaw_r"]].setMeshData(
            meshdata=_box_mesh(ik["wrist"] - jaw_dir * gap, (0.05, 0.016, 0.05)))
        # 🔩 插销: 独立物体 — 抓取前躺台面, 抓取后随末端 (位置来自仿真 tr["peg"])
        #   老 tr 没有 "peg" 键 (旧仿真 peg=末端) → 回退到末端, 保持兼容
        peg_grasp = (np.asarray(tr["peg"][i], dtype=float)
                     if tr.get("peg") is not None and len(tr["peg"]) > i else x)
        arm[self._arm_idx["peg"]].setMeshData(
            meshdata=_box_mesh(peg_grasp + self._peg_center_off, _PEG_SIZE))

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

        # YOLO 检测框: hand/peg/hole 三个框 (真实 3D 坐标 — peg 用独立插销位置, hole 用孔口)
        boxes = [("hand", x, (0.07, 0.07, 0.06)),
                 ("peg", peg_grasp + self._peg_center_off, (0.21, 0.04, 0.04)),
                 ("hole", self._mouth, (0.05, 0.07, 0.07))]
        for cls, ctr, sz in boxes:
            v, edges = _bbox_lines(ctr, sz)
            # 线框: 每条边 2 顶点 → 12 条边拼成 24 点序列
            line_pts = []
            for e in edges:
                line_pts.append(v[e[0]])
                line_pts.append(v[e[1]])
            self._gl_items["yolo_" + cls].setData(pos=np.array(line_pts))

        # 状态估计 x̂ (latent = 位置3 + 预测接触力1): 紫线 = 最近 60 帧估计轨迹
        win = min(i + 1, 60)
        lat_pts = np.array([np.asarray(tr["latent_vec"][k], dtype=float)[:3]
                            for k in range(i - win + 1, i + 1)])
        if len(lat_pts) < 2:
            lat_pts = np.vstack([lat_pts, lat_pts])
        self._gl_items["latent"][0].setData(pos=lat_pts)
        self._gl_items["latent"][1].setData(pos=lat_pts[-1:])

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
        self.lbl_t.setText(f"t={t:.2f}s · 帧 {i}/{self._n - 1}\n阶段 {stage}\n数据源: {self._src}")
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
