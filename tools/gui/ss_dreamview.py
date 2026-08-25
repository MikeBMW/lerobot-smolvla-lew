# -*- coding: utf-8 -*-
"""
ss_dreamview.py — 🧭 状态空间 3D 分层视图 (参考百度 Apollo Dreamview, 2026-08-25 老倪)

在同一个 3D 空间 (与操作视频 gen_state_space_video.py 的物理世界坐标一致) 里,
叠加渲染状态空间仿真的所有处理层数据, 每层可独立开关 (Apollo Layer 风格):

  坐标世界: 工作台平面 + 孔位插座(红) + 光模块 peg(金) + 末端夹爪(蓝)
  处理层:
    🎯 YOLO 检测框  — hand/peg/hole 三个 3D 半透明立方体框
    📍 末端轨迹     — 末端历史 3D 轨迹线 (旧→新 渐亮)
    ⚡ 前馈加速器 — 绿色箭头 (快通道速度指令 u_ff)
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
from PyQt5.QtGui import QColor, QFont, QVector3D
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
_LABEL_PT = 13          # 3D 标签字号 (高分屏 236DPI, 太小看不见)
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


_U_REF = 0.35     # 箭头满格对应的速度 (m/s) — 实测 u_ff 模长范围 0.031~0.331 m/s
_L_MAX = 0.10     # 箭头满格长度 (m)
_L_MIN_FRAC = 0.22   # 最短也画满格的 22% (否则小速度只剩 2mm, 看着就是"一个点")


def _arrow(pos, action, scale=None, u_ref=_U_REF, l_max=_L_MAX):
    """由末端位置 pos + 动作向量 action(3D 速度指令 m/s) 生成箭头几何:
    返回 (line_pts 2x3, tip 箭头尖 3D, length 长度 m)
      方向 = action 归一化 (往哪走)
      长度 = clip(|u|/u_ref, 0.22, 1.0) × l_max  (速度大小 → 箭杆长短)

    🐛 2026-08-25 老倪「为什么是一个绿色圆点和一个绿色线段」根因: 原公式
    length = clip(|u|,0,1)×0.08m, 而真实 |u_ff| 只有 0.03~0.33 m/s →
    箭头只有 2.5~26mm 长, 近距时缩到 2mm ⇒ 看起来就剩箭头尖那个点。
    改成按 u_ref=0.35m/s 归一化 + 最短 22% 保底: 现在 22~100mm, 始终看得见方向。"""
    a = np.asarray(action[:3], dtype=float)
    mag = float(np.linalg.norm(a))
    if mag < 1e-9:
        return None, None, 0.0
    d = a / mag
    length = float(np.clip(mag / max(1e-6, u_ref), _L_MIN_FRAC, 1.0)) * l_max
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


def _cone_mesh(p_from, p_to, radius, cols=14):
    """锥形箭头头 (p_from→p_to 方向, 底半径 radius, 尖端在 p_to) —
    2026-08-25 老倪「线段表示速度, 那方向呢」: 原来只有线+散点看不出朝向, 加真箭头头。"""
    p1 = np.asarray(p_from, dtype=float)
    p2 = np.asarray(p_to, dtype=float)
    axis = p2 - p1
    length = float(np.linalg.norm(axis)) or 1e-6
    d = axis / length
    z = np.array([0.0, 0.0, 1.0])
    v = np.cross(z, d)
    s = float(np.linalg.norm(v))
    c = float(np.dot(z, d))
    if s < 1e-9:
        R = np.eye(3) if c > 0 else np.diag([1.0, 1.0, -1.0])
    else:
        K = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
        R = np.eye(3) + K + K @ K * ((1 - c) / (s * s))
    md = gl.MeshData.cylinder(rows=1, cols=cols, radius=[radius, 0.0], length=length)
    verts = md.vertexes() @ R.T + p1
    return gl.MeshData(vertexes=verts, faces=md.faces())


def _dir_words(vec):
    """把方向向量翻成人话 (老倪要的"方向"): 取主分量组合, 如 "右下"/"朝孔位/下降" """
    v = np.asarray(vec[:3], dtype=float)
    n = float(np.linalg.norm(v)) or 1.0
    u = v / n
    parts = []
    if abs(u[0]) > 0.25:
        parts.append("−X(朝孔位)" if u[0] < 0 else "+X(离孔位)")
    if abs(u[1]) > 0.25:
        parts.append("+Y(朝台面外)" if u[1] > 0 else "−Y(朝台面内)")
    if abs(u[2]) > 0.25:
        parts.append("↑抬升" if u[2] > 0 else "↓下压")
    return " ".join(parts) if parts else "几乎静止"


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
    "uff":     (0.20, 0.85, 0.35, 1.0),   # 绿  前馈加速器
    "ufb":     (0.35, 0.62, 1.00, 1.0),   # 蓝  反馈校正
    "ufuse":   (1.00, 0.78, 0.12, 1.0),   # 金黄 融合指令 (action 主图标)
    "ulimit":  (1.00, 0.30, 0.30, 1.0),   # 红  安全限幅
    "yolo_hand": (0.35, 0.65, 1.00, 0.55),
    "yolo_peg":  (0.00, 0.83, 0.66, 0.55),
    "yolo_hole": (1.00, 0.65, 0.00, 0.55),
}


class LabelOverlay(QWidget):
    """🏷 3D 画布上的透明文字标注层 (2026-08-25 老倪: "你要在旁边标出来")

    ⚠️ 为什么不用 pyqtgraph 的 GLTextItem: 它在 paint() 里 `QPainter(self.view())` 直接画
    控件表面, 本机 (Mesa 25.2 / GLViewWidget) 实测**完全不渲染** —— 清空文本前后屏幕像素
    差 0 px (tools/probe_text_labels.py 抓真实窗口验证)。改为自己叠一层透明 QWidget,
    用 project_world() 算屏幕坐标 + QPainter.drawText 画, 可控且抓图可验证。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setStyleSheet("background:transparent;")
        self._labels = []      # [(x_px, y_px, text, QColor, bold)]

    def set_labels(self, labels):
        self._labels = labels
        self.update()

    def paintEvent(self, ev):
        from PyQt5.QtGui import QPainter, QPen, QBrush
        if not self._labels:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        for x, y, text, col, bold in self._labels:
            f = QFont("Arial", 10, QFont.Bold if bold else QFont.Normal)
            p.setFont(f)
            fm = p.fontMetrics()
            w = fm.horizontalAdvance(text) + 10
            h = fm.height() + 4
            bx, by = int(x) + 8, int(y) - h // 2
            bx = max(2, min(bx, self.width() - w - 2))
            by = max(2, min(by, self.height() - h - 2))
            # 半透明深底 (深色画布上文字才看得清; 单色不刺眼 — 老倪不喜大面积彩色高亮)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(13, 17, 23, 205)))
            p.drawRoundedRect(bx, by, w, h, 4, 4)
            p.setPen(QPen(col))
            p.drawText(bx + 5, by + h - fm.descent() - 2, text)
            # 一条短引线连到目标点
            p.setPen(QPen(QColor(col.red(), col.green(), col.blue(), 150), 1))
            p.drawLine(int(x), int(y), bx, by + h // 2)
        p.end()


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
            ("scene",     "🌍 物理世界 (台面/插销/孔位/夹爪)", True,
             "画布节点「🌍 物理世界」的真实几何: 台面 / 带孔盒 / 插销 peg / Sawyer 臂+夹爪\n"
             "(含物体名字标注; 关掉它连机械臂和标注一起隐藏)"),
            ("yolo",      "🎯 YOLO 目标检测",           True,
             "画布节点「🎯 YOLO 目标检测」的输出: hand / peg / hole 三个 3D 检测框"),
            ("traj",      "🌍 物理世界 · 末端轨迹",      True,
             "「🌍 物理世界」每步实测的末端位置连成的历史轨迹 (metaworld MuJoCo 真值)"),
            ("uff",       "⚡ 前馈加速器",              True,
             "快通道 (前馈加速器 = 原左脑 MLP 的等效控制律) 每步给出的**速度指令** (m/s):\n"
             "  绿线 = 建议往哪走 (方向), 线越长 = 建议速度越大 (满格 0.35 m/s = 10cm 长)\n"
             "  绿点 = 箭杆末端(箭头尖) = 照这个建议走一步会到哪\n"
             "调度器只采纳 30% (接触/插入阶段 85%) → 和金黄「融合指令 u」比长短就知道被压了多少"),
            ("ufb",       "🧪 状态校正器 · 残差方向",    False,
             "画布节点「🧪 状态校正器」算出的残差 r = z_k − 先验预测, 这里画 0.5×r 作为校正方向\n"
             "(实测 0.005 m/s 量级): 蓝箭头 = 观测比预测偏了哪边 → 动作调制器据此把前馈拉回来"),
            ("ufuse",     "🧭 动作调制器 (下发 action)", True,
             "动作调制器 (八阶段状态机 + 否决权) 的最终输出 = 真正下发给执行器的动作:\n"
             "  u = 0.3·u_ff + 0.7·u_fb (接近/对位/下降/抬起/转移)\n"
             "  u = 0.85·u_ff + 0.15·u_fb (抓取/插入 — 力控阶段前馈推力主导)\n"
             "  残差超阈值 → 否决, u 直接归零 (强制减速重试)"),
            ("ulimit",    "🛡 安全执行边界 (饱和限幅)",  False,
             "安全层饱和限幅后的指令 (上限 0.6 m/s)。与融合指令重合 = 没触发限幅;\n"
             "两者分叉 = 安全层出手削掉了超速部分"),
            ("latent",    "🔮 自适应状态估计器 · x̂",     False,
             "慢通道 AdaptiveStateEstimator 的后验位置估计 x̂ₖ = 预测 + K·(观测−预测);\n"
             "紫线 = 最近 60 帧估计轨迹, 大球 = 当前帧估计位置。\n"
             "与蓝色真实末端轨迹的偏离量 = 残差 (接触/扰动来源), 调度器据此判接触概率"),
            ("contact",   "🧪 状态校正器 · 接触概率",    True,
             "画布节点「🧪 状态校正器」的第二路输出: 接触概率 = σ(8×|残差|)\n"
             "橙色热力球画在末端: 球越大越亮 = 接触概率越高 (插入顶到孔沿时最明显);\n"
             "残差的力觉分量来自 MuJoCo 真实环境接触力 (夹持力单独一路不计入)"),
            ("grid",      "▦ 地面网格",                 True,  "z=0 台面参考网格 (5cm 一格)"),
            ("axis",      "🧭 坐标轴 XYZ",              False,
             "世界坐标轴指示器 (pyqtgraph GLAxisItem), 画在原点 = 机器人底座:\n"
             "  绿 = Z 轴 (垂直向上)   黄 = Y 轴 (指向工作台)   蓝 = X 轴\n"
             "⚠️ 原点在画面外时看不到 (实测: 自动取景/俯视档 0px, 「🎥 视频同框」档可见)"),
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

        # 📟 实时数值面板 (2026-08-25 老倪: "不知道啥意思" → 画面旁边直接给数字)
        self.lbl_num = QLabel("—")
        self.lbl_num.setStyleSheet(
            "color:#c9d1d9; font-size:12px; font-family:Consolas,monospace; "
            "background:#0d1117; border:1px solid #30363d; border-radius:4px; padding:6px;")
        self.lbl_num.setMinimumHeight(210)
        self.lbl_num.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        pl.addWidget(self.lbl_num)

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
        self._overlay = LabelOverlay(self.view)     # 🏷 文字标注层 (贴在 3D 画布上)
        self._overlay.setGeometry(0, 0, self.view.width(), self.view.height())
        self._overlay.show()
        self.view.installEventFilter(self)
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

        # 🔍 视角三档 (默认自动取景 — 1:1 复刻视频机位时场景只占画面 3%, 看不清)
        for _txt, _mode, _tip in (("🔍 自动取景", "fit", "朝向与操作视频一致, 距离自动收紧到刚好装下全场景 (推荐)"),
                                  ("🎥 视频同框", "video", "与操作视频逐像素同机位 (远景, 用于和视频对比)"),
                                  ("⬇ 俯视", "top", "正上方俯视 (看水平对位)")):
            b = QPushButton(_txt)
            b.setToolTip(_tip)
            b.setStyleSheet(
                "QPushButton{background:#21262d; color:#c9d1d9; border:1px solid #30363d;"
                "border-radius:4px; padding:5px 10px; font-size:12px;}"
                "QPushButton:hover{border-color:#58a6ff; color:#58a6ff;}")
            b.clicked.connect(lambda _=False, mm=_mode: self._fit_view(mm))
            ctrl.addWidget(b)
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
        self._fit_view("fit")      # 默认自动取景 (视频同框太远, 物体只有几十像素)
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
            # 记下"与视频 1:1 同框"的机位, 供视角切换用
            self._cam_video = dict(center=center.copy(), dist=max(0.3, t),
                                   fwd=cf.copy(), right=cr.copy(), up=cu.copy())
            self.setWindowTitle("🧭 状态空间 3D 分层视图 — 与操作视频同源 (metaworld corner2 视角)")
        except Exception as e:
            print(f"⚠️ 同源 trace meta 应用失败, 退回默认视角: {e}")

    # ── 取景 (2026-08-25 老倪: "还是一堆点, 不知道啥意思") ──
    #   实测: 严格 1:1 复刻视频机位时 (距离 1.735m/竖直fov60), 926x766 画布上
    #   96.8% 是空背景, 插销只有 51px、轨迹 3px → 每个东西都成了"小点", 看不懂。
    #   → 默认改「自动取景」: **朝向保持与视频完全一致**, 只把 center/distance 收紧到
    #     刚好装下 (末端轨迹 ∪ 插销轨迹 ∪ 孔口 ∪ 台面) 的包围盒 + 12% 余量。
    #     要逐像素对比视频时用「视频同框」档切回去。
    def _fit_view(self, mode=None):
        mode = mode or getattr(self, "_view_mode", "fit")
        self._view_mode = mode
        cam = getattr(self, "_cam_video", None)
        tr = self.tr or {}
        try:
            if mode == "video" and cam:
                self.view.setCameraPosition(pos=QVector3D(*cam["center"].tolist()),
                                            distance=cam["dist"],
                                            rotation=camera_quaternion(cam["fwd"], cam["right"], cam["up"]))
                self._sync_fov()
                return
            pts = []
            for k in ("x", "peg", "peg_head"):
                if tr.get(k) is not None and len(tr[k]):
                    pts.append(np.asarray(tr[k], dtype=float))
            pts.append(np.asarray([self._mouth, self._hole], dtype=float))
            P = np.vstack(pts)
            lo, hi = P.min(axis=0), P.max(axis=0)
            ctr = (lo + hi) / 2.0
            radius = float(np.linalg.norm(hi - lo)) / 2.0 + 0.05
            if mode == "top":       # 俯视档 (正上方看)
                self.view.opts["rotationMethod"] = "euler"
                self.view.setCameraPosition(pos=QVector3D(*ctr.tolist()),
                                            distance=max(0.35, radius * 2.6),
                                            elevation=88, azimuth=270)
                self.view.opts["fov"] = 60.0
                self.view.update()
                self._refine_distance(P, target=0.72)     # 俯视也按投影收紧距离
                return
            # fit 档: 朝向沿用视频机位, 距离按包围盒外接球 + fov 求
            fwd = cam["fwd"] if cam else np.array([-0.746, 0.458, -0.484])
            right = cam["right"] if cam else np.array([0.55, 0.833, -0.058])
            up = cam["up"] if cam else np.array([-0.376, 0.310, 0.873])
            self._sync_fov()
            self.view.opts["rotationMethod"] = "quaternion"
            self._fit_camera_to_points(P, ctr, radius, fwd, right, up)
        except Exception as e:
            print(f"⚠️ 取景失败: {e}")

    def _fit_camera_to_points(self, P, ctr, radius, fwd, right, up, target=0.72, iters=14):
        """按**实际投影**迭代取景 (朝向不动, 只调 center/distance):
        球形包围盒对扁平作业区太保守 (实测只占屏 44%) → 改成每轮把点云投影出来,
        按屏幕占比缩放距离 + 把点云包围框居中, 收敛到占屏 ≈ target。"""
        import math
        pts = np.asarray(P, dtype=float)
        if len(pts) > 240:
            pts = pts[:: max(1, len(pts) // 240)]
        center = np.asarray(ctr, dtype=float).copy()
        dist = max(0.25, radius * 2.2)
        for _ in range(iters):
            self.view.setCameraPosition(pos=QVector3D(*center.tolist()), distance=float(dist),
                                        rotation=camera_quaternion(fwd, right, up))
            s = [project_world(self.view, p) for p in pts]
            s = np.asarray([v for v in s if v is not None], dtype=float)
            if len(s) < 3:
                break
            xmin, ymin = s.min(axis=0)
            xmax, ymax = s.max(axis=0)
            spread = max(xmax - xmin, ymax - ymin)
            # ① 居中: 把投影框中心拉到画面中心 (沿相机 right/up 平移世界 center)
            fov_h = math.radians(float(self.view.opts.get("fov", 60.0)))
            w, h = max(1, self.view.width()), max(1, self.view.height())
            half_x = math.tan(fov_h / 2.0)
            half_y = half_x * h / w
            dx = ((xmin + xmax) / 2.0) - 0.5
            dy = ((ymin + ymax) / 2.0) - 0.5
            center = center + right * (dx * 2.0 * half_x * dist) - up * (dy * 2.0 * half_y * dist)
            # ② 缩放: 占屏 → target
            if spread > 1e-4:
                dist *= float(np.clip(spread / target, 0.55, 1.8))
            dist = float(np.clip(dist, 0.18, 6.0))
            if abs(spread - target) < 0.03 and abs(dx) < 0.01 and abs(dy) < 0.01:
                break
        self.view.update()

    def _refine_distance(self, P, target=0.72, iters=10):
        """只调距离不动朝向 (俯视档用): 把点云投影占屏收敛到 target"""
        pts = np.asarray(P, dtype=float)
        if len(pts) > 240:
            pts = pts[:: max(1, len(pts) // 240)]
        for _ in range(iters):
            s = [project_world(self.view, p) for p in pts]
            s = np.asarray([v for v in s if v is not None], dtype=float)
            if len(s) < 3:
                return
            spread = max(s[:, 0].max() - s[:, 0].min(), s[:, 1].max() - s[:, 1].min())
            if abs(spread - target) < 0.03:
                break
            self.view.opts["distance"] = float(np.clip(
                self.view.opts["distance"] * float(np.clip(spread / target, 0.6, 1.7)), 0.18, 6.0))
            self.view.update()

    def _sync_fov(self):
        """把视频的垂直 fovy 换算成 pyqtgraph 的水平 fov (随窗口尺寸变化必须重算)"""
        try:
            self.view.opts["fov"] = fov_h_from_fovy(self._cam_fovy,
                                                    self.view.width(), self.view.height())
            self.view.update()
        except Exception:
            pass

    def eventFilter(self, obj, ev):
        """3D 画布尺寸变化 → 标注层跟着变 (覆盖层必须与画布严格同尺寸, 否则坐标错位)"""
        try:
            if obj is self.view and ev.type() == ev.Resize:
                self._overlay.setGeometry(0, 0, self.view.width(), self.view.height())
        except Exception:
            pass
        return super().eventFilter(obj, ev)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._sync_fov()
        try:
            self._overlay.setGeometry(0, 0, self.view.width(), self.view.height())
        except Exception:
            pass

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
        self._gl_items["grid"] = gz          # 受「▦ 地面网格」图层开关控制
        self.view.addItem(gz)

        # 坐标轴 (世界原点 = 机器人底座)
        # 坐标轴 (pyqtgraph GLAxisItem 固定配色: 绿=Z 黄=Y 蓝=X, 见源码 updateLines)
        # 2026-08-25 老倪: 原来叫 "_axis" 不在图层字典里 → 全取消勾选后仍留一段绿线+黄线,
        #   看不出是什么。现在纳入图层 (默认关) + 轴端加 X/Y/Z 文字标签。
        ax = gl.GLAxisItem()
        ax.setSize(0.20, 0.20, 0.20)
        self.view.addItem(ax)
        self._gl_items["axis"] = [ax]      # X/Y/Z 字样由 LabelOverlay 画

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
        # 轨迹线 — ⚠️ 2026-08-25 实测: 末端轨迹恰好走在机械臂/夹爪实体位置, 默认深度测试下
        #   被完全挡住 (画面里只剩 5 个像素) → 数据层统一 setGLOptions('additive')
        #   穿透遮挡叠加显示 (Apollo Dreamview 覆盖层做法), 线宽 2→3.5
        traj = gl.GLLinePlotItem(pos=np.zeros((2, 3)), color=(0.35, 0.65, 1.0, 1.0), width=3.5)
        traj.setGLOptions("additive")
        self.view.addItem(traj)
        self._gl_items["traj"] = traj

        # 箭头线 (4 层动作)
        for key in ("uff", "ufb", "ufuse", "ulimit"):
            col = _LAYER_COLORS[key]
            ln = gl.GLLinePlotItem(pos=np.zeros((2, 3)), color=col, width=(7 if key == "ufuse" else 3.5))
            ln.setGLOptions("additive")          # 动作箭头穿透遮挡 (否则被机械臂挡住)
            self.view.addItem(ln)
            self._gl_items[key + "_line"] = ln
            # 箭头头 (小锥体 / 目标点球)
            tip = gl.GLScatterPlotItem(pos=np.zeros((1, 3)), color=col,
                                       size=(16 if key == "ufuse" else 10))
            tip.setGLOptions("additive")
            self.view.addItem(tip)
            self._gl_items[key + "_tip"] = tip
            # 🔺 锥形箭头头 (方向) + 🏷 旁边文字标注 (名称/速度/方向) — 2026-08-25 老倪要求
            head = gl.GLMeshItem(meshdata=_cone_mesh([0, 0, 0], [0, 0, 0.001], 0.004),
                                 color=col, smooth=True, shader=None)
            head.setGLOptions("additive")
            self.view.addItem(head)
            self._gl_items[key + "_head"] = head
            # (箭头文字标注由 LabelOverlay 自绘层负责 — GLTextItem 本机不渲染)

        # 融合指令目标点大球 (action 主图标 — 明显醒目)
        fuse_sphere = gl.GLScatterPlotItem(pos=np.zeros((1, 3)), color=_LAYER_COLORS["ufuse"], size=18)
        self.view.addItem(fuse_sphere)
        self._gl_items["ufuse_sphere"] = fuse_sphere

        # YOLO 检测框 (3 个立方体线框)
        yolo = []
        for cls, col in (("hand", _LAYER_COLORS["yolo_hand"]),
                         ("peg", _LAYER_COLORS["yolo_peg"]),
                         ("hole", _LAYER_COLORS["yolo_hole"])):
            ln = gl.GLLinePlotItem(pos=np.zeros((12, 3)), color=col, width=2.5, mode='lines')
            ln.setGLOptions("additive")
            self.view.addItem(ln)
            self._gl_items["yolo_" + cls] = ln
            yolo.append(ln)
        self._gl_items["yolo"] = yolo

        # 状态估计 x̂: 紫线(最近 60 帧估计轨迹) + 当前帧估计位置大球
        #   2026-08-25 老倪「为什么显示一堆点」→ 原来是每帧一个散点(看不出是轨迹),
        #   改成连线 + 当前点大球, 一眼看出"卡尔曼估计出来的末端在哪、跟真实轨迹差多少"
        lat_line = gl.GLLinePlotItem(pos=np.zeros((2, 3)), color=(0.85, 0.45, 0.95, 0.95), width=3.5)
        lat_line.setGLOptions("additive")
        self.view.addItem(lat_line)
        lat_now = gl.GLScatterPlotItem(pos=np.zeros((1, 3)), color=(0.95, 0.55, 1.0, 1.0), size=16)
        lat_now.setGLOptions("additive")
        self.view.addItem(lat_now)
        self._gl_items["latent"] = [lat_line, lat_now]

        # 接触热力球
        contact = gl.GLScatterPlotItem(pos=np.zeros((1, 3)), color=(1.0, 0.4, 0.0, 1.0), size=12)
        contact.setGLOptions("additive")
        self.view.addItem(contact)
        self._gl_items["contact"] = contact

        # 🏷 文字标注统一走 LabelOverlay 自绘层 (GLTextItem 在本机 Mesa 下不渲染, 已弃用)

        # 应用当前图层开关状态
        for key, on in self._layer_on.items():
            self._apply_layer_visibility(key, on)

    def _apply_layer_visibility(self, key, on):
        """图层开关 → GL 元素可见性。
        🐛 2026-08-25 老倪「所有选项都取消了, 屏幕还有一小段绿线和黄线」根因:
        四层动作箭头存的 key 是 `<key>_line` / `<key>_tip` (还有 ufuse_sphere),
        而图层 key ("uff"/"ufb"/"ufuse"/"ulimit") 本身不在 _gl_items 里 →
        原实现 get(key) 拿到 None 直接 return, **勾选框点了完全没作用**;
        残留的绿线 = 前馈 u_ff 箭头, 黄线 = 融合指令 u 箭头+大球 (不是坐标轴)。
        另: 3D 文字标签 _labels 也不受任何图层控制 → 并入 scene 联动。"""
        targets = []
        it0 = self._gl_items.get(key)
        if it0 is not None:
            targets += it0 if isinstance(it0, list) else [it0]
        # 动作箭头族: <key>_line / <key>_tip (+ ufuse 的目标点大球)
        for suf in ("_line", "_tip", "_head"):
            sub = self._gl_items.get(key + suf)
            if sub is not None:
                targets += sub if isinstance(sub, list) else [sub]
        if key == "ufuse":
            sph = self._gl_items.get("ufuse_sphere")
            if sph is not None:
                targets.append(sph)
        # 场景层联动: 机械臂 + 3D 文字标签
        if key == "scene":
            for extra in ("arm", "_labels"):
                sub = self._gl_items.get(extra)
                if sub is not None:
                    targets += sub if isinstance(sub, list) else [sub]
        for it in targets:
            try:
                it.setVisible(on)
            except Exception:
                pass
        if not targets:
            return

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

        # 动作箭头 (4 层): 杆 + 锥形箭头头(方向) + 旁边文字标注(名称/速度/方向)
        _NAMES = {"uff": "⚡前馈加速器", "ufb": "🧪状态校正器·残差",
                  "ufuse": "🧭动作调制器", "ulimit": "🛡安全执行边界"}
        for key in ("uff", "ufb", "ufuse", "ulimit"):
            a = np.asarray(tr[self._vec_key(key)][i], dtype=float)
            mag = float(np.linalg.norm(a[:3]))
            pts, tip, ln = _arrow(x, a)
            head_it = self._gl_items.get(key + "_head")
            if pts is not None:
                self._gl_items[key + "_line"].setData(pos=pts)
                self._gl_items[key + "_tip"].setData(pos=np.array([tip]))
                d = (tip - np.asarray(x, dtype=float))
                dn = d / (np.linalg.norm(d) or 1.0)
                if head_it is not None:      # 锥头: 占箭杆末段 28%, 底半径随杆长
                    hl = max(0.008, ln * 0.28)
                    head_it.setMeshData(meshdata=_cone_mesh(tip - dn * hl, tip, max(0.004, hl * 0.42)))
            else:
                self._gl_items[key + "_line"].setData(pos=np.array([x[:3], x[:3]]))
                self._gl_items[key + "_tip"].setData(pos=np.array([x[:3]]))
                if head_it is not None:
                    head_it.setMeshData(meshdata=_cone_mesh(x, x + np.array([0, 0, 0.001]), 0.002))

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
        win = min(i + 1, 30)      # 60→30 帧: 观测噪声下估计轨迹本就抖, 窗口太长视觉更乱
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

        # 🏷 文字标注 (自绘覆盖层 — GLTextItem 在本机不渲染, 见 LabelOverlay 说明)
        try:
            _NAMES2 = {"uff": "⚡前馈加速器", "ufb": "🧪状态校正器·残差",
                       "ufuse": "🧭动作调制器", "ulimit": "🛡安全执行边界"}
            ovl = []
            def _add(world_p, text, rgba, bold=True):
                s = project_world(self.view, np.asarray(world_p, dtype=float))
                if s is None or not (-0.2 <= s[0] <= 1.2 and -0.2 <= s[1] <= 1.2):
                    return
                ovl.append((s[0] * self.view.width(), s[1] * self.view.height(), text,
                            QColor(int(rgba[0] * 255), int(rgba[1] * 255), int(rgba[2] * 255)), bold))
            if self._layer_on.get("scene", True):
                _add(np.asarray(x) + [0, 0, 0.03], "末端 hand", (0.55, 0.78, 1.0))
                _add(np.asarray(peg_grasp) + [0, 0, 0.03], "插销 peg", (1.0, 0.82, 0.25))
                _add(self._mouth + np.array([0, 0, 0.05]), "孔口 hole", (1.0, 0.45, 0.35))
                _add(self._hole + np.array([0, 0, -0.05]), "插入终点 goal", (0.35, 0.95, 0.60))
            if self._layer_on.get("latent", False):
                _add(np.asarray(lat_pts[-1]) + [0, 0, 0.02], "状态估计 x̂", (0.90, 0.60, 1.0))
            if self._layer_on.get("axis", False):
                for _t, _p, _c in (("Z↑", (0, 0, 0.21), (0.30, 1.0, 0.30)),
                                   ("Y", (0, 0.21, 0), (1.0, 1.0, 0.35)),
                                   ("X", (0.21, 0, 0), (0.45, 0.55, 1.0))):
                    _add(_p, _t, _c)
            # 四层动作: 箭尖旁标 名称 + 速度 + 方向
            for _k in ("uff", "ufb", "ufuse", "ulimit"):
                if not self._layer_on.get(_k, False):
                    continue
                _a = np.asarray(tr[self._vec_key(_k)][i], dtype=float)
                _mag = float(np.linalg.norm(_a[:3]))
                _pts, _tip, _ = _arrow(x, _a)
                if _tip is None:
                    continue
                _c = _LAYER_COLORS[_k]
                _add(_tip, f"{_NAMES2[_k]} {_mag:.3f} m/s  {_dir_words(_a)}", _c)
            self._overlay.set_labels(ovl)
        except Exception as _e:
            print(f"⚠️ 标注层更新失败: {_e}")

        # 📟 实时数值面板 (每帧滚动 — 老倪: 运行后数据须实时动态滚动, 不要一次性静态填充)
        t = tr["t"][i]
        stage = tr["stage"][i].replace("阶段 ", "")
        def _f(v, n=3):
            return f"{float(v):+.{n}f}"
        peg_h = (np.asarray(tr["peg_head"][i], dtype=float)
                 if tr.get("peg_head") is not None and len(tr["peg_head"]) > i else peg_grasp)
        res = float(np.linalg.norm(np.asarray(tr["residual_vec"][i], dtype=float)))
        cp = float(tr["contact_p"][i])
        fenv = float(tr["force"][i]) if tr.get("force") is not None else 0.0
        fg = float(tr["force_grasp"][i]) if tr.get("force_grasp") is not None else float("nan")
        lat3 = np.asarray(lat_pts[-1], dtype=float)
        err = float(np.linalg.norm(lat3 - np.asarray(x, dtype=float))) * 1000
        # x̂ 逐步抖动 (最近 30 帧平均步长) — 量化"乱"的程度, 观测噪声 5mm 时约 1mm/步
        jit = (float(np.linalg.norm(np.diff(lat_pts, axis=0), axis=1).mean()) * 1000
               if len(lat_pts) > 2 else 0.0)
        u_ff_m = float(np.linalg.norm(np.asarray(tr["u_ff_vec"][i], dtype=float)[:3]))
        u_fu_m = float(np.linalg.norm(np.asarray(tr["u_fuse_vec"][i], dtype=float)[:3]))
        u_li_m = float(np.linalg.norm(np.asarray(tr["u_limit_vec"][i], dtype=float)[:3]))
        d_ph = float(np.linalg.norm(peg_h[:2] - self._mouth[:2]))
        self.lbl_num.setText(
            f"阶段    {stage}\n"
            f"t       {t:6.2f}s   帧 {i}/{self._n - 1}\n"
            f"────────────────────\n"
            f"末端    {_f(x[0])} {_f(x[1])} {_f(x[2])}\n"
            f"插销    {_f(peg_grasp[0])} {_f(peg_grasp[1])} {_f(peg_grasp[2])}\n"
            f"销头    {_f(peg_h[0])} {_f(peg_h[1])} {_f(peg_h[2])}\n"
            f"估计x̂   {_f(lat3[0])} {_f(lat3[1])} {_f(lat3[2])}\n"
            f"x̂−末端  {err:6.1f} mm   抖动 {jit:4.2f} mm/步\n"
            f"────────────────────\n"
            f"夹爪    {float(tr['gripper'][i]):5.2f}  (1=闭合)\n"
            f"销头→孔 {d_ph * 1000:6.1f} mm\n"
            f"环境接触{fenv:6.3f}   夹持{fg:5.3f}\n"
            f"状态校正器 残差{res:6.4f} 接触概率{cp:5.2f}\n"
            f"────────────────────\n"
            f"前馈加速器  {u_ff_m:5.3f} m/s\n"
            f"动作调制器  {u_fu_m:5.3f} m/s\n"
            f"安全边界    {u_li_m:5.3f} m/s")
        self.lbl_t.setText(f"数据源: {self._src}")
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
