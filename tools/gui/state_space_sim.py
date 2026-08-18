# -*- coding: utf-8 -*-
"""
state_space_sim.py — 🧮 状态空间画布真实仿真引擎 (2026-08-18 老倪)

按画布拓扑驱动六层真实源码, 每节点打印真实数值:
  📡传感器融合 → 🧩43D obs → ⚡前馈加速器 ‖ 🔮状态估计器
    → 📈先验动力学 → 🧪状态校正器(残差&接触概率) → 🧭认知调度器(否决权)
    → 🛡安全限幅 → 🤖执行器 → 🌍物理世界(噪声观测 z_k) → 闭环

物理世界 = 光模块插拔简化模型 (末端位置积分 + 夹爪一阶 + 接触/插入判定)。
引擎不引入 torch 等重依赖 — 六层源码经 importlib 按文件路径加载 (仅 numpy)。
"""
import importlib.util
import os
import sys
import numpy as np

_SS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                       "src", "lerobot", "policies", "left_right", "state_space")


def _load(name):
    """按文件路径加载六层模块 (避开 lerobot 包级 torch 依赖)"""
    path = os.path.join(_SS_DIR, name)
    spec = importlib.util.spec_from_file_location(f"state_space.{name[:-3]}", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# 物理世界模型参数 (光模块插拔)
HOLE_POS = np.array([0.25, 0.0, 0.05])   # 孔位 (销钉目标)
X0 = np.array([0.10, -0.06, 0.12])       # 末端起始位置
D_CONTACT = 0.02                          # 水平接触距离 (销钉到孔沿)
D_INSERT = 0.004                          # 插入成功判定
K_CONTACT = 6.0                           # 接触力增益
DT = 0.02
T_END = 10.0


class StateSpaceSim:
    """状态空间画布仿真 — run() 返回时间序列 (Scope 波形用) + 逐节点回调数值"""

    def __init__(self, log=None, dt=DT, t_end=T_END):
        self.log = log or (lambda *a: None)
        self.dt = dt
        self.t_end = t_end
        # 实例化六层真实源码
        self.perception = _load("perception.py")
        self.parallel = _load("parallel.py")
        self.dynamics = _load("dynamics.py")
        self.cognition = _load("cognition.py")
        self.safety = _load("safety.py")
        self.execution = _load("execution.py")
        self.accel = self.parallel.FeedforwardAccelerator()
        # 状态转移匹配物理: A=1.0 (位置保持) + B=dt (速度指令积分) — 默认 A=0.95 每步衰减
        # 会制造虚假残差 → 频繁否决; 物理自洽的预测器残差只来自真实扰动+传感器噪声
        self.est = self.parallel.AdaptiveStateEstimator(A=1.0, K=0.5, B=dt)
        self.dyn = self.dynamics.PriorDynamicsPredictor(A=1.0, B=dt)
        self.sched = self.cognition.CognitiveScheduler()
        self.execr = self.execution.RobotExecutor()
        self.world = self.execution.PhysicalWorld()
        # 物理世界状态
        self.x = X0.copy()
        self.v = np.zeros(3)
        self.gripper = 0.0
        self.latent = np.concatenate([self.x, [0.0]])   # 潜状态 4D: 位置3 + 预测接触力 (无接触=0)
        self.obs_prev = None                 # 上一帧 18D (帧堆叠)

    # ── 感知 ──
    def _build_obs(self, force):
        """构造 43D obs: 39D 视觉结构 (当前帧18 + 上一帧18 + 目标3) + 触觉4D"""
        cur = np.concatenate([
            self.x,                  # [0:3]  末端位置
            [self.gripper],          # [3]    夹爪开度
            self.v,                  # [4:7]  末端速度
            self.x,                  # [7:10] peg 位置 (末端携带)
            HOLE_POS,                # [10:13] 孔位
            np.zeros(3),             # [13:16] 孔位姿态 (简化)
            np.zeros(2),             # [16:18] 预留
        ])
        prev = self.obs_prev if self.obs_prev is not None else cur
        target = HOLE_POS
        visual39 = np.concatenate([cur, prev, target])
        tactile4 = np.array([self.gripper, float(self._contact), 0.0, 0.0])
        return self.perception.fuse_sensors(visual39, np.asarray(force, dtype=float), tactile4)

    @property
    def _contact(self):
        """接触判定: 末端-孔位水平距离 < 接触半径"""
        return float(np.linalg.norm(self.x[:2] - HOLE_POS[:2])) < D_CONTACT

    def _dist_h(self):
        return float(np.linalg.norm(self.x[:2] - HOLE_POS[:2]))

    # ── 主循环 ──
    def run(self, on_step=None):
        """跑完整仿真 (500 步 ≈ 0.1s 纯 numpy)。on_step(node_name, value_str) 每节点回调。"""
        tr = {"t": [], "dist": [], "u_ff": [], "residual": [], "contact_p": [],
              "u_sat": [], "stage": [], "done": [],
              "x": [], "gripper": [], "force": []}   # 🎥 2026-08-18: 完整轨迹 (视频渲染用)
        done = False
        t = 0.0
        n_steps = int(self.t_end / self.dt)
        for _ in range(n_steps):
            # ① 接触力 (物理世界给感知的输入; 归一化: 最大接触力 6*0.02=0.12N)
            force = np.zeros(6)
            if self._contact:
                force[2] = K_CONTACT * max(0.0, D_CONTACT - self._dist_h())  # 垂直接触力
            force_norm = float(np.clip(force[2] / (K_CONTACT * D_CONTACT), 0.0, 1.0))
            # ② 感知 → obs
            obs = self._build_obs(force)
            # ③ 快通道: 前馈建议
            u_ff = self.accel.forward(obs)
            act4 = np.concatenate([u_ff[:3], [0.0]])
            # ④ 慢通道: 状态估计先验 (4D: 位置 + 预测力)
            latent_pred = self.est.predict(self.latent, act4)
            # ⑤ 先验动力学预测 next_obs (4D)
            prior = self.dyn.predict(self.latent, act4)
            # ⑥ 物理世界观测 z_k (位置带噪声 + 力觉 — 接触力是残差真实来源)
            z_k = np.concatenate([self.world.observe(self.x), [force_norm]])
            # ⑦ 状态校正: 残差 + 接触概率
            corrected, residual = self.cognition.state_correction(prior, z_k, K=0.5)
            residual = np.asarray(residual, dtype=float).copy()
            # 力残差 = 实测接触力 (接触力是外部事件不可预测, 预测力恒 0 —
            # 若走卡尔曼平滑, 潜状态力维会吃掉残差 → 调度器收不到接触信号)
            residual[3] = force_norm
            r_scalar = float(np.linalg.norm(residual))
            contact_p = float(self.cognition.contact_probability(r_scalar, gain=8.0))
            # 后验: 潜状态更新 (卡尔曼)
            self.latent = self.est.update(latent_pred, corrected)
            # ⑧ 认知调度: 否决/融合 (慢通道反馈 u_fb = 位置校正方向)
            u_fb = np.concatenate([np.clip(0.5 * residual[:3], -0.5, 0.5), [0.0]])
            u, stage = self.sched.decide(u_ff, u_fb, contact_p, r_scalar)
            # 夹爪指令直通 (开关量不参与位置加权融合 — 权重稀释会夹不紧)
            if np.ndim(u) == 0:
                u = np.zeros(4)
            u = np.asarray(u, dtype=float).copy()
            u[3] = float(u_ff[3])
            # ⑨ 安全限幅 (位置/速度通道; 夹爪开关量不受限幅)
            u_sat = self.safety.saturate(u, limit=0.6)
            u_sat = np.asarray(u_sat, dtype=float).copy()
            u_sat[3] = float(u[3])
            # ⑩ 执行器 → 物理世界积分 (否决时 decide 返回标量 0 = 强制减速)
            u_vec = self.execr.execute(u_sat)
            if np.ndim(u_vec) == 0:
                u_vec = np.zeros(4)
            self.v += u_vec[:3] * self.dt
            self.x += self.v * self.dt
            # 接触阻尼: 孔壁阻挡横向移动 (真实物理 — 预测继续走 vs 观测被挡 = 残差来源)
            d = self._dist_h()
            if d < D_INSERT:
                self.v[:2] *= 0.3          # 插入区横向锁住 (对孔)
                self.v[2] *= 0.85          # 插入阻力 (防 z 过冲)
            elif d < D_CONTACT:
                self.v[:2] *= 0.75         # 孔沿摩擦阻尼
                self.v[2] *= 0.95
            g_cmd = float(u_vec[3])
            self.gripper += (g_cmd - self.gripper) * min(1.0, self.dt * 10.0)
            self.obs_prev = obs[0:18]
            # 阶段推进: 调度器状态机 (advance 证据驱动 — 接触概率/距离/夹爪/深度)
            d = self._dist_h()
            self.sched.advance(contact_p=contact_p, dist_h=d,
                               gripper=self.gripper, depth=d)
            done = self.sched.stage() == "完成"
            # 记录
            tr["t"].append(round(t, 3))
            tr["dist"].append(d)
            tr["u_ff"].append(float(np.linalg.norm(u_ff[:3])))
            tr["residual"].append(r_scalar)
            tr["contact_p"].append(contact_p)
            tr["u_sat"].append(float(np.linalg.norm(u_vec[:3])))
            tr["stage"].append(stage)
            tr["done"].append(done)
            tr["x"].append(self.x.copy())
            tr["gripper"].append(self.gripper)
            tr["force"].append(force_norm)
            if on_step:
                on_step("sensor", f"force_z={force[2]:+.3f}N")
                on_step("obs", f"obs 43D · hand={self.x.round(4)} · gripper={self.gripper:.2f}")
                on_step("ff", f"u_ff={np.round(u_ff, 3)}")
                on_step("est", f"latent_pred={np.round(latent_pred, 3)}")
                on_step("pred", f"prior={np.round(prior, 3)}")
                on_step("correct", f"r={r_scalar:.4f} · contact_p={contact_p:.3f} · x̂={np.round(corrected, 3)}")
                on_step("sched", f"{stage} · u={np.round(u, 3)}")
                on_step("limit", f"u_sat={np.round(u_sat, 3)}")
                on_step("act", f"v={np.round(self.v, 4)}")
                on_step("world", f"z_k={np.round(z_k, 3)} · dist={d:.4f}")
            t += self.dt
            if done:
                break
        return tr


def quick_run():
    """命令行快速验证: python3 state_space_sim.py"""
    sim = StateSpaceSim()
    tr = sim.run()
    print(f"完成: {tr['done'][-1]} · 用时 {tr['t'][-1]:.1f}s · 最终距离 {tr['dist'][-1]:.4f}")
    print(f"残差峰值 {max(tr['residual']):.4f} · 接触概率峰值 {max(tr['contact_p']):.3f}")
    print(f"阶段序列: {sorted(set(tr['stage']))}")
    return tr


if __name__ == "__main__":
    quick_run()
