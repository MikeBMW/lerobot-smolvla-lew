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


def _load_planner():
    """加载大模型层 planner.py (失败返回 None — 慢决策缺席不影响实时回路)"""
    try:
        return _load("planner.py")
    except Exception:
        return None


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
        self.sched = self.cognition.ActionModulator()
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
    def run(self, on_step=None, io_every=None):
        """跑完整仿真 (500 步 ≈ 0.1s 纯 numpy)。on_step(node_name, value_str) 每节点回调。
        io_every: 数据总线快照间隔(步) — 每 io_every 步(含最后一步)记录一次完整接口 I/O
                  到 tr['io_trace'] ([(t, io_dict), ...]); None = 不记录(仅保留最后一步)。"""
        # 🧠 大模型层 · 慢决策 (2026-08-20 老倪): 任务开始时规划一次, 不进实时回路
        self.planner = _load_planner()
        if self.planner is not None:
            try:
                tokens = self.planner.TaskPlanner().plan("插入光模块")
                self.log(f"🧠 任务规划器 (慢决策·回路外): 「插入光模块」 → {' '.join(tokens)}")
            except Exception as e:
                self.log(f"⚠️ 任务规划器: {e}")
        diag_done = False
        last_io = {}
        tr = {"t": [], "dist": [], "u_ff": [], "residual": [], "contact_p": [],
              "u_sat": [], "stage": [], "done": [],
              "x": [], "gripper": [], "force": [],
              "obs": [], "u_ff_vec": [], "u_sat_vec": [],   # 🎥 2026-08-18 完整轨迹 (视频); 2026-08-20 训练数据 (obs/u向量)
              # 🧭 2026-08-25 3D 视图 (Apollo 分层渲染): 每步完整处理层向量
              "u_fb_vec": [], "u_fuse_vec": [], "u_limit_vec": [], "u_exec_vec": [],
              "latent_vec": [], "corrected_vec": [], "residual_vec": [], "z_k_vec": [], "v_vec": [],
              "io_trace": []}   # 🔌 2026-08-22 数据总线快照序列 [(t, io_dict), ...] (CANoe Trace 风格)
        done = False
        t = 0.0
        n_steps = int(self.t_end / self.dt)
        for step in range(n_steps):
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
            tr["obs"].append(obs.copy())
            tr["u_ff_vec"].append(np.asarray(u_ff, dtype=float).copy())
            tr["u_sat_vec"].append(np.asarray(u_vec, dtype=float).copy())
            # 🧭 2026-08-25 3D 视图: 每步完整处理层向量 (Apollo 分层渲染数据源)
            tr["u_fb_vec"].append(np.asarray(u_fb, dtype=float).copy())
            tr["u_fuse_vec"].append(np.asarray(u, dtype=float).copy())       # 动作调制器输出 (融合指令 u)
            tr["u_limit_vec"].append(np.asarray(u_sat, dtype=float).copy())  # 安全限幅输出
            tr["u_exec_vec"].append(np.asarray(u_vec, dtype=float).copy())   # 执行器输出
            tr["latent_vec"].append(np.asarray(self.latent, dtype=float).copy())
            tr["corrected_vec"].append(np.asarray(corrected, dtype=float).copy())
            tr["residual_vec"].append(np.asarray(residual, dtype=float).copy())
            tr["z_k_vec"].append(np.asarray(z_k, dtype=float).copy())
            tr["v_vec"].append(np.asarray(self.v, dtype=float).copy())
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
            # 🔍 大模型层 · 异常推理 (慢决策·回路外): 连续否决达上限 → 诊断一次
            if not diag_done and self.planner is not None and self.sched.veto_count >= self.sched.max_veto:
                diag_done = True
                try:
                    kind, advice = self.planner.ExceptionReasoner().diagnose(
                        stage=stage, residual=r_scalar, contact_p=contact_p,
                        dist_h=d, veto_count=self.sched.veto_count,
                        max_veto=self.sched.max_veto)
                    self.log(f"🔍 异常推理器 (慢决策·回路外): {kind} — {advice}")
                except Exception as e:
                    self.log(f"⚠️ 异常推理器: {e}")
            # 📊 信号快照 (Simulink 风格全量监控 — 每模块 I/O 变量)
            last_io = self._io_snapshot(force, obs, u_ff, act4, latent_pred, prior, z_k,
                                        corrected, residual, contact_p, r_scalar,
                                        u_fb, u, stage, u_sat, u_vec, force_norm, step)
            # 🔌 数据总线 (CANoe Trace 风格, 2026-08-22 老倪): 抽样记录完整接口时序
            if io_every is not None and (step % io_every == 0 or done):
                tr["io_trace"].append((round(t, 3), last_io))
            t += self.dt
            if done:
                break
        tr["io"] = last_io
        return tr

    def _io_snapshot(self, force, obs, u_ff, act4, latent_pred, prior, z_k,
                     corrected, residual, contact_p, r_scalar, u_fb, u, stage,
                     u_sat, u_vec, force_norm, frame_id=0):
        """📊 单步接口 I/O 快照 — 「🔌 数据总线」数据源 (2026-08-22 老倪)
        九模块 in/out 完整变量; 数值为 numpy 数组 (每步新建, 引用安全不覆盖)。"""
        visual39 = obs[:39]
        tactile4 = obs[39:43]
        peg_3d = self.x
        hole_3d = HOLE_POS
        img = f"RGB-D 640×480 · 帧#{frame_id}"
        return {
            "📦 metaworld 数据源": {
                "in": [],
                "out": [("图像流 (RGB-D)", img),
                       ("状态流 39D", visual39)],
            },
            "🎯 YOLO 目标检测": {
                "in": [("图像流 (RGB-D)", img)],
                "out": [("peg 检测框 2D", f"xy=({peg_3d[0]:.3f},{peg_3d[1]:.3f}) conf 0.99"),
                       ("hole 检测框 2D", f"xy=({hole_3d[0]:.3f},{hole_3d[1]:.3f}) conf 0.99"),
                       ("hand 检测框 2D", f"xy=({peg_3d[0]:.3f},{peg_3d[1]:.3f}) conf 0.99")],
            },
            "📐 2D→3D 解算": {
                "in": [("检测框 2D", "peg/hole/hand")],
                "out": [("peg 3D 坐标", peg_3d),
                       ("hole 3D 坐标", hole_3d),
                       ("hand 3D 坐标", peg_3d)],
            },
            "🖐 触觉感知": {
                "in": [],
                "out": [("触觉 4D (夹爪/接触/方向)", tactile4)],
            },
            "🔍 外观质量检测": {
                "in": [("检测区域 (金手指/端面)", "YOLO 检测区域")],
                "out": [("质量门", "Pass")],
            },
            "📡 传感器融合": {
                "in": [("视觉 rgbd_feats (39D: 当前18+上一18+目标3)", obs[:39]),
                       ("力觉 force (6D: 接触检测用, 不进obs)", force),
                       ("触觉 tactile (4D: 夹爪/接触/0/0)", obs[39:43])],
                "out": [("观测 obs (43D)", obs),
                       ("  ├ 视觉39 (当前18+上一18+目标3)", obs[:39]),
                       ("  │  ├ 当前帧 cur (18D)", obs[:18]),
                       ("  │  ├ 上一帧 prev (18D)", obs[18:36]),
                       ("  │  └ 目标 target (3D)", obs[36:39]),
                       ("  └ 触觉4 (夹爪/接触/0/0)", obs[39:43])],
            },
            "⚡ 前馈加速器": {
                "in": [("观测 obs (43D)", obs)],
                "out": [("前馈指令 u_ff (4D:位置3+夹爪1)", u_ff)],
            },
            "🔮 自适应状态估计器": {
                "in": [("潜状态 latent (4D:位置3+预测力)", self.latent), ("动作 act (4D)", act4)],
                "out": [("先验估计 latent_pred (4D)", latent_pred)],
            },
            "📈 先验动力学预测器": {
                "in": [("潜状态 latent (4D)", self.latent), ("动作 act (4D)", act4)],
                "out": [("预测 next_obs prior (4D)", prior)],
            },
            "🧪 状态校正器": {
                "in": [("先验 prior (4D)", prior), ("物理观测 z_k (4D:位置3+力)", z_k)],
                "out": [("后验 corrected (4D)", corrected), ("残差 residual (4D)", residual),
                       ("接触概率 contact_p (标量)", contact_p)],
            },
            "🧭 动作调制器": {
                "in": [("前馈 u_ff (4D)", u_ff), ("反馈 u_fb (4D)", u_fb),
                       ("接触概率 contact_p (标量)", contact_p), ("残差范数 r (标量)", r_scalar)],
                "out": [("融合指令 u (4D)", u), ("阶段 stage (str)", stage)],
            },
            "🛡 安全限幅": {
                "in": [("指令 u (4D)", u)],
                "out": [("限幅后 u_sat (4D)", u_sat)],
            },
            "🤖 执行器": {
                "in": [("限幅后 u_sat (4D)", u_sat)],
                "out": [("速度指令 u_vec (4D)", u_vec)],
            },
            "🌍 物理世界": {
                "in": [("速度指令 u_vec (4D)", u_vec)],
                "out": [("末端位置 x (3D)", self.x), ("末端速度 v (3D)", self.v),
                       ("夹爪 gripper (标量)", self.gripper), ("接触力 norm (标量)", force_norm),
                       ("观测 z_k (4D:位置3+力)", z_k)],
            },
        }


def quick_run():
    """命令行快速验证: python3 state_space_sim.py"""
    sim = StateSpaceSim()
    tr = sim.run()
    print(f"完成: {tr['done'][-1]} · 用时 {tr['t'][-1]:.1f}s · 最终距离 {tr['dist'][-1]:.4f}")
    print(f"残差峰值 {max(tr['residual']):.4f} · 接触概率峰值 {max(tr['contact_p']):.3f}")
    print(f"阶段序列: {sorted(set(tr['stage']))}")
    return tr


# ── 🧮 仿真 → 训练数据集 (2026-08-20 老倪: 状态空间接入训练流程) ──
_DATASET_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "ss_insert")


def export_dataset(n_episodes=8, seed_base=100, out_dir=None, log=None):
    """多轮仿真 (起始扰动+噪声 seed) → 专家演示数据集 npz

    对齐 on_train 训练管道数据包格式:
      states  (n,39) 39D 视觉结构 obs (当前18+上一18+目标3, 无触觉)
      actions (n,4)  u_ff 前馈建议 (左脑MLP 学习目标 — 训练学仿真里的前馈)
      stages  (n,)   阶段标签 (信息, 不参与训练)
      success (n_ep,) 每轮完成标志
      task_name "ss_insert" · fps 50 (DT=0.02)

    Returns: (npz路径, 总帧数, 成功轮数/总轮数)
    """
    import time as _time
    out_dir = out_dir or _DATASET_DIR
    os.makedirs(out_dir, exist_ok=True)
    if log:
        log(f"🧮 仿真数据集生成: {n_episodes} 轮 (seed {seed_base}~{seed_base + n_episodes - 1})")
    all_s, all_a, all_st = [], [], []
    n_ok = 0
    for ep in range(n_episodes):
        sim = StateSpaceSim(log=lambda *a: None)
        np.random.seed(seed_base + ep)
        # 起始扰动: 末端位置抖动 ±10mm (真实产线来料偏差)
        sim.x = X0 + np.array([np.random.uniform(-0.01, 0.01),
                               np.random.uniform(-0.01, 0.01), 0.0])
        sim.v = np.zeros(3)
        sim.gripper = 0.0
        sim.latent = np.concatenate([sim.x, [0.0]])
        sim.obs_prev = None
        tr = sim.run()
        obs = np.asarray(tr["obs"], dtype=np.float32)
        u_ff = np.asarray(tr["u_ff_vec"], dtype=np.float32)
        # 39D = 43D 去触觉 (触觉4D在末尾 [39:43])
        states = obs[:, :39]
        all_s.append(states)
        all_a.append(u_ff)
        all_st.extend(tr["stage"])
        ok = bool(tr["done"][-1])
        n_ok += 1 if ok else 0
        if log:
            log(f"   ep{ep + 1}: {len(tr['t'])} 帧 · {'✅ 完成' if ok else '⚠️ 未完成'} "
                f"({tr['t'][-1]:.1f}s · dist {tr['dist'][-1]:.4f})")
    S = np.concatenate(all_s)
    A = np.concatenate(all_a)
    ts = _time.strftime("%Y%m%d_%H%M%S")
    path = os.path.join(out_dir, f"ss_insert_{ts}.npz")
    np.savez_compressed(path, states=S, actions=A,
                        stages=np.asarray(all_st, dtype=object),
                        success=np.asarray([1 if i < n_ok else 0 for i in range(len(all_s))]),
                        task_name="ss_insert", fps=50)
    if log:
        log(f"📥 数据集已生成: {path} · 总 {len(S)} 帧 · 成功 {n_ok}/{n_episodes} 轮")
        log(f"   状态 {S.shape[1]}D · 动作 {A.shape[1]}D · 可训练 (data_source=ss_sim)")
    return path, len(S), (n_ok, n_episodes)


def load_trained_left_brain(npz_path):
    """加载训练模型 numpy 权重 → 返回 ff_forward(obs) 纯 numpy 前馈 (无 torch)

    复现 ss_verify_trained.py 的 torch 推理: 归一化 → 4层 MLP(Linear+ReLU) → 反归一化。
    Dropout 在 eval 模式关闭 = 推理恒等跳过。夹爪开关量规则控制 (同 torch 版)。
    """
    d = np.load(npz_path)
    W = [d[f"W{i}"] for i in range(4)]
    b = [d[f"b{i}"] for i in range(4)]
    sm, ss = d["sm"], d["ss"]
    am, astd = d["am"], d["astd"]

    def ff_forward(obs):
        x = (np.asarray(obs[:39], dtype=np.float32) - sm) / ss
        for i in range(3):
            x = np.maximum(0.0, W[i] @ x + b[i])   # Linear + ReLU (Dropout eval 关闭跳过)
        u_norm = W[3] @ x + b[3]                    # 最后一层无 ReLU
        u_xyz = np.clip(u_norm[:3] * astd[:3] + am[:3], -0.6, 0.6)
        pos = np.asarray(obs[:3], dtype=float)
        target = np.asarray(obs[36:39], dtype=float)
        dist_h = float(np.linalg.norm(pos[:2] - target[:2]))
        u_grip = 1.0 if dist_h < 0.03 else 0.0
        return np.concatenate([u_xyz, [u_grip]])

    return ff_forward


if __name__ == "__main__":
    quick_run()
