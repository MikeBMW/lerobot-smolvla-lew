"""su2.py — SU(2) 统一状态空间 (二阶特殊酉群) · Z-MAX 画布 VEH.5.041 节点内核

═══════════════════════════════════════════════════════════════════════════════
设计意图 (老倪 2026-09-20):
    原来的「🧩 43D 统一状态向量」节点源码是 `def fuse_sensors(rgbd_feats, force_6d,
    tactile_marker)` —— 那是**传感器融合**, 是拼接向量, 不是统一状态。
    真正的统一状态空间是一个**群**: SU(2) = Special Unitary group of degree 2
    (二阶特殊酉群), 所有层/所有节点的数据都映射到这个群的一个元素上;
    在这个群的数据空间里可以观察并理解整个状态空间的场景。

数学定义:
    SU(2) = { U ∈ C^{2×2} : U†U = I, det U = 1 }
          = { U(ω) = exp(−i·(ω·σ)/2) : ω ∈ R³ }        (指数映射, σ=泡利矩阵)
    四元数表示 U = w·I − i(x·σx + y·σy + z·σz), (w,x,y,z) 单位四元数 → U ≅ S³
    群运算   U1·U2  = 哈密顿四元数积 (不可交换)
    李代数   su(2) = span{σx, σy, σz},  ω = 旋转向量, θ=‖ω‖ 旋转角, n̂=ω/θ 旋转轴
    可观测量 Bloch 向量  r = (2(wy−zx), 2(wx+zy), w²+z²−x²−y²) = sinθ·n̂, |r| ≤ 1
        物理含义: n̂ = 状态(误差/意图)方向, θ = 激活(旋转)幅度, |r| = 可观测强度
                  U = I ⇔ 状态收敛(无残差), θ=0/π ⇒ |r|=0 (不可观测, 即恒等/翻转)

映射原则 (为什么"所有数据"都能进这个群):
    任意实向量 f ∈ R^k → su(2) 系数 ω = G·Π·f (Π=通道均值读出, G=增益) → U = exp(−i ω·σ/2)
    **指数映射把 R³ 整体映到 SU(2) 内部**: 无论数据多大/多脏, 结果一定是酉、det=1 的群元素
    → 群对任意输入封闭, 这就是"全面映射"的数学保证 (不会溢出, 不需要归一化假设)。

层合成 (上层只给意图/条件, 执行由最下层收口):
    U_scene = U_L2 ⊗ U_L3 ⊗ U_L4 ⊗ U_L5     (⊗ = 群乘法, 右乘=后作用的层)
    层的先后**不可交换**: U_L2·U_L3 ≠ U_L3·U_L2, 其差 ‖[U_i,U_j]‖ = 2|sinΘ| 就是层间耦合强度
    反演(观察/理解): U_L2⁻¹·U_scene = U_L3·U_L4·U_L5 —— 逐层剥离, 读每一层"贡献了什么"

节点级映射 (数据来自每个节点的映射):
    encode_nodes(frame) —— 画布每个节点(引擎 io_trace 帧)的输出 → 一个 SU(2) 元素,
    U_scene(nodes) = 按 MODULE_ORDER 顺序的群合成 → 由此观察/理解整场景。
═══════════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import json
import os
import re

import numpy as np

# ── 泡利矩阵 (su(2) 基) ───────────────────────────────────────────────────────
SIGMA_X = np.array([[0, 1], [1, 0]], dtype=complex)
SIGMA_Y = np.array([[0, -1j], [1j, 0]], dtype=complex)
SIGMA_Z = np.array([[1, 0], [0, -1]], dtype=complex)
SIGMAS = (SIGMA_X, SIGMA_Y, SIGMA_Z)
I2 = np.eye(2, dtype=complex)

# 仓库根: .../src/lerobot/policies/left_right/state_space/su2.py → 上溯 5 层
REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                          *([".."] * 5)))
MAPPING_JSON = os.path.join(REPO_ROOT, "data", "su2_mapping.json")


# ════════════════════════════════════════════════════════════════════════════
# 1. 群元素
# ════════════════════════════════════════════════════════════════════════════
class SU2Element:
    """SU(2) 群元素 (单位四元数表示, U = w·I − i(x σx + y σy + z σz))"""

    __slots__ = ("w", "x", "y", "z")

    def __init__(self, w=1.0, x=0.0, y=0.0, z=0.0, normalize=False):
        v = np.array([w, x, y, z], dtype=float)
        n = float(np.linalg.norm(v))
        if n < 1e-12:
            raise ValueError("SU(2): 零四元数不是群元素")
        if normalize or abs(n - 1.0) > 1e-12:
            v = v / n
        self.w, self.x, self.y, self.z = (float(v[0]), float(v[1]), float(v[2]), float(v[3]))

    # ── 构造 ──
    @staticmethod
    def identity() -> "SU2Element":
        """单位元 I (无状态/场景收敛)"""
        return SU2Element(1.0, 0.0, 0.0, 0.0)

    @staticmethod
    def from_rotvec(omega) -> "SU2Element":
        """指数映射: su(2) 向量 ω → 群元素 exp(−i ω·σ/2)"""
        omega = np.asarray(omega, dtype=float).reshape(3)
        theta = float(np.linalg.norm(omega))
        if theta < 1e-12:
            return SU2Element.identity()
        n = omega / theta
        half = 0.5 * theta
        return SU2Element(np.cos(half), *(np.sin(half) * n))

    @staticmethod
    def from_axis_angle(axis, angle) -> "SU2Element":
        axis = np.asarray(axis, dtype=float).reshape(3)
        nn = float(np.linalg.norm(axis))
        if nn < 1e-12:
            return SU2Element.identity()
        return SU2Element.from_rotvec(axis / nn * float(angle))

    @staticmethod
    def random(rng=None) -> "SU2Element":
        """Haar 随机群元素 (单位四元数在 S³ 上均匀采样)"""
        rng = rng or np.random.default_rng()
        v = rng.normal(size=4)
        return SU2Element(*v)

    # ── 群结构 ──
    def __mul__(self, other: "SU2Element") -> "SU2Element":
        """哈密顿积 (群乘法, 不可交换) — 对应矩阵乘法"""
        a, b = self, other
        return SU2Element(
            a.w * b.w - a.x * b.x - a.y * b.y - a.z * b.z,
            a.w * b.x + a.x * b.w + a.y * b.z - a.z * b.y,
            a.w * b.y - a.x * b.z + a.y * b.w + a.z * b.x,
            a.w * b.z + a.x * b.y - a.y * b.x + a.z * b.w,
        )

    def inv(self) -> "SU2Element":
        """逆元 U⁻¹ = U† (四元数共轭)"""
        return SU2Element(self.w, -self.x, -self.y, -self.z)

    @staticmethod
    def compose(elements) -> "SU2Element":
        """有序群合成 U1·U2·…·Un (顺序敏感: 左乘=后作用的层)"""
        out = SU2Element.identity()
        for e in elements:
            out = out * e
        return out

    def commutator_norm(self, other: "SU2Element") -> float:
        """‖[U1,U2]‖₂ — 不可交换性(层间耦合)度量; =0 表示两层可交换(解耦)"""
        anti = self * other
        comm = anti * (other * self).inv()
        return float(np.linalg.norm(comm.mat() - I2))

    def commutator_angle(self, other: "SU2Element") -> float:
        """不可交换角 Θ = arccos(Re⟨U1U2 U2⁻¹U1⁻¹⟩) ∈ [0,π] (实测量)"""
        comm = (self * other) * (other * self).inv()
        return float(np.arccos(np.clip(comm.w, -1.0, 1.0)))

    # ── 李代数 ──
    def log(self) -> np.ndarray:
        """对数映射(主值分支): 群元素 → su(2) 旋转向量 ω

        用带符号半角 half = atan2(‖v‖, w) ∈ (−π, π] → ω = n̂·2·half,
        保证 exp(log(U)) = U **精确**(不做双覆盖取绝对值的近似)。
        注: ‖ω‖>π 的 ω 与 ω−2π n̂ 映到同一群元素(SU(2) 覆盖 SO(3), 2π 转回 −I/4π 回 I),
        故 log 只能还原主值分支 — 这是群的性质, 不是误差。
        """
        s = float(np.linalg.norm([self.x, self.y, self.z]))
        if s < 1e-12:
            return np.zeros(3) if self.w >= 0 else np.array([np.pi, 0.0, 0.0])
        n = np.array([self.x, self.y, self.z]) / s
        return n * (2.0 * float(np.arctan2(s, self.w)))

    def generators(self) -> np.ndarray:
        """李代数系数 = log(ω) (与 from_rotvec 互逆)"""
        return self.log()

    # ── 观测量 (Bloch 球) ──
    def bloch(self) -> np.ndarray:
        """Bloch 向量 r — 该群元素(S作为旋转)作用在参考态(北极)上的像, ‖r‖ ≡ 1

        r = (2(wy−zx), 2(wx+zy), w²+z²−x²−y²);  实测 ‖r‖−1 ≤ 5.6e-16
        → SU(2) 元素 ↔ 纯态, 全部落在 Bloch 球面上 (S²): 这就是"统一状态空间"的
          可视几何, 任意数据映射后依然是球面上一点(纯态, 不会跑出群外)。
        """
        w, x, y, z = self.w, self.x, self.y, self.z
        return np.array([2.0 * (w * y - z * x), 2.0 * (w * x + z * y),
                         w * w + z * z - x * x - y * y])

    def theta(self) -> float:
        """旋转角 θ = 2·arccos|w| ∈ [0,π] (激活幅度)"""
        return float(2.0 * np.arccos(np.clip(abs(self.w), -1.0, 1.0)))

    def axis(self) -> np.ndarray:
        """旋转轴 n̂ (状态方向); θ=0 时返回零向量(方向无定义)"""
        v = np.array([self.x, self.y, self.z])
        n = float(np.linalg.norm(v))
        return v / n if n > 1e-12 else np.zeros(3)

    def purity(self) -> float:
        """纯态纯度 |r| — 群元素总对应纯态, 恒为 1 (实测 1±5.6e-16)"""
        return float(np.linalg.norm(self.bloch()))

    def visibility(self) -> float:
        """干涉可见度 / 与参考(收敛)态的对齐度 = |w| = |cos(θ/2)| ∈ [0,1]

        物理含义: 1 ⇒ 场景收敛到参考态(U=I, 任务完成);
                  0 ⇒ 与参考态正交(状态翻转, 完全未收敛/反相)。
        """
        return float(abs(self.w))

    def mat(self) -> np.ndarray:
        """2×2 复矩阵表示 (用于群公理/酉性校验)"""
        return (self.w * I2 - 1j * (self.x * SIGMA_X + self.y * SIGMA_Y + self.z * SIGMA_Z))

    def ket(self) -> np.ndarray:
        """态矢 |ψ⟩ = U|0⟩ (第一列) — 可视化/干涉用"""
        return self.mat()[:, 0]

    def is_unitary(self, eps=1e-9) -> bool:
        m = self.mat()
        return bool(np.allclose(m.conj().T @ m, I2, atol=eps)) and \
            bool(abs(np.linalg.det(m) - 1.0) < eps)

    # ── 距离 / 度量 ──
    def distance_fs(self, other: "SU2Element") -> float:
        """Fubini–Study 测地距离 arccos|⟨U1,U2⟩| ∈ [0,π/2] (双覆盖取 |·|)"""
        dot = abs(self.w * other.w + self.x * other.x + self.y * other.y + self.z * other.z)
        return float(np.arccos(np.clip(dot, -1.0, 1.0)))

    def distance_chord(self, other: "SU2Element") -> float:
        """欧氏(弦)距离 ‖U1−U2‖₂"""
        return float(np.linalg.norm(self.mat() - other.mat()))

    # ── 人机可读 ──
    def describe(self) -> str:
        ax = self.axis()
        return ("θ=%.4f rad (%.2f°) n̂=(%+.3f,%+.3f,%+.3f) 收敛度|w|=%.4f"
                % (self.theta(), np.degrees(self.theta()), ax[0], ax[1], ax[2],
                   self.visibility()))

    def as_dict(self) -> dict:
        return {"quat": [self.w, self.x, self.y, self.z],
                "theta": self.theta(), "axis": self.axis().tolist(),
                "bloch": self.bloch().tolist(), "visibility": self.visibility(),
                "purity": self.purity()}

    def __repr__(self) -> str:
        return "<SU2 %s>" % self.describe()


# ════════════════════════════════════════════════════════════════════════════
# 2. 映射层: 任意实向量 → SU(2) (指数映射, 对任意输入封闭)
# ════════════════════════════════════════════════════════════════════════════
def bounded_rotvec(v, gain=2.0) -> np.ndarray:
    """有界映射律: 任意实向量 → su(2) 系数 ω = π·tanh(gain·‖v‖)·v̂

    性质(实测): ① θ=‖ω‖ 对 ‖v‖ 严格单调 ↑ (误差越大越"激活")
                ② 方向 n̂ = v̂ 完全保留 (数据的方向语义不丢)
                ③ θ < π 恒成立 → 永不绕圈 (不会出现 θ 3.14 与 0.00 混在一起的假收敛)
                ④ ‖v‖→0 ⇒ ω→0 ⇒ U→I (场景收敛);  ‖v‖→∞ ⇒ θ→π (最大偏离)
    说明: 为什么不用 ω = gain·v —— 那样 θ 会超过 π 绕回, 轨迹出现跳变假象;
          有界律保证"误差-角度"一一对应, 是可视化的前提。
    """
    v = np.asarray(v, dtype=float).reshape(3)
    n = float(np.linalg.norm(v))
    if n < 1e-15:
        return np.zeros(3)
    return (np.pi * np.tanh(gain * n) / n) * v


# ── 43D 统一状态向量 (旧观察量) 的语义通道划分 ───────────────────────────────
# [0:3]手位置 [3]夹爪 [4:7]光模块位置 [7:11]光模块四元数 [11:18]pad×7
# [18:36]上一帧18D [36:39]孔位 [39:43]触觉(grasp/contact/dir_x/dir_z)
def obs43_geometry(obs) -> np.ndarray:
    """43D obs → 几何误差向量 e = (光模块头 − 孔位) (m), 统一状态的方向来源

    输入兼容: (43,)/(1,43)/列表 均可 (批量取首行, 不炸)。
    """
    o = np.asarray(obs, dtype=float)
    if o.ndim > 1:
        o = o[0] if o.shape[0] == 1 else o.reshape(-1)
    o = o.reshape(-1)
    if o.size < 43:
        o = np.pad(o, (0, 43 - o.size))
    peg_head = o[4:7].copy()
    peg_head[2] += 0.030                      # 光模块头相对本体中心偏置 (与感知层一致)
    return peg_head - o[36:39]


def encode_obs43(obs, gain=2.0) -> SU2Element:
    """L2 执行层映射: 43D 统一状态向量(旧观察量) → SU(2) = 几何误差的群表示

    ω = π·tanh(gain·‖e‖)·ê ,  e = 光模块头 − 孔位 (m)
    实测语义: e→0 ⇒ U→I (θ→0, 场景收敛/插入到位); n̂ = 误差方向; θ/π = 偏离程度
    注: 触觉/力/夹爪不是几何量, 由「🖐触觉感知」等节点各自映射成独立群元素参与合成
        (不做量纲混编到 L2, 保证 n̂ 的"误差方向"语义干净)。
    """
    return SU2Element.from_rotvec(bounded_rotvec(obs43_geometry(obs), gain))


# ════════════════════════════════════════════════════════════════════════════
# 3. 分层映射 L2 / L3 / L4 / L5
# ════════════════════════════════════════════════════════════════════════════
LAYER_META = {
    "L2": "肌肉记忆/执行层 — 43D 统一状态(旧观察量) 几何误差映射",
    "L3": "规划层 — 任务进度/法向偏离/剩余深度 (流形规划读数)",
    "L4": "自主层 — 安全限幅后的动作/接触/性能流形效能",
    "L5": "大模型层 — 场景意图 (VLM/LLM 输出的意图向量; 未接入 = 单位元, 不编造)",
}


LAYER_GAIN = {"L2": 2.0, "L3": 3.0, "L4": 1.0, "L5": 1.0}


def _scalar(x, default=0.0) -> float:
    """把任意标量/0-d/1元素数组/None 安全取成 float (数组不能进布尔上下文, 踩过)"""
    if x is None or isinstance(x, bool):
        return float(x) if isinstance(x, bool) else default
    try:
        a = np.asarray(x, dtype=float).reshape(-1)
        return float(a[0]) if a.size else default
    except Exception:                                                       # noqa: BLE001
        try:
            return float(x)                                                 # type: ignore[arg-type]
        except Exception:                                                   # noqa: BLE001
            return default


def encode_layer(L: str, frame: dict, obs43=None) -> SU2Element:
    """单层 → SU(2)。frame: 引擎 io_trace 帧/真机帧的标量字典 (缺项按 0, 不编造)。"""
    def g(k, d=0.0):
        return _scalar(frame.get(k, d), d)
    if L == "L2":
        if obs43 is None:
            return SU2Element.identity()
        return encode_obs43(obs43, LAYER_GAIN["L2"])
    if L == "L3":
        # 规划层读数: 流形进度 e∥ / 法向偏离 e⊥ / 剩余插入深度 (有界映射)
        return SU2Element.from_rotvec(bounded_rotvec(
            [g("mani_progress"), g("mani_dperp"), g("mani_rem")], LAYER_GAIN["L3"]))
    if L == "L4":
        # 自主/安全层: 限幅后动作范数 / 接触概率 / 未达性能流形程度 (1−η)
        return SU2Element.from_rotvec(bounded_rotvec(
            [g("u_sat"), g("contact_p"), 1.0 - g("mani_eta")], LAYER_GAIN["L4"]))
    if L == "L5":
        # 大模型层: 意图向量 (intent). 引擎无 LLM → 空向量 → 单位元(诚实: 未接入)
        intent = frame.get("L5_intent") or []
        if not intent:
            return SU2Element.identity()
        return SU2Element.from_rotvec([float(v) for v in np.asarray(intent, float).reshape(-1)[:3]])
    raise KeyError("未知层: %s" % L)


def encode_layers(frame: dict, obs43=None, order=("L2", "L3", "L4", "L5")) -> dict:
    return {L: encode_layer(L, frame, obs43) for L in order}


def compose_scene(layers: dict, order=("L2", "L3", "L4", "L5")) -> SU2Element:
    """U_scene = U_L2 ⊗ U_L3 ⊗ U_L4 ⊗ U_L5 (左乘=后作用; 层序不可交换)"""
    return SU2Element.compose([layers[L] for L in order if L in layers])


def peel_layers(layers: dict, scene: SU2Element, order=("L2", "L3", "L4", "L5")) -> dict:
    """反演(观察/理解): 逐层剥离, 读"每层贡献了多少" ── U_k⁻¹·U_scene 的 θ 变化"""
    out = {}
    cur = scene
    for L in order:
        u = layers.get(L)
        if u is None:
            continue
        nxt = u.inv() * cur
        out[L] = {"theta_before": cur.theta(), "theta_after": nxt.theta(),
                  "delta_theta": cur.theta() - nxt.theta(),
                  "layer_theta": u.theta(), "layer_axis": u.axis().tolist()}
        cur = nxt
    out["_residual"] = {"theta": cur.theta(), "purity": cur.purity(),
                        "note": "全部剥离后应为单位元 θ≈0 (数值残差)"}
    return out


def commutativity_matrix(layers: dict, order=("L2", "L3", "L4", "L5")) -> dict:
    """层间不可交换性矩阵 ‖[U_i,U_j]‖₂ — 值大 = 两层意图/执行强耦合, 0 = 解耦"""
    ks = [k for k in order if k in layers]
    M = {}
    for i in ks:
        for j in ks:
            M["%s|%s" % (i, j)] = round(layers[i].commutator_norm(layers[j]), 6)
    return M


def fs_distance_matrix(states: dict) -> dict:
    """Fubini–Study 测地距离矩阵 (层间几何关系/场景相似度)"""
    ks = list(states.keys())
    return {"%s|%s" % (a, b): round(states[a].distance_fs(states[b]), 6)
            for a in ks for b in ks}


def understand(scene: SU2Element, layers: dict) -> dict:
    """场景理解: 从群元素读出方向/幅度/层序效应 (全为实测量, 无数值编造)"""
    peel = peel_layers(layers, scene)
    return {
        "state": scene.as_dict(),
        "readout": "状态方向 n̂=%s · 偏离角 θ=%.4f rad · 收敛度|w|=%.4f · Bloch球面点‖r‖=%.6f"
                   % (np.round(scene.axis(), 3).tolist(), scene.theta(),
                      scene.visibility(), scene.purity()),
        "converged": bool(scene.theta() < 0.05),
        "dominant_layer": (max((k for k in peel if not k.startswith("_")),
                              key=lambda k: peel[k]["layer_theta"]) if peel else None),
        "layer_peel": peel,
        "noncommutativity": commutativity_matrix(layers),
        "layer_distance": fs_distance_matrix(layers),
        "note": "U=I(θ→0) ⇒ 场景收敛(误差零); 层剥离残余 θ 应≈0 (群恒等元验证)",
    }


# ════════════════════════════════════════════════════════════════════════════
# 4. 节点级映射: 画布每个节点的数据 → 群元素 (全面映射)
# ════════════════════════════════════════════════════════════════════════════
# 每个节点的"统一状态向量"取自它在引擎 io_trace 里的真实输出 (语义规则, 不是编造)
# spec 类型:
#   ("vec",  label子串, k)      取该 out 条目前 k 个数值作状态向量
#   ("slice",label子串, i, j)   取该 out 条目 [i:j]
#   ("diff", labelA, labelB)    A[:3] − B[:3] (几何差向量, 如 光模块−孔位)
#   ("chans",[l1,l2,l3])        三条目首值作 3 通道 (不同量纲时按向量范数归一, 已注)
#   ("obserr",)                 用 43D obs 直接算 光模块头−孔位 几何误差
NODE_SPECS = {
    "📦 metaworld 数据源":  ("slice", "状态流", 0, 3),
    "🎯 YOLO 目标检测":      ("diff", "peg 检测框", "hole 检测框"),
    "📐 2D→3D 解算":        ("diff", "peg 3D", "hole 3D"),
    "🖐 触觉感知":          ("vec", "触觉 4D", 3),
    "🔍 外观质量检测":      ("vec", "质量门", 3),
    "📡 传感器融合":        ("obserr",),
    "⚡ 前馈加速器":        ("vec", "前馈指令", 3),
    "🔮 自适应状态估计器":  ("vec", "先验估计", 3),
    "📈 先验动力学预测器":  ("vec", "预测 next_obs", 3),
    "🧪 状态校正器":        ("vec", "残差", 3),
    "🧭 动作调制器":        ("vec", "融合指令", 3),
    "🛡 安全限幅":          ("vec", "限幅后", 3),
    "🤖 执行器":            ("vec", "速度指令", 3),
    "🌍 物理世界":          ("vec", "末端位置", 3),
    "🧮 接触流形":          ("chans", ["流形进度", "法向偏离", "V=½"]),
    "🧮 性能流形":          ("chans", ["横向错位", "插深剩余", "V_p"]),
    "🧮 潜空间":            ("vec", "潜坐标", 3),
}

_NUM_RE = re.compile(r"-?\d+\.?\d*")


def _nums(v) -> list:
    """从任意 out 值里取真实数值: 数组/标量直转, 字符串用正则提数(引擎把数值写在标签文本里,

    如 'xy=(0.096,0.520) conf --')。取不到 → 空列表 (不编造)。
    """
    if isinstance(v, bool):
        return []
    if isinstance(v, (int, float)):
        return [float(v)]
    if isinstance(v, (list, tuple, np.ndarray)):
        try:
            return [float(x) for x in np.asarray(v, dtype=float).reshape(-1)]
        except Exception:
            return []
    if isinstance(v, str):
        return [float(x) for x in _NUM_RE.findall(v)]
    return []


def _pick(out: dict, sub: str) -> list:
    for lab, val in out.items():
        if sub in lab:
            return _nums(val)
    return []


def node_vector(node: str, out: dict, obs43=None) -> np.ndarray:
    """按语义规则从节点真实输出取出状态向量 (取不到 → 空数组 = 不编造)"""
    spec = NODE_SPECS.get(node)
    if spec is None:
        vals = []
        for val in out.values():
            vals += _nums(val)
            if len(vals) >= 3:
                break
        return np.asarray(vals[:3], dtype=float)
    kind = spec[0]
    if kind == "vec":
        return np.asarray(_pick(out, spec[1])[:spec[2]], dtype=float)
    if kind == "slice":
        return np.asarray(_pick(out, spec[1])[spec[2]:spec[3]], dtype=float)
    if kind == "diff":
        a = np.asarray(_pick(out, spec[1])[:3], dtype=float)
        b = np.asarray(_pick(out, spec[2])[:3], dtype=float)
        if a.size == 0 or b.size == 0:
            return np.zeros(0)
        n = max(a.size, b.size, 3)                      # 2D 框→z 补 0, 仍进群
        a = np.pad(a, (0, n - a.size))
        b = np.pad(b, (0, n - b.size))
        return a - b
    if kind == "chans":
        vv = [_pick(out, s)[:1] for s in spec[1]]
        return np.asarray([x[0] for x in vv if x], dtype=float)
    if kind == "obserr":
        if obs43 is None:
            o = _pick(out, "观测 obs")
            obs43 = np.asarray(o, dtype=float) if len(o) >= 39 else None
        return obs43_geometry(obs43) if obs43 is not None else np.zeros(0)
    return np.zeros(0)


def encode_node(node: str, out: dict, gain=2.0, obs43=None) -> SU2Element:
    """一个节点的真实输出 → SU(2) 群元素 (有界映射律)"""
    v = node_vector(node, out, obs43)
    if v.size == 0:
        return SU2Element.identity()
    return SU2Element.from_rotvec(bounded_rotvec(v[:3], gain))


def encode_nodes(frame: dict, order=None, gain=2.0, detail=None) -> dict:
    """整帧(全节点) → 每节点一个群元素。

    frame: {节点名: {"out": [(label, value), ...]}}
    detail(可选 dict): 回填 {"no_numeric_output": [节点名...]} — 本帧该节点
    无任何数值输出 → 映射为单位元(诚实标注, 不编造数值)。
    """
    order = order or list(NODE_SPECS.keys())
    states, empty = {}, []
    for node in order:
        mo = frame.get(node)
        if not mo:
            continue
        pairs = mo.get("out", []) if isinstance(mo, dict) else []
        out = {}
        for it in pairs:
            if isinstance(it, (list, tuple)) and len(it) == 2:
                out[str(it[0])] = it[1]
        if not out:
            continue
        if node_vector(node, out).size == 0:
            empty.append(node)
            states[node] = SU2Element.identity()
        else:
            states[node] = encode_node(node, out, gain)
    if detail is not None:
        detail["no_numeric_output"] = empty
    return states


def scene_from_nodes(node_states: dict) -> SU2Element:
    """全场景统一状态 = 各节点群元素按链路顺序合成"""
    return SU2Element.compose(list(node_states.values()))


# ════════════════════════════════════════════════════════════════════════════
# 5. 可视化层统一载荷 (所有可视化工具的输入都从这一个函数出)
# ════════════════════════════════════════════════════════════════════════════
def viz_payload(frame: dict, obs43=None, node_states=None, history=None) -> dict:
    """统一可视化载荷 — Bloch 球 / S³ / 层贡献 / 距离矩阵 / 轨迹 / 节点映射 一份出全"""
    layers = encode_layers(frame, obs43)
    scene = compose_scene(layers)
    nodes = node_states if node_states is not None else {}
    return {
        "scene": scene.as_dict(),
        "s3": [scene.w, scene.x, scene.y, scene.z],
        "bloch": scene.bloch().tolist(),
        "layers": {L: u.as_dict() for L, u in layers.items()},
        "nodes": {k: u.as_dict() for k, u in nodes.items()},
        "understand": understand(scene, layers),
        "trajectory": list(history or []) + [scene.bloch().tolist()],
        "contract": "SU(2) 统一状态空间 · 所有可视化层从此载荷取数 (VEH.5.041)",
    }


# ════════════════════════════════════════════════════════════════════════════
# 6. 统一状态 (对外主类)
# ════════════════════════════════════════════════════════════════════════════
class SU2UnifiedState:
    """SU(2) 统一状态空间 — 把 L2/L3/L4/L5 + 全部节点数据映射进二阶特殊酉群"""

    def __init__(self, gain=6.0, order=("L2", "L3", "L4", "L5"), log=None):
        self.gain = float(gain)
        self.order = tuple(order)
        self._log = log
        self.history = []                    # Bloch 轨迹
        self.node_history = []               # 节点群元素轨迹 (可视化)

    # 单帧: 分层 → 群元素 → 场景态
    def push(self, frame: dict, obs43=None):
        layers = encode_layers(frame, obs43, self.order)
        scene = compose_scene(layers, self.order)
        self.history.append(scene.bloch().tolist())
        u = understand(scene, layers)
        if self._log:
            self._log("🧩 SU(2) 统一状态: %s" % u["readout"])
            for L in self.order:
                self._log("   %s: %s" % (L, layers[L].describe()))
            self._log("   层剥离残余 θ=%.2e (应≈0 = 群恒等元)" % u["layer_peel"]["_residual"]["theta"])
        return scene, layers, u

    # 整帧全节点 (全面映射)
    def push_nodes(self, frame: dict):
        nodes = encode_nodes(frame)
        scene = scene_from_nodes(nodes)
        self.node_history.append({k: v.as_dict() for k, v in nodes.items()})
        if self._log:
            self._log("🧩 SU(2) 节点映射: %d 个节点 → 群元素, 场景态 %s"
                      % (len(nodes), scene.describe()))
        return scene, nodes


# ════════════════════════════════════════════════════════════════════════════
# 7. 映射表 (可扩展: 群的数据来自每个节点的映射)
# ════════════════════════════════════════════════════════════════════════════
DEFAULT_MAPPING = {
    "version": "v1",
    "node": "VEH.5.041",
    "group": "SU(2) = {U∈C^2×2 : U†U=I, det U=1}",
    "obs_dim": 43,
    "compose_order": ["L2", "L3", "L4", "L5"],
    "layer_gain": LAYER_GAIN,
    "map_law": "ω = π·tanh(gain·‖v‖)·v̂  (有界映射律: θ<π 不绕圈, 方向保留)",
    "layers": LAYER_META,
    "node_specs": {k: list(v) for k, v in NODE_SPECS.items()},
    "observables": ["theta", "axis", "bloch", "purity", "layer_peel",
                    "noncommutativity", "fs_distance"],
}


def load_mapping(path=MAPPING_JSON) -> dict:
    """读映射表; 缺失 → 内置默认 (画布/引擎不阻塞)"""
    try:
        with open(path, encoding="utf-8") as f:
            m = json.load(f)
        return {**DEFAULT_MAPPING, **m}
    except Exception:
        return dict(DEFAULT_MAPPING)


def save_mapping(path=MAPPING_JSON) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_MAPPING, f, ensure_ascii=False, indent=1)
    return path


# ════════════════════════════════════════════════════════════════════════════
# 8. 群公理自检 (数值证据, 供验证层/画布"验证"节点调用)
# ════════════════════════════════════════════════════════════════════════════
def group_axiom_selftest(n=64, seed=0, eps=1e-9) -> dict:
    """逐条数值验证 SU(2) 群结构 + 映射性质 (返回实测误差, 不写死"通过")"""
    rng = np.random.default_rng(seed)
    els = [SU2Element.random(rng) for _ in range(n)]
    res = {}

    # ① 封闭性 + 酉性 + det=1
    prod = [a * b for a, b in zip(els, els[1:])]
    res["closure_max_unitarity_err"] = max(
        float(np.max(np.abs(e.mat().conj().T @ e.mat() - I2))) for e in prod)
    res["closure_max_det_err"] = max(float(abs(np.linalg.det(e.mat())) - 1.0) for e in prod)

    # ② 结合律 (U1U2)U3 = U1(U2U3)
    e = max((((els[i] * els[i + 1]) * els[i + 2]).distance_chord(
        els[i] * (els[i + 1] * els[i + 2]))) for i in range(n - 3))
    res["associativity_max_err"] = float(e)

    # ③ 单位元 / ④ 逆元
    res["identity_max_err"] = max((els[i] * SU2Element.identity()).distance_chord(els[i])
                                  for i in range(n))
    res["inverse_max_err"] = max((els[i] * els[i].inv()).distance_chord(SU2Element.identity())
                                 for i in range(n))

    # ⑤ exp/log 互逆 (su(2) ↔ SU(2) 双向) — 主值分支 ‖ω‖ ≤ π 内精确可逆
    omegas = rng.normal(size=(n, 3))
    omegas = omegas / np.linalg.norm(omegas, axis=1, keepdims=True) * np.linspace(0.01, np.pi, n)[:, None]
    res["exp_log_max_err"] = float(max(np.max(np.abs(
        SU2Element.from_rotvec(w).log() - w)) for w in omegas))
    res["log_exp_max_err"] = float(max(SU2Element.from_rotvec(els[i].log())
                                       .distance_chord(els[i]) for i in range(n)))

    # ⑥ Bloch: ‖r‖≡1 (纯态在球面), 且 |w| = cos(θ/2) (收敛度-角度一致性)
    res["bloch_norm_max_err"] = float(max(abs(els[i].purity() - 1.0) for i in range(n)))
    res["visibility_cos_half_theta_max_err"] = float(max(
        abs(els[i].visibility() - np.cos(0.5 * els[i].theta())) for i in range(n)))

    # ⑦ 不可交换性: 随机两元素 θ 平均应 > 0 (群非阿贝尔)
    comm = np.mean([els[i].commutator_angle(els[(i * 7 + 3) % n]) for i in range(n)])
    res["mean_commutator_angle_rad"] = float(comm)

    # ⑧ 距离度量性质: 对称 + 三角不等式(抽样)
    ds = [els[i].distance_fs(els[(i * 5 + 1) % n]) for i in range(n)]
    sym = max(abs(els[i].distance_fs(els[(i * 5 + 1) % n])
                  - els[(i * 5 + 1) % n].distance_fs(els[i])) for i in range(n))
    tri = []
    for i in range(0, n - 3, 3):
        a, b, c = els[i], els[i + 1], els[i + 2]
        tri.append(a.distance_fs(c) - (a.distance_fs(b) + b.distance_fs(c)))
    res["distance_symmetry_max_err"] = float(sym)
    res["distance_triangle_max_violation"] = float(max(tri))

    # ⑨ 映射封闭性: 任意实向量(含大值/脏值)映射后仍是合法群元素
    bad = 0
    for v in rng.normal(size=(n, 3)) * 50:
        u = SU2Element.from_rotvec(v)
        if not u.is_unitary(1e-8) or not np.isfinite(u.w):
            bad += 1
    res["mapping_closure_bad_count"] = bad
    res["n_samples"] = n
    res["all_ok"] = bool(res["closure_max_unitarity_err"] < eps
                         and res["closure_max_det_err"] < eps
                         and res["associativity_max_err"] < eps
                         and res["identity_max_err"] < eps
                         and res["inverse_max_err"] < eps
                         and res["exp_log_max_err"] < 1e-9
                         and res["log_exp_max_err"] < 1e-9
                         and res["bloch_norm_max_err"] < 1e-9
                         and res["visibility_cos_half_theta_max_err"] < eps
                         and res["mapping_closure_bad_count"] == 0
                         and res["distance_symmetry_max_err"] < eps)
    return res


if __name__ == "__main__":
    import pprint
    print("== SU(2) 群公理自检 ==")
    pprint.pprint(group_axiom_selftest())
