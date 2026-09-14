"""🛩 飞行 (Flight) — 标架转换模块: 统一 Frenet / 端口任务坐标系 / 全局笛卡尔

设计依据 (老倪 09-12):
  · Frenet 是**坐标表示** (沿参考线 s, 横向 d); 增量是**控制方式** (Δs/Δd), 两者不同维度
  · 端口任务坐标系增量 = Frenet 的**直线特例** (κ=0):
        Δs = Δz (沿插入轴),  Δd_x = Δx,  Δd_y = Δy  (端面横向),  Δroll (绕轴键位)
  · 自由段(弯路径) → Bishop/Frenet;  插入段 → 端口系增量 + 力控
  · 统一形式: u = (Δs, Δd₁, Δd₂, Δroll) 在**某个标架**下 → 转到笛卡尔速度/位姿

三个标架 (mode):
  "world"  : 全局笛卡尔增量 (ΔX,ΔY,ΔZ,Δroll)   — 自由空间接近 / 视觉伺服
  "port"   : 端口任务坐标系增量 (Δz,Δx,Δy,Δroll) — 直线插拔 (最实用, Frenet 直线特例)
  "frenet" : 曲线参考线 (Δs,Δd₁,Δd₂,Δroll)     — 弯曲路径 (自由段/管道)

用法:
    fl = Flight(port_origin=P0, port_axis=z_hat, approach=0.12)
    u_cart = fl.to_world((ds, dd1, dd2, droll))        # 标架动作 → 世界系增量
    u_port = fl.to_port(u_cart)                        # 世界系 → 端口系
    fl.set_path(control_points)                        # 自由段弯曲参考线 (Bishop)
"""
from __future__ import annotations

import numpy as np

# ── 小工具 ────────────────────────────────────────────────────────────────
_EPS = 1e-9


def _unit(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float64).reshape(3)
    n = float(np.linalg.norm(v))
    return v / n if n > _EPS else np.array([0.0, 0.0, 1.0])


def _rot_axis(axis: np.ndarray, ang: float) -> np.ndarray:
    """Rodrigues: 绕任意单位轴 axis 转 ang (rad) → 3x3"""
    a = _unit(axis)
    K = np.array([[0.0, -a[2], a[1]], [a[2], 0.0, -a[0]], [-a[1], a[0], 0.0]])
    return np.eye(3) + np.sin(ang) * K + (1.0 - np.cos(ang)) * (K @ K)


def _frame_from_axis(z: np.ndarray, ref: np.ndarray | None = None) -> np.ndarray:
    """给定 z 轴 (单位), 构造正交标架 R = [x, y, z] (列).

    ref 提供"上"参考以消除 roll 自由度; 缺省取世界 Z 或 X.
    """
    z = _unit(z)
    if ref is None:
        ref = np.array([0.0, 0.0, 1.0])
        if abs(float(np.dot(z, ref))) > 0.95:      # z 与世界 Z 近平行 → 换参考
            ref = np.array([1.0, 0.0, 0.0])
    x = np.cross(ref, z)
    if float(np.linalg.norm(x)) < 1e-6:
        x = np.cross(np.array([0.0, 1.0, 0.0]), z)
    x = _unit(x)
    y = _unit(np.cross(z, x))
    return np.column_stack([x, y, z])


# ── Bishop (旋转最小化) 标架沿曲线 ────────────────────────────────────────
def bishop_frames(points: np.ndarray) -> np.ndarray:
    """沿折线控制点生成 Bishop 标架序列 (无 roll 漂移).

    points: [N,3]  → 返回 [N,3,3] (每点的 [x,y,z] 列向量)
    """
    P = np.asarray(points, dtype=np.float64)
    if P.ndim != 2 or P.shape[1] != 3 or len(P) < 2:
        raise ValueError("bishop_frames 需要 [N>=2, 3] 的控制点")
    seg = np.diff(P, axis=0)
    T = np.array([_unit(s) for s in seg])          # 切线
    # 初始法向: 任取与 T0 正交
    ref = np.array([1.0, 0.0, 0.0])
    if abs(float(np.dot(T[0], ref))) > 0.9:
        ref = np.array([0.0, 1.0, 0.0])
    n0 = _unit(ref - np.dot(ref, T[0]) * T[0])
    Ns = [n0]
    for i in range(1, len(T)):                     # 平行移动 (remove twist)
        v = Ns[-1] - np.dot(Ns[-1], T[i]) * T[i]
        Ns.append(_unit(v))
    out = []
    for i in range(len(T)):
        x = _unit(np.cross(Ns[i], T[i]))
        out.append(np.column_stack([x, Ns[i], T[i]]))
    out.append(out[-1])                            # 末点沿用末段标架
    return np.array(out)


def frenet_curvature_torsion(points: np.ndarray, s: np.ndarray | None = None):
    """数值曲率 κ / 挠率 τ (用于判断"直线特例"是否成立)."""
    P = np.asarray(points, dtype=np.float64)
    d1 = np.gradient(P, axis=0)
    d2 = np.gradient(d1, axis=0)
    d3 = np.gradient(d2, axis=0)
    c = np.cross(d1, d2)
    nc = np.linalg.norm(c, axis=1)
    sp = np.linalg.norm(d1, axis=1) + _EPS
    kappa = nc / (sp ** 3)
    tau = np.einsum("ij,ij->i", c, d3) / (nc ** 2 + _EPS)
    return kappa, tau


# ── 核心: 飞行 ────────────────────────────────────────────────────────────
class Flight:
    """🛩 标架转换器 — 光模块"沿一条路向前、左右微调".

    参数
      port_origin : 端口(孔)入口点, 世界系 [3]
      port_axis   : 插入轴方向 (指向孔内), 世界系 [3] (会归一化)
      port_up     : 端口面内"上"参考 (决定 x/y 朝向与 roll 零点), [3] 可选
      approach    : 自由段长度 (端口前多远开始插入段), m
      max_step    : 单步增量限幅 (每轴), m
      max_roll    : 单步 roll 限幅, rad
    """

    def __init__(self, port_origin, port_axis=(1.0, 0.0, 0.0), port_up=None,
                 approach: float = 0.12, max_step: float = 0.02,
                 max_roll: float = 0.10):
        self.p0 = np.asarray(port_origin, dtype=np.float64).reshape(3)
        self.z = _unit(port_axis)
        self.R_port = _frame_from_axis(self.z, None if port_up is None else np.asarray(port_up, float))
        self.approach = float(approach)
        self.max_step = float(max_step)
        self.max_roll = float(max_roll)
        self._path = None            # 自由段控制点
        self._frames = None          # bishop 标架
        self._mode = "port"          # 当前模式

    # ── 标架选择 / 自动切换 ──
    def mode_for(self, hand_pos) -> str:
        """按手(夹爪)位置自动选标架: 端口轴向距离 > approach → 自由段(world/frenet), 否则 port."""
        h = np.asarray(hand_pos, dtype=np.float64).reshape(3)
        along = float(np.dot(h - self.p0, self.z))
        return "port" if along <= self.approach else ("frenet" if self._path is not None else "world")

    def set_path(self, control_points):
        """设置自由段弯曲参考线 (Bishop 标架)."""
        self._path = np.asarray(control_points, dtype=np.float64).reshape(-1, 3)
        self._frames = bishop_frames(self._path)
        return self

    # ── 变换 ──
    def port_R(self, roll: float = 0.0) -> np.ndarray:
        """端口系旋转 (含 roll 绕轴)."""
        return self.R_port @ _rot_axis(np.array([0.0, 0.0, 1.0]), float(roll))

    def to_world(self, u_frame, mode: str | None = None, roll: float = 0.0) -> np.ndarray:
        """标架动作 (Δs, Δd1, Δd2, Δroll) → 世界系增量 [3] + roll.

        返回 [ΔX, ΔY, ΔZ, Δroll] (位置增量 + 绕轴角增量).
        """
        u = np.asarray(u_frame, dtype=np.float64).reshape(-1)
        if u.size == 3:
            u = np.concatenate([u, [0.0]])
        ds, d1, d2, droll = [float(v) for v in u[:4]]
        m = mode or self._mode

        if m == "port":
            R = self.port_R(roll)
            dxyz = R @ np.array([d1, d2, ds])          # 端口系 (x,y←横向, z←沿轴)
        elif m == "world":
            dxyz = np.array([ds, d1, d2])
            droll = droll if abs(droll) > 0 else float(u[3])
        elif m == "frenet":
            if self._frames is None:
                raise ValueError("frenet 模式需先 set_path()")
            R = self._frames[0]                       # (简化) 起点标架
            dxyz = R @ np.array([d1, d2, ds])
        else:
            raise ValueError(f"未知标架: {m}")
        # 限幅 (精细操作必须高频小步)
        n = float(np.linalg.norm(dxyz))
        if n > self.max_step:
            dxyz = dxyz * (self.max_step / (n + _EPS))
        droll = float(np.clip(droll, -self.max_roll, self.max_roll))
        return np.concatenate([dxyz, [droll]])

    def to_port(self, u_world, hand_pos=None) -> np.ndarray:
        """世界系增量 → 端口系 (Δs,Δd1,Δd2,Δroll)."""
        u = np.asarray(u_world, dtype=np.float64).reshape(-1)
        dxyz = u[:3]
        droll = float(u[3]) if u.size > 3 else 0.0
        R = self.R_port.T
        loc = R @ dxyz
        return np.array([loc[2], loc[0], loc[1], droll])   # (s, d1, d2, roll)

    def distance_to_port(self, hand_pos) -> dict:
        """到端口的分解距离: 沿轴(剩余前进) + 面内横向误差 + 角向."""
        h = np.asarray(hand_pos, dtype=np.float64).reshape(3)
        rel = h - self.p0
        along = float(np.dot(rel, self.z))            # >0 = 已在孔外侧
        lat = rel - along * self.z
        return {"along_m": along, "lateral_m": float(np.linalg.norm(lat)),
                "lateral_vec": lat.copy(),
                "in_insert_zone": bool(along <= self.approach)}

    # ── 轨迹生成 (让光模块"飞"过去) ──
    def fly_to_port(self, start_pos, step: float = 0.004, n_free: int = 40,
                    n_insert: int = 25):
        """生成 起飞→巡航→对准→插入 的航点序列 (世界系位置).

        · 自由段: 从 start 到端口前 approach 处 (直线/或 set_path 的 Bishop 曲线)
        · 对准段: 横向误差归零 (面内微调)
        · 插入段: 沿端口轴 Δz 前进 (Frenet 直线特例)
        返回 [M,3] 航点 + 每段的标架标签.
        """
        s = np.asarray(start_pos, dtype=np.float64).reshape(3)
        pre = self.p0 - self.approach * self.z        # 端口前 approach 处
        pts, tags = [], []

        # ① 自由段 (world / frenet)
        if self._path is not None:
            f = self.frenet_path(start_pos=s, end_pos=pre, n=n_free)
            pts += list(f); tags += ["frenet"] * len(f)
        else:
            for t in np.linspace(0, 1, n_free):
                pts.append(s + t * (pre - s)); tags.append("world")

        # ② 对准段 (port 系横向归零): 横向误差 → 0, 沿轴保持
        lat_end = s - self.p0 - np.dot(s - self.p0, self.z) * self.z
        lat_pre = pre - self.p0 - np.dot(pre - self.p0, self.z) * self.z
        for t in np.linspace(0, 1, max(3, n_insert // 3)):
            p = pre + t * (lat_pre * 0 + (lat_pre - lat_pre))   # 起点即 pre(已在轴上)
            # 把剩余横向误差平滑归零
            p = pre - (1 - t) * lat_pre
            pts.append(p); tags.append("port")

        # ③ 插入段 (沿 -轴 前进到端口, 越过口一点)
        for t in np.linspace(0, 1, n_insert):
            depth = 0.035 * t                              # 插入 35mm
            pts.append(self.p0 + depth * self.z); tags.append("port")

        return np.array(pts), tags

    def frenet_path(self, start_pos, end_pos, n: int = 30, bow: float = 0.05):
        """简单弯曲参考线 (二次 Bezier, 用于演示"沿弯路径飞")."""
        a = np.asarray(start_pos, float).reshape(3)
        b = np.asarray(end_pos, float).reshape(3)
        # 控制点: 中点 + 垂直偏移 (产生曲率)
        mid = 0.5 * (a + b)
        d = _unit(b - a)
        perp = np.cross(d, self.z)
        if float(np.linalg.norm(perp)) < 1e-6:
            perp = np.cross(d, np.array([0.0, 0.0, 1.0]))
        mid = mid + bow * _unit(perp)
        t = np.linspace(0, 1, n)[:, None]
        return (1 - t) ** 2 * a + 2 * (1 - t) * t * mid + t ** 2 * b


__all__ = ["Flight", "bishop_frames", "frenet_curvature_torsion"]
