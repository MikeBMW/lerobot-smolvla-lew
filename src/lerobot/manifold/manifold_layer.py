# -*- coding: utf-8 -*-
"""manifold_layer.py — 🧮 流形层: 接触流形 / 性能流形 (回路外几何分析元层)

第一性原理 (2026-09-03 老倪, 光模块精密制造流形视角):
  光口/电口插拔与光耦合, 物理上是在高维状态空间里沿低维"流形"运动:
    · 接触流形 (Contact Manifold): 插拔的安全通道 — 机器人必须沿该流形推进
      (测地线), 一旦偏离 (法向漂移) → 引脚弯曲/器件报废。
    · 性能流形 (Performance Manifold): 光耦合对准误差 → 传输效率/插入损耗
      构成的性能曲面; 插拔 = 在该流形上找全局最优 (对准代价极小点)。
  本层把这些几何量落成**可执行计算**: 输入 = 引擎轨迹当前帧真实量
  (obs43/target/peg_head/v/stage, 与 tools/gui/state_space_sim.py 同源),
  输出 = 切向进度 / 法向偏离 / 李雅普诺夫势 / 对准代价 / 估计耦合效率。

数据同源: 常量 (HOLE_POS/HOLE_MOUTH/PEG_HEAD_OFF) 与 state_space_sim.py
          逐字同源 (metaworld peg-insert-side-v3 真实几何实测值, 别改单边)。

定位 (回路外): 只分析/监控/展示, 不参与引擎推理, 不新增控制或安全通道
          (状态空间唯一三层安全 = 否决 + 限幅 + Sys0, 流形层不碰)。
          η 是几何→性能**模型** (高斯光束近似), 不是光功率计实测 —
          真机接入点 = 光功率计 IL/RL 标定 W/σ (勿冒充实测)。
"""
import numpy as np

# ── 与 tools/gui/state_space_sim.py 同源 (metaworld peg-insert-side-v3 实测几何) ──
HOLE_POS = np.array([-0.2345, 0.4623, 0.1309])    # 插入终点/孔底 (metaworld goal)
HOLE_MOUTH = np.array([-0.1685, 0.4623, 0.1309])  # 孔口 (侧插入口)
PEG_HEAD_OFF = np.array([-0.130, 0.0, -0.010])    # 光模块头相对抓握点 (光模块 沿 X 长 0.2)
# 孔轴单位向量 (孔口 → 孔底): 水平 −x 方向
AXIS_HOLE = HOLE_POS - HOLE_MOUTH
AXIS_HOLE = AXIS_HOLE / np.linalg.norm(AXIS_HOLE)  # ≈ (−1, 0, 0)

STAGES = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"]

# 通道分组 (哪个子任务受哪条几何通道约束):
#   垂直通道 (z): 手贴身垂直操作 (下降触光模块/抓取锁存/抬起持光模块) — 约束 = xy 对中
#   工艺通道:    插入 = 光模块头沿工艺斜线 (孔口上方悬高 2cm → 孔底, engine 转移/插入
#                子目标同源) 压入; 完成 = 贴孔底 (孔轴 x)
#   自由空间:    空中长距离移动 (接近=飞向光模块上方, 对位=水平对中, 转移=光模块料位→孔口),
#                未接触无弯曲风险源, 只报距离收敛 (progress=‖e‖)
CHANNEL_Z = ("下降", "抓取", "抬起")
CHANNEL_INS = ("插入",)
CHANNEL_DONE = ("完成",)
CHANNEL_FREE = ("接近", "对位", "转移")

# 插入工艺轴: 孔口上方悬高 2cm (engine 转移子目标 z+0.02) → 孔底 (插入子目标)
_HOVER = HOLE_MOUTH + np.array([0.0, 0.0, 0.02])
AXIS_INSERT = HOLE_POS - _HOVER
AXIS_INSERT = AXIS_INSERT / np.linalg.norm(AXIS_INSERT)   # ≈ (−0.957, 0, −0.29)

# 法向偏离阈值 (米) — 超过 = 离流形 (弯曲/报废风险). 初始标定依据:
#   下降/抓取: engine 抓握接触容差 d_xy<0.03 (metaworld 脚本接触判据) →
#                    xy 错位须 <3cm 才允许接触; 插入/完成: 孔间隙量级 (D_INSERT 4mm),
#                    对工艺轴垂直偏离 <6mm; 抬起: 别蹭台面/别晃. 真机按现场微调。
RISK_TH = {
    "接近": 0.030, "对位": 0.030, "下降": 0.030, "抓取": 0.030,
    "抬起": 0.020, "转移": 0.030, "插入": 0.006, "完成": 0.004,
}


def _stage_name(stage):
    """阶段名清洗: engine 轨迹 stage 可能带推进后缀 (如「下降 · 接触」) → 取主阶段"""
    return str(stage).split("·")[0].strip()


class ContactManifold:
    """接触流形 — 插拔安全通道的几何诊断 (切向进度 / 法向偏离 / 李雅普诺夫势)

    输入 = 引擎轨迹当前帧真实量: hand(末端), peg_head(光模块头), target(阶段子目标,
    obs[36:39] 感知层真值), v(末端速度), stage。
    分解: 误差 e 沿通道轴投影 → 切向 e∥ (沿流形推进, 测地线进度);
          法向 e⊥ (离流形漂移, 风险源: 对位歪/插斜都在这)。
    """

    def __init__(self, hole_pos=None, hole_mouth=None, risk_th=None):
        self.hole_pos = HOLE_POS if hole_pos is None else np.asarray(hole_pos, float)
        self.hole_mouth = HOLE_MOUTH if hole_mouth is None else np.asarray(hole_mouth, float)
        self.axis = self.hole_pos - self.hole_mouth
        n = np.linalg.norm(self.axis)
        self.axis = self.axis / n if n > 1e-9 else np.array([-1.0, 0.0, 0.0])
        self.risk_th = dict(RISK_TH)
        if risk_th:
            self.risk_th.update(risk_th)

    # ── 通道轴 (单位向量) ──
    def channel_axis(self, stage):
        if stage in CHANNEL_Z:
            return np.array([0.0, 0.0, 1.0])          # 垂直通道 (下降/抓取/抬起)
        if stage in CHANNEL_INS:
            return AXIS_INSERT                        # 插入工艺斜线 (孔口悬高→孔底)
        if stage in CHANNEL_DONE:
            return self.axis                          # 完成: 贴孔底 (孔轴 x)
        return None                                    # 自由空间 (无约束轴)

    # ── 当前受控体误差: 谁在逼近谁 ──
    def _error(self, hand, peg_head, target, stage):
        if stage in CHANNEL_INS or stage in CHANNEL_DONE:
            return np.asarray(peg_head, float) - self.hole_pos   # 光模块头对孔底 (完成→0)
        return np.asarray(target, float) - np.asarray(hand, float)  # 末端对阶段目标

    def decompose(self, hand, peg_head, target, v, stage):
        """e → 切向 e∥ (进度) / 法向 e⊥ (偏离) + 李雅普诺夫 V, V̇
        返回 dict: progress/risk/V/Vdot/e/e_par/e_perp/axis/state/risk_th"""
        stage = _stage_name(stage)
        e = self._error(hand, peg_head, target, stage)
        v = np.asarray(v, float)
        ax = self.channel_axis(stage)
        if ax is None:
            # 自由空间: 无接触通道, 法向偏离不计风险 (只报几何与收敛)
            e_par, e_perp = e.copy(), np.zeros(3)
            progress = float(np.linalg.norm(e_par))
            risk = 0.0
            state = "自由空间 (无接触约束)"
        else:
            e_par = float(e @ ax) * ax
            e_perp = e - e_par
            progress = float(abs(e @ ax))            # 沿通道剩余量
            risk = float(np.linalg.norm(e_perp))     # 对通道轴的垂直偏离 (统一)
            th = self.risk_th.get(stage, 0.01)
            if risk <= 0.5 * th:
                state = "在流形 (贴线走)"
            elif risk <= th:
                state = "贴流形边缘 (漂移中)"
            else:
                state = "离流形 (弯曲/报废风险)"
        V = 0.5 * float(e @ e)
        Vdot = -float(e @ v)                          # Ṫ≈0 (阶段内目标静止) → V̇=−e·v
        return {"progress": progress, "risk": risk, "V": V, "Vdot": Vdot,
                "e": np.asarray(e, float), "e_par": e_par, "e_perp": e_perp,
                "axis": None if ax is None else np.asarray(ax, float),
                "state": state, "risk_th": self.risk_th.get(stage, None)}

    def summarize(self, r):
        """dict → 一行日志文本"""
        return (f"进度={r['progress']:.4f}m · 法向偏离={r['risk']:.4f}m · "
                f"V=½‖e‖²={r['V']:.3e} · V̇={r['Vdot']:.3e} → {r['state']}")


class PerformanceManifold:
    """性能流形 — 光耦合对准代价与估计耦合效率 (高斯光束近似, 非实测)

    对准误差 δ = 光模块头 − 孔底 (插到底 δ→0 → 耦合最优):
      轴向 x 剩余 = 插深不足; 横向 yz = 模场错位 (耦合损耗主因)。
    性能势 V_p = ½ δᵀWδ (W: 轴向轻权 0.4, 横向 1.0 — 横向 1mm 错位比轴向
    1mm 未插深更伤耦合); 估计耦合效率 η = exp(−V_p/σ²) (单模模场重叠近似)。
    σ 是标定量 (默认 4mm 尺度, 使插入完成判据 D_INSERT≈4mm 时 η 接近 1;
    真机用光功率计 IL/RL 标定 W/σ — 本模块输出是模型不是实测)。
    """

    def __init__(self, hole_pos=None, w=None, sigma=0.004):
        self.hole_pos = HOLE_POS if hole_pos is None else np.asarray(hole_pos, float)
        # W 对角 (x=轴向插深, y/z=横向对中): 顺序与 δ 分量对应
        self.W = np.diag([0.4, 1.0, 1.0]) if w is None else np.asarray(w, float)
        self.sigma = sigma

    def evaluate(self, peg_head, stage=None):
        """光模块头几何 → 对准代价 V_p / 估计耦合效率 η / 梯度 ∇V_p (修正方向)"""
        stage = _stage_name(stage) if stage is not None else None
        d = np.asarray(peg_head, float) - self.hole_pos
        d_ax = float(d @ AXIS_HOLE)                    # 沿孔轴剩余 (插深; 负=未到底)
        d_perp = d - d_ax * AXIS_HOLE                  # 横向错位向量
        Vp = 0.5 * float(d @ self.W @ d)
        eta = float(np.exp(-Vp / max(self.sigma ** 2, 1e-12)))  # 可下溢→0 (未耦合)
        grad = self.W @ d                              # ∇V_p; 最优对准方向 = −grad
        stage_note = stage or ""
        if stage in ("插入", "完成"):
            note = "对孔耦合 (插深+对中)"
        elif stage == "转移":
            note = "接近孔口 (未入孔)"
        else:
            note = "非插入段 (光模块未对孔)"
        return {"delta": d, "d_axial": d_ax, "d_perp_norm": float(np.linalg.norm(d_perp)),
                "Vp": Vp, "eta": eta, "grad": grad, "stage": stage, "note": note}

    def summarize(self, r):
        """dict → 一行日志文本"""
        return (f"对准误差 δ⊥={r['d_perp_norm']*1000:.2f}mm (横向) · "
                f"插深剩余={-r['d_axial']*1000:.2f}mm · V_p={r['Vp']:.3e} · "
                f"η≈{r['eta']:.4f} ({r['note']})")
