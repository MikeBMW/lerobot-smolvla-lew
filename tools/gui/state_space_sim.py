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


def _find_ss_dir():
    """定位 state_space 六层源码目录 — 多候选探测 (env → frozen _MEIPASS → 上溯三级 → 向上逐级找仓库根)

    🐛 2026-08-26: Windows exe / 绿色版运行时 __file__ 在 AppData 解压目录,
    上溯三级拼出 C:\\Users\\Admin\\AppData\\Local\\src\\... (不存在) → FileNotFoundError。
    改为逐级向上探测, 找到含 perception.py 的仓库根为止。
    """
    rel = os.path.join("src", "lerobot", "policies", "left_right", "state_space")
    cands = []
    _root_env = os.environ.get("ZMAX_REPO_ROOT")
    if _root_env and os.path.isdir(_root_env):
        cands.append(os.path.join(_root_env, rel))
    if getattr(sys, "frozen", False):
        cands.append(os.path.join(getattr(sys, "_MEIPASS", ""), rel))
    # __file__ 上溯三级 (源码仓库内) — 保底候选
    cands.append(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                              "src", "lerobot", "policies", "left_right", "state_space"))
    # 向上逐级探测仓库根 (tools/gui 被复制到任意位置也能找到 src/ 同级目录)
    d = os.path.dirname(os.path.abspath(__file__))
    while True:
        cands.append(os.path.join(d, rel))
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    for c in cands:
        if os.path.isfile(os.path.join(c, "perception.py")):
            return c
    raise FileNotFoundError(
        "state_space 六层源码目录未找到 (已探测: " + " ; ".join(dict.fromkeys(cands)) +
        ")。请设置环境变量 ZMAX_REPO_ROOT 指向仓库根, 或从仓库内运行。")


_SS_DIR = _find_ss_dir()


def _find_mani_file():
    """定位流形层源码 manifold_layer.py (与六层同探测策略)"""
    rel = os.path.join("src", "lerobot", "manifold", "manifold_layer.py")
    cands = []
    _root_env = os.environ.get("ZMAX_REPO_ROOT")
    if _root_env and os.path.isdir(_root_env):
        cands.append(os.path.join(_root_env, rel))
    if getattr(sys, "frozen", False):
        cands.append(os.path.join(getattr(sys, "_MEIPASS", ""), rel))
    d = os.path.dirname(os.path.abspath(__file__))
    while True:
        cands.append(os.path.join(d, rel))
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    for c in cands:
        if os.path.isfile(c):
            return c
    return None   # 无流形层 → 流形 channel 跳过 (不阻塞引擎)

_MANI_FILE = _find_mani_file()


def _load_manifold():
    """直载 manifold_layer (纯 numpy; 失败返回 None 不阻塞引擎)"""
    if not _MANI_FILE:
        return None
    try:
        spec = importlib.util.spec_from_file_location("state_space_mani", _MANI_FILE)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m
    except Exception:
        return None


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


# ════════════════════════════════════════════════════════════════
# 物理世界模型参数 (光模块插拔) — 2026-08-25 老倪: 全部换成 metaworld
# peg-insert-side-v3 (操作视频 gen_insert_video.py 用的同一个环境) 的真实几何,
# 实测来源 tools/probe_video_view.py / probe_scene_geom.py (seed 0 复位后):
#   末端 endEffector (0.0043, 0.6014, 0.1551) / obs 末端 (0.0046,0.6014,0.1951)
#   插销抓握点 pegGrasp (0.0966, 0.5191, 0.030), 插销头 pegHead (-0.0334, 0.5191, 0.020)
#   孔口 hole (-0.1685, 0.4623, 0.1309), 插入终点 goal (-0.2345, 0.4623, 0.1309)
# 原来这里是编造坐标 (孔位 0.25,0,0.05), 与操作视频既不同尺度也不同朝向。
# ════════════════════════════════════════════════════════════════
HOLE_POS = np.array([-0.2345, 0.4623, 0.1309])   # 插入终点 (metaworld goal, obs[36:39] 语义)
HOLE_MOUTH = np.array([-0.1685, 0.4623, 0.1309])  # 孔口 (侧插入口)
PEG_POS0 = np.array([0.0966, 0.5191, 0.030])      # 插销抓握点初始 (台面上)
PEG_HEAD_OFF = np.array([-0.130, 0.0, -0.010])    # 插销头相对抓握点 (peg 沿 X 长 0.2)
X0 = np.array([0.0046, 0.6014, 0.1951])           # 末端起始位置 (手空着, 未持插销)
TABLE_Z = 0.005                                   # 台面高度 (插销底面)
D_CONTACT = 0.02                          # 接触距离 (下降触销 / 销到孔沿)
D_INSERT = 0.004                          # 插入成功判定
K_CONTACT = 6.0                           # 接触力增益
DT = 0.02
T_END = 32.0                              # 完整插拔 (接近→对位→下降→抓取→抬起→转移→插入→完成) 需要更长
# 各阶段末端子目标 (感知层把"当前阶段目标"写进 obs[36:39] — 前馈层就是按它比例引导)
STAGE_LIFT = 0.16                         # 抬起目标高度 (台面之上)
STAGE_APPROACH_H = 0.09                   # 接近: 插销上方悬停高度
STAGE_ALIGN_H = 0.05                      # 对位: 精对位高度
STAGE_DESCEND_H = 0.004                   # 下降: 贴到抓握点


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
        # 🐛 2026-08-25 老倪「自适应状态估计的输出为什么这么乱」实测: 观测噪声 5mm/轴,
        #   K=0.5 等于一半直接跟噪声走 → 估计每步抖 2.17mm 而末端真实每步只走 0.29mm
        #   (抖动 = 真实运动的 7.4 倍, 画成轨迹线就是乱麻)。离线重放实测:
        #   K=0.5→误差3.01mm/抖动2.19mm, K=0.3→2.30/1.31, K=0.15→1.68/0.71
        #   取 K=0.2 折中 (误差≈2.0mm, 抖动≈1.0mm/步, 仍保留对真实运动的跟随)
        self.est = self.parallel.AdaptiveStateEstimator(A=1.0, K=0.2, B=dt)
        self.u_prev = np.zeros(4)      # 上一步"实际下发"的控制量 (卡尔曼预测必须用它)
        self.dyn = self.dynamics.PriorDynamicsPredictor(A=1.0, B=dt)
        self.sched = self.cognition.ActionModulator()
        self.execr = self.execution.RobotExecutor()
        self.world = self.execution.PhysicalWorld()
        # 物理世界状态
        self.x = X0.copy()
        self.v = np.zeros(3)
        self.gripper = 0.0
        # 🔩 2026-08-25 老倪: 插销是独立物体 (原来 obs 里 peg 位置=末端, 等于"开局就握着销",
        #   3D 视图因此没有「从初始位置到抓取插销」的过程)。现在插销先躺在台面上,
        #   抓取阶段夹爪闭合后才随手移动 (self.grasped / self.peg_off)。
        self.peg = PEG_POS0.copy()      # 插销抓握点世界坐标
        self.grasped = False            # 是否已夹住
        self.peg_off = np.zeros(3)      # 夹住瞬间 插销-末端 的相对偏移
        self.latent = np.concatenate([self.x, [0.0]])   # 潜状态 4D: 位置3 + 预测接触力 (无接触=0)
        self.obs_prev = None                 # 上一帧 18D (帧堆叠)
        # 🧮 流形层逐帧发布 (2026-09-03): 接触/性能流形 channel 进数据世界 (缺失不阻塞)
        self._mani = _load_manifold()
        self._mani_cm = self._mani.ContactManifold() if self._mani else None
        self._mani_pm = self._mani.PerformanceManifold() if self._mani else None
        self._mani_out = None                # 本步流形量 (io_snapshot 发布用)

    def _head_off(self):
        """销头相对末端的真实偏移 — 夹持后由感知给出 (peg 位置 − 末端位置 + 销头偏移)。
        ⚠️ 不能用名义 PEG_HEAD_OFF: 抓取锁存发生在"手比抓握点高 12mm"时 (接触判据),
        用名义偏移算插入目标会残留 12mm 高度差 → 永远差最后 4mm 判定不了「完成」。"""
        if self.grasped:
            return self.peg_head() - self.x
        return PEG_HEAD_OFF.copy()

    # ── 阶段子目标 (感知层写进 obs[36:39], 前馈层按它比例引导) ──
    def _stage_target(self):
        """当前阶段的末端目标位置 — 八阶段插拔流程:
        接近(销上方悬停) → 对位(降到精对位高度) → 下降(贴抓握点) → 抓取(原地闭合)
        → 抬起(提到 STAGE_LIFT) → 转移(销头对准孔口上方) → 插入(销头推到 goal) → 完成"""
        st = self.sched.stage()
        if st == "接近":
            return self.peg + np.array([0.0, 0.0, STAGE_APPROACH_H])
        if st == "对位":
            return self.peg + np.array([0.0, 0.0, STAGE_ALIGN_H])
        if st == "下降":
            return self.peg + np.array([0.0, 0.0, STAGE_DESCEND_H])
        if st == "抓取":
            return self.peg.copy()
        if st == "抬起":
            return np.array([self.peg[0], self.peg[1], TABLE_Z + STAGE_LIFT])
        if st == "转移":
            # 末端目标 = 让"销头"落在孔口正前方上方 2cm (末端 = 孔口 − 真实夹持偏移)
            return HOLE_MOUTH - self._head_off() + np.array([0.0, 0.0, 0.02])
        if st == "插入":
            return HOLE_POS - self._head_off()
        return HOLE_POS - self._head_off()     # 完成: 保持在插入终点

    def peg_head(self):
        """插销头世界坐标 (插入端)"""
        return self.peg + PEG_HEAD_OFF

    def _d_xy_peg(self):
        """末端-插销抓握点 水平距离 (接近/对位/下降 的推进证据)"""
        return float(np.linalg.norm(self.x[:2] - self.peg[:2]))

    def _d_hole_h(self):
        """插销头-孔口 水平距离 (转移→插入 的推进证据)"""
        return float(np.linalg.norm(self.peg_head()[:2] - HOLE_MOUTH[:2]))

    def _insert_depth(self):
        """插销头到插入终点距离 (插入→完成 的推进证据)"""
        return float(np.linalg.norm(self.peg_head() - HOLE_POS))

    # ── 感知 ──
    def _build_obs(self, force):
        """构造 43D obs: 39D 视觉结构 (当前帧18 + 上一帧18 + 目标3) + 触觉4D"""
        cur = np.concatenate([
            self.x,                  # [0:3]  末端位置
            [self.gripper],          # [3]    夹爪开度
            self.v,                  # [4:7]  末端速度
            self.peg,                # [7:10] 插销位置 (独立物体, 抓取后才随末端)
            HOLE_POS,                # [10:13] 孔位 (插入终点)
            np.zeros(3),             # [13:16] 孔位姿态 (简化)
            np.zeros(2),             # [16:18] 预留
        ])
        prev = self.obs_prev if self.obs_prev is not None else cur
        target = self._stage_target()   # [36:39] 当前阶段子目标 (八阶段插拔)
        visual39 = np.concatenate([cur, prev, target])
        tactile4 = np.array([self.gripper, float(self._contact), 0.0, 0.0])
        return self.perception.fuse_sensors(visual39, np.asarray(force, dtype=float), tactile4)

    @property
    def _contact(self):
        """接触判定 (按阶段): 未夹持 = 末端下降触到插销; 已夹持 = 销头触到孔沿"""
        if not self.grasped:
            return (self._d_xy_peg() < 0.03
                    and (self.x[2] - self.peg[2]) < 0.012)
        return self._d_hole_h() < D_CONTACT

    def _dist_h(self):
        """当前"到目标"的水平距离 (Scope 波形 dist 曲线): 未夹持看插销, 已夹持看孔口"""
        return self._d_xy_peg() if not self.grasped else self._d_hole_h()

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
              # 🔩 2026-08-25 完整插拔: 插销独立轨迹 + 每步阶段子目标 (3D 视图渲染用)
              "peg": [], "peg_head": [], "target": [], "grasped": [],
              "obs": [], "u_ff_vec": [], "u_sat_vec": [],   # 🎥 2026-08-18 完整轨迹 (视频); 2026-08-20 训练数据 (obs/u向量)
              # 🧭 2026-08-25 3D 视图 (Apollo 分层渲染): 每步完整处理层向量
              "u_fb_vec": [], "u_fuse_vec": [], "u_limit_vec": [], "u_exec_vec": [],
              "latent_vec": [], "corrected_vec": [], "residual_vec": [], "z_k_vec": [], "v_vec": [],
              # 📈 先验动力学预测器输出 (2026-08-25 老倪: 六层每层都要能在 3D 视图看到)
              "prior_vec": [],
              # 🧮 2026-09-03 流形层逐帧序列 (Scope 全程曲线/验证层数据源)
              "mani_risk": [], "mani_progress": [], "mani_eta": [], "mani_V": [],
              "io_trace": []}   # 🔌 2026-08-22 数据总线快照序列 [(t, io_dict), ...] (CANoe Trace 风格)
        done = False
        t = 0.0
        n_steps = int(self.t_end / self.dt)
        for step in range(n_steps):
            # ① 接触力 (物理世界给感知的输入; 归一化: 最大接触力 6*0.02=0.12N)
            #   未夹持: 下降触到插销 → 垂直反力 (证据: 可以闭合夹爪了)
            #   已夹持: 销头触到孔沿 → 插入阻力 (证据: 对上孔了)
            force = np.zeros(6)
            if self._contact:
                if not self.grasped:
                    gap_z = max(0.0, 0.012 - (self.x[2] - self.peg[2]))
                    force[2] = K_CONTACT * max(gap_z, 0.5 * D_CONTACT)
                else:
                    force[2] = K_CONTACT * max(0.0, D_CONTACT - self._d_hole_h())
            force_norm = float(np.clip(force[2] / (K_CONTACT * D_CONTACT), 0.0, 1.0))
            # ② 感知 → obs
            obs = self._build_obs(force)
            # ③ 快通道: 前馈加速器
            u_ff = self.accel.forward(obs)
            # 🐛 卡尔曼预测的控制输入必须是**上一步真正下发给执行器的量** (u_exec),
            #   原来用 u_ff (前馈建议) — 实测两者模长差 3.12 倍 ⇒ 预测拿"没执行的动作"外推,
            #   凭空制造预测误差 (离线重放: 改用 u_exec 后误差 3.60→3.01mm)
            act4 = np.concatenate([self.u_prev[:3], [0.0]])
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
            # 🌫 反馈用**滤波后**的残差: 瞬时残差 96% 是观测噪声 (相邻帧方向变化 88.5°),
            #   直接反馈等于把噪声注入指令 → EMA (α=0.15, ≈10 步时间常数) 只留系统性偏差
            self.res_ema = (0.85 * self.res_ema + 0.15 * np.asarray(residual, dtype=float)
                            if getattr(self, "res_ema", None) is not None
                            else np.asarray(residual, dtype=float).copy())
            u_fb = np.concatenate([np.clip(0.5 * self.res_ema[:3], -0.5, 0.5), [0.0]])
            u, stage = self.sched.decide(u_ff, u_fb, contact_p, r_scalar)
            # 夹爪指令直通 (开关量不参与位置加权融合 — 权重稀释会夹不紧)
            if np.ndim(u) == 0:
                u = np.zeros(4)
            u = np.asarray(u, dtype=float).copy()
            # 夹爪指令 = 调度器夹持保持 (抓取阶段起锁存闭合; 之前听前馈近距闭合)
            u[3] = self.sched.gripper_cmd(u_ff[3])
            # ⑨ 安全限幅 (位置/速度通道; 夹爪开关量不受限幅)
            u_sat = self.safety.saturate(u, limit=0.6)
            u_sat = np.asarray(u_sat, dtype=float).copy()
            u_sat[3] = float(u[3])
            # ⑩ 执行器 → 物理世界积分 (否决时 decide 返回标量 0 = 强制减速)
            u_vec = self.execr.execute(u_sat)
            if np.ndim(u_vec) == 0:
                u_vec = np.zeros(4)
            self.u_prev = np.asarray(u_vec, dtype=float).copy()   # 供下一步卡尔曼预测用
            # 🐛 2026-08-25 老倪 (物理层语义 bug): u 是**速度指令** (前馈层 Kp·(target−pos) 限幅 ±0.5 m/s,
            #   状态估计器 predict 也是 latent + dt·u 按速度积分), 但这里原本按**加速度**积分
            #   (v += u·dt) → 双积分无阻尼系统: 位置比例控制必然过冲/发散 (实测末端冲到
            #   x=-0.37 越过孔位 0.13m 停不下来), 同时给估计器制造假残差。
            #   改为一阶速度伺服 (真实执行器惯性): v ← v + (u − v)·dt/τ, τ=0.08s
            tau = 0.08
            self.v += (u_vec[:3] - self.v) * min(1.0, self.dt / tau)
            self.x += self.v * self.dt
            # 台面约束: 未夹持时末端不能穿透台面 (真实物理 — 下降到抓握高度就停)
            if not self.grasped and self.x[2] < self.peg[2] - 0.002:
                self.x[2] = self.peg[2] - 0.002
                self.v[2] = max(0.0, self.v[2])
            # 接触阻尼 (真实物理 — 预测继续走 vs 观测被挡 = 残差来源)
            if self.grasped:
                dh = self._d_hole_h()
                if dh < D_INSERT:
                    self.v[1] *= 0.3           # 插入区侧向锁住 (对孔, 侧插沿 -X)
                    self.v[2] *= 0.85
                elif dh < D_CONTACT:
                    self.v[1] *= 0.75          # 孔沿摩擦阻尼
                    self.v[2] *= 0.95
            # 🔩 夹持锁存: 抓取阶段夹爪闭到 0.5 以上 → 插销被夹住, 之后随末端一起走
            g_cmd = float(u_vec[3])
            if (not self.grasped) and self.sched.stage() == "抓取" and self.gripper > 0.5:
                self.grasped = True
                self.peg_off = self.peg - self.x
                self.log(f"🔩 插销已夹住 (gripper={self.gripper:.2f}) → 随末端移动")
            self.gripper += (g_cmd - self.gripper) * min(1.0, self.dt * 10.0)
            if self.grasped:
                self.peg = self.x + self.peg_off
            self.obs_prev = obs[0:18]
            # 阶段推进: 调度器状态机 (八阶段 · 证据驱动 — 水平距离/接触概率/夹爪/提起高度/插入深度)
            d = self._dist_h()
            self.sched.advance(contact_p=contact_p, dist_h=self._d_hole_h(),
                               gripper=self.gripper, depth=self._insert_depth(),
                               d_xy=self._d_xy_peg(), lifted=self.peg[2] - PEG_POS0[2],
                               # 🛟 夹持丢失回退证据 (numpy 引擎无真实力 → 用夹持状态代理)
                               grasp_force=(1.0 if self.grasped else 0.0),
                               peg_z=float(self.peg[2]), peg_z_grasp=float(PEG_POS0[2]))
            done = self.sched.stage() == "完成"
            # 记录
            tr["t"].append(round(t, 3))
            tr["dist"].append(d)
            tr["u_ff"].append(float(np.linalg.norm(u_ff[:3])))
            tr["residual"].append(r_scalar)
            tr["contact_p"].append(contact_p)
            tr["u_sat"].append(float(np.linalg.norm(u_vec[:3])))
            # 阶段标签取"本步结束时"的状态机阶段 (decide() 的文本是本步开始时的阶段,
            # 会导致最后一帧显示「插入」而实际已进入「完成」→ 3D 视图/波形看不到完成段)
            tr["stage"].append(stage if self.sched.stage() in stage
                               else f"阶段 {self.sched.stage()}")
            tr["done"].append(done)
            # 🧮 流形层逐帧发布 (2026-09-03): 接触/性能流形每步实算 → io channel + 全程序列
            _ms = str(tr["stage"][-1]).replace("阶段 ", "").split("·")[0].strip()
            if self._mani_cm is not None:
                try:
                    _mc = self._mani_cm.decompose(self.x, self.peg_head(),
                                                  self._stage_target(), self.v, _ms)
                    _mp = self._mani_pm.evaluate(self.peg_head(), stage=_ms)
                    self._mani_out = {"cm": _mc, "pm": _mp,
                                      "lat": np.asarray(self.latent, dtype=float),
                                      "vel": (np.asarray(prior, dtype=float)
                                              - np.asarray(latent_pred, dtype=float))}
                    tr["mani_risk"].append(float(_mc["risk"]))
                    tr["mani_progress"].append(float(_mc["progress"]))
                    tr["mani_eta"].append(float(_mp["eta"]))
                    tr["mani_V"].append(float(_mc["V"]))
                except Exception:
                    self._mani_out = None
                    tr["mani_risk"].append(0.0); tr["mani_progress"].append(0.0)
                    tr["mani_eta"].append(0.0); tr["mani_V"].append(0.0)
            else:
                tr["mani_risk"].append(0.0); tr["mani_progress"].append(0.0)
                tr["mani_eta"].append(0.0); tr["mani_V"].append(0.0)
            tr["x"].append(self.x.copy())
            tr["gripper"].append(self.gripper)
            tr["force"].append(force_norm)
            tr["peg"].append(self.peg.copy())
            tr["peg_head"].append(self.peg_head().copy())
            tr["target"].append(np.asarray(self._stage_target(), dtype=float).copy())
            tr["grasped"].append(bool(self.grasped))
            tr["obs"].append(obs.copy())
            tr["u_ff_vec"].append(np.asarray(u_ff, dtype=float).copy())
            tr["u_sat_vec"].append(np.asarray(u_vec, dtype=float).copy())
            # 🧭 2026-08-25 3D 视图: 每步完整处理层向量 (Apollo 分层渲染数据源)
            tr["u_fb_vec"].append(np.asarray(u_fb, dtype=float).copy())
            tr["u_fuse_vec"].append(np.asarray(u, dtype=float).copy())       # 动作调制器输出 (融合指令 u)
            tr["u_limit_vec"].append(np.asarray(u_sat, dtype=float).copy())  # 安全限幅输出
            tr["u_exec_vec"].append(np.asarray(u_vec, dtype=float).copy())   # 执行器输出
            tr["prior_vec"].append(np.asarray(prior, dtype=float).copy())
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
            # 🔌 数据世界 (DataWorld / Dreamview channel 语义, 2026-09-03 v3.4.6):
            #   每步全量 append — tr["io_trace"] = 逐帧全模块 I/O 历史 (画布节点名=模块 key),
            #   画布播放/3D视图/数据总线消费同一帧序列 → 严格同帧同步。
            #   (io_every 参数保留兼容, 已不再抽稀 — 帧全量才支持逐引擎步同步渲染)
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
        # 🧮 流形 channel (2026-09-03): 本步流形量 (主循环算好存 self._mani_out)
        _mo = getattr(self, "_mani_out", None) or {}
        _mc = _mo.get("cm") or {}
        _mp = _mo.get("pm") or {}
        _lat = _mo.get("lat", np.zeros(4))
        _vel = _mo.get("vel", np.zeros(4))
        visual39 = obs[:39]
        tactile4 = obs[39:43]
        peg_3d = self.peg            # 🐛 2026-09-03: 独立插销位置 (原误用 self.x 末端)
        hand_3d = self.x             # 末端执行器 = hand
        hole_3d = HOLE_POS
        img = f"RGB-D 640×480 · 帧#{frame_id}"
        # 🐛 2026-09-03 老倪: YOLO/2D→3D 快照不再写死 conf 0.99 伪装检测 (老倪红线);
        #   hand 也不再抄 peg 坐标. 引擎无 YOLO 模型 → conf 标 "--"; ▶运行 后由
        #   simulink_module 注入真实 detect_3d/detect2d 采样值 (真实 conf/框/3D)。
        return {
            "📦 metaworld 数据源": {
                "in": [],
                "out": [("图像流 (RGB-D)", img),
                       ("状态流 39D", visual39)],
            },
            "🎯 YOLO 目标检测": {
                "in": [("图像流 (RGB-D)", img)],
                "out": [("peg 检测框 2D", f"xy=({peg_3d[0]:.3f},{peg_3d[1]:.3f}) conf --"),
                       ("hole 检测框 2D", f"xy=({hole_3d[0]:.3f},{hole_3d[1]:.3f}) conf --"),
                       ("hand 检测框 2D", f"xy=({hand_3d[0]:.3f},{hand_3d[1]:.3f}) conf --")],
            },
            "📐 2D→3D 解算": {
                "in": [("检测框 2D", "peg/hole/hand")],
                "out": [("peg 3D 坐标", peg_3d),
                       ("hole 3D 坐标", hole_3d),
                       ("hand 3D 坐标", hand_3d)],
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
            # 🧮 2026-09-03 流形层逐帧 channel (引擎每步实算, 画布输出线 → 波形/总线)
            "🧮 接触流形": {
                "in": [("几何 (手/销/孔)", "引擎真值")],
                "out": [("流形进度 e∥ (m)", _mc.get("progress", 0.0)),
                       ("法向偏离 e⊥ (m)", _mc.get("risk", 0.0)),
                       ("V=½‖e‖²", _mc.get("V", 0.0)),
                       ("状态", _mc.get("state", "—"))],
            },
            "🧮 性能流形": {
                "in": [("几何 (销/孔)", "引擎真值")],
                "out": [("横向错位 δ⊥ (m)", _mp.get("d_perp_norm", 0.0)),
                       ("插深剩余 (m)", -_mp.get("d_axial", 0.0) if _mp else 0.0),
                       ("V_p=½δᵀWδ", _mp.get("Vp", 0.0)),
                       ("耦合效率 η", _mp.get("eta", 0.0))],
            },
            "🧮 潜空间": {
                "in": [("潜状态/先验", "估计器+动力学")],
                "out": [("潜坐标 (位置3+预测力)", _lat),
                       ("速度场 prior−x̂₋", _vel)],
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
# 🐛 2026-08-26: 与 _SS_DIR 同源 — 从已探测到的源码目录上溯 5 级到仓库根 (state_space→left_right→policies→lerobot→src→根)
_DATASET_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.dirname(_SS_DIR))))),
    "data", "ss_insert")


def export_dataset(n_episodes=8, seed_base=100, out_dir=None, log=None, perturb=0.01):
    """多轮仿真 (起始扰动+噪声 seed) → 专家演示数据集 npz

    对齐 on_train 训练管道数据包格式:
      states  (n,39) 39D 视觉结构 obs (当前18+上一18+目标3, 无触觉)
      actions (n,4)  u_ff 前馈建议 (左脑MLP 学习目标 — 训练学仿真里的前馈)
      stages  (n,)   阶段标签 (信息, 不参与训练)
      success (n_ep,) 每轮完成标志
      task_name "ss_insert" · fps 50 (DT=0.02)
    perturb: 起始位置扰动半径 (m)。2026-09-04: 训练域 = 扰动决定 —
      蒸馏 MLP 只覆盖数据域, 域外闭环发散 (实证 ±3cm 即失败) → 扩域重训加 perturb。

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
        # 🧠 2026-09-04 静静: 数据管道固定用解析律当教师 (teacher) — 与推理主执行器解耦。
        #   蒸馏范式: 教师(解析, 全局稳定)生成演示 → 学生(左脑MLP)蒸馏。
        #   MLP 不能当教师: 域外无稳定保证, 自举生成发散轨迹 (实测 hand 飞到 9m)。
        sim.accel.forward = sim.accel.analytic_forward
        np.random.seed(seed_base + ep)
        # 起始扰动: 末端位置抖动 ±perturb (真实产线来料偏差; perturb 定义训练域)
        sim.x = X0 + np.array([np.random.uniform(-perturb, perturb),
                               np.random.uniform(-perturb, perturb), 0.0])
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
