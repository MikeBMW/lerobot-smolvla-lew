# -*- coding: utf-8 -*-
"""state_space_sim_real.py — R0 物理真实化闭环 (2026-09-04 静静, 设计见 docs/closed_loop_realization_design.md)

六层控制器 (perception/parallel/cognition/dynamics/safety/execution 源码 importlib 加载, 同引擎)
  指令 → metaworld peg-insert-side-v3 env.step 真实物理 (接触/夹持/插入动力学)
  感知 = env 真值直读 (R0; R1 将换成 渲染帧→YOLO→3D)

与引擎 state_space_sim.py 差异:
  - 物理推进: 引擎自积分 → env.step (真实 MuJoCo)
  - 几何: 引擎写死常量 → 每轮现场采样 (探针证实 metaworld 跨进程漂移 >10cm)
  - 状态: x/peg/gripper 全部从 env 观测刷新, 不做引擎积分
  - 夹持: 引擎锁存 → 闭合指令 + gripper 收敛判夹持 (metaworld 夹住销饱和 ~0.70, 空夹 ~0.29)
  - 前馈: 解析律 u=Kp(target−pos) (不挂引擎训练 MLP — 引擎语义 39D 与真实世界错位)
  - 步频: 引擎 dt=0.02 (50Hz) → env step (~10Hz), 控制器时间常数按新步频

用法: python3 state_space_sim_real.py [轮数]
"""
import importlib.util
import os
import sys
import numpy as np


def _find_ss_dir():
    rel = os.path.join("src", "lerobot", "policies", "left_right", "state_space")
    d = os.path.dirname(os.path.abspath(__file__))
    while True:
        c = os.path.join(d, rel)
        if os.path.isfile(os.path.join(c, "perception.py")):
            return c
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    raise FileNotFoundError("state_space 六层源码目录未找到")


_SS_DIR = _find_ss_dir()


def _load(name):
    path = os.path.join(_SS_DIR, name)
    spec = importlib.util.spec_from_file_location(f"ss_real.{name[:-3]}", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# metaworld 环境 (模块级懒加载单例 — 构造 ~0.5s, import 0.3s)
_ENV = None


def _make_env():
    global _ENV
    if _ENV is not None:
        return _ENV
    os.environ.setdefault("DISPLAY", ":0")
    os.environ.setdefault("MUJOCO_GL", "glfw")
    import metaworld as _mt
    mt = _mt.MT1("peg-insert-side-v3")
    env = mt.train_classes["peg-insert-side-v3"](render_mode="rgb_array", camera_name="corner2")
    env.set_task(mt.train_tasks[0])
    _ENV = env
    return env


DT_ENV = 0.1            # metaworld 1 step ≈ 0.1s 物理 (标定值, audit 可调)
K_ACT = 0.5             # 引擎速度指令 m/s → act ±1 的标定: act = clip(u[:3]/K_ACT)
GRIP_CLOSE = 0.6        # metaworld 夹爪闭合动作值 (gen_insert_video 同款, 防夹死)
GRIP_OPEN = -1.0        # 张开动作
GRASP_SAT = 0.70        # 夹住销后的 gripper 饱和 (~0.70, cognition.py 注释; 空夹收敛 ~0.29)
D_CONTACT = 0.02        # 接触距离 (同引擎)
D_INSERT = 0.004        # 插入成功判定 (同引擎)
K_CONTACT = 6.0         # 接触力增益 (同引擎)
MAX_STEPS = 2000        # 单轮步数上限 (metaworld ~10Hz, 引擎 500 步 @50Hz = 1000 步 @10Hz, 余量)
STAGE_LIFT = 0.16       # 抬起目标 (夹爪锚, 台面之上; 同引擎语义)
STAGE_APPROACH_H = 0.09
STAGE_ALIGN_H = 0.05
STAGE_DESCEND_H = 0.004
PEG_HEAD_OFF_XY = 0.13  # 销头相对抓握点沿 -X 0.13 (现场用 site, 此值仅兜底)


class RealStateSpaceSim:
    """R0 物理真实化 — run() 返回时间序列 (结构与引擎 tr 兼容)"""

    def __init__(self, log=None, seed=0):
        self.log = log or (lambda *a: None)
        self.seed = seed
        self.env = _make_env()
        # 六层控制器源码 (同引擎加载方式)
        self.perception = _load("perception.py")
        self.parallel = _load("parallel.py")
        self.dynamics = _load("dynamics.py")
        self.cognition = _load("cognition.py")
        self.safety = _load("safety.py")
        self.execution = _load("execution.py")
        self.accel = self.parallel.FeedforwardAccelerator()
        # B = 每步实际位移/速度指令 — 实测标定: metaworld act=u/0.5 伺服稳态 ~9mm/步@act1,
        #   位移 ≈ u × 0.018s (引擎 dt=0.02 巧合同量级); 原 B=0.1 预测过冲 5 倍 →
        #   残差 0.5 级爆发 → contact_p 误判接触 (夹爪离销 20cm 空闭合) → 卡死循环
        self.est = self.parallel.AdaptiveStateEstimator(A=1.0, K=0.2, B=0.02)
        self.dyn = self.dynamics.PriorDynamicsPredictor(A=1.0, B=0.02)
        self.execr = self.execution.RobotExecutor()
        self.world = self.execution.PhysicalWorld(noise=0.0)   # R0 直读真值, 不加模拟噪声
        # 夹爪结构 site id (现场解析, 每轮 reset 后刷新 xpos)
        m = self.env.model
        self._site_ee = m.site("endEffector").id          # 夹爪锚 (YOLO 检的 hand)
        self._site_pg = m.site("pegGrasp").id             # 销抓握点
        self._site_ph = m.site("pegHead").id              # 销头 (插入端)
        self._site_hole = m.site("hole").id               # 孔口
        self._site_goal = m.site("goal").id               # 插入终点

    # ── 每轮复位: 现场采样几何 ──
    def _reset(self, seed):
        env = self.env
        # 🐛 2026-09-04: freeze 必须在 reset 采样**之后** — 若先 freeze 再 reset,
        #   布局锁死在第一次的值, 后续 seed 全同 (8 轮同一轨迹实锤).
        #   先解冻 → reset(seed) 采样该 seed 的新布局 → 再冻结防 step 扰动
        env._freeze_rand_vec = False
        env.reset(seed=seed)
        env._freeze_rand_vec = True
        d = env.data
        o = np.asarray(env._get_obs(), dtype=np.float64).ravel()
        # 现场几何 (metaworld 跨进程漂移 → 每轮从 MuJoCo data 读, 不信常量)
        self.geom = {
            "goal": d.site_xpos[self._site_goal].copy(),          # 插入终点
            "hole": d.site_xpos[self._site_hole].copy(),          # 孔口
            "peg_grasp": o[4:7].copy(),                           # 销抓握点 (obs 语义)
            "peg_head0": d.site_xpos[self._site_ph].copy(),       # 销头初始
            "peg_z0": float(o[4]),                                # 销初始 z (抬升判据锚)
            "hand0": d.site_xpos[self._site_ee].copy(),           # 夹爪初始
        }
        self.grasped = False
        self.peg_off = None            # (保留字段, 夹持用 _grasp_off0)
        self._grasp_off0 = None
        self._grasp_gap_z = 0.015
        self._close_steps = 0
        # 🐛 2026-09-04 静静 (探针12 实锤): 控制锚必须用 obs[0:3] hand (腕部=真实夹爪 claw),
        #   不能用 endEffector site — site 是腕下 4cm 的虚拟视觉点, 降到 peg 高度时真实夹爪
        #   还悬空 2-3.5cm → 空夹 (接触实验里 'peg 接触' 实为 peg 贴桌面, 误读成夹持).
        #   探针12: hand 降到 peg 身 (hand_z≈peg_z+0.02 被销顶住) 闭合 grp~0.66 夹住, 抬升随动.
        self.x = o[0:3].copy()         # 夹爪真实位置 (obs hand 语义)
        self.v = np.zeros(3)
        self.gripper = float(o[3])
        self.u_prev = np.zeros(4)
        self.obs_prev = None
        self.res_ema = None
        self.latent = np.concatenate([self.x, [0.0]])
        # 每轮新建调度器 (stage_idx 归零) — 控制器参数现场可调
        # gripper 语义: 喂 advance 的 gripper = 夹紧度 1−obs_mw (1=紧)。
        # metaworld obs gripper: 1=全开, 夹住 0.03m 销饱和 ~0.70 (空夹收敛 ~0.29)
        # → 夹紧度: 夹住=0.30, 空夹=0.71。阈值取 0.25 (obs<0.75, 闭合足够深才开始抬;
        #   夹住与否由抬起阶段 peg 随动验证决定, 见 grasp_force)
        self.sched = self.cognition.ActionModulator(
            grasp_th=0.40,      # 夹紧度 1−obs>0.40 (obs<0.60 深夹) 才推进抬起 — 与锁存同步
                                # (浅夹 0.72 就抬滑脱率高; 深夹到 0.60 以下夹持力才足)
            align_th=0.025,     # 转移→插入 孔位对准 (销头-孔口水平, 视觉精度余量)
            insert_depth=0.006,  # 插入→完成: 销头离终点 6mm 内算完成 (metaworld 插入物理
                                 #   精度余量; 引擎 0.004 在真实物理下差 0.1mm 磨死 — ep5 实锤)
            lift_h=0.08,        # 抬起→转移: 销升 8cm (孔口高 0.13, 销初始 0.03 — 升够才平移防撞台)
            max_veto=5,
        )
        self.stage_hist = []
        self._grasp_off0 = None    # 锁存瞬间 peg−x (随动验证锚)
        self._grasp_gap_z = 0.015  # 锁存瞬间 夹爪z−销z (抬升目标补偿)
        self._close_steps = 0      # 抓取阶段闭合指令持续步数
        # 插入阶段最小推力: 销头进孔后摩擦阻力大, 比例项趋零 → 无 v_min 会磨死在孔口
        #   (ep3 插到 13mm 推不动 96 步实锤; 引擎 STAGE_V_MIN 无插入, 真实物理需要)
        self.sched.v_min["插入"] = 0.02

    # ── 阶段子目标 (八阶段, 几何全现场, 锚 = 夹爪) ──
    # 夹持前 (接近→抓取): 目标 = 销抓握点上方 — ⚠️ 用**实时销位置** self._peg_cur
    #   (回退重抓时销可能被首次下降碰移, 静态采样坐标会空夹 — ep3-5 失败实锤)
    # 夹持后 (抬起→插入): 目标由"销头当前位置 + 实时夹爪偏移"驱动 —
    #   销头相对夹爪的方向/距离锁存后不变, 把销头送到孔口/终点即得夹爪目标
    def _stage_target(self):
        g = self.geom
        st = self.sched.stage()
        pg = getattr(self, "_peg_cur", g["peg_grasp"])     # 实时销位置 (obs[4:7])
        if st == "接近":
            return pg + np.array([0.0, 0.0, STAGE_APPROACH_H])
        if st == "对位":
            return pg + np.array([0.0, 0.0, STAGE_ALIGN_H])
        if st in ("下降", "抓取"):
            return pg + np.array([0.0, 0.0, STAGE_DESCEND_H])
        if st == "抬起":
            # 垂直抬升: xy 保持当前, z 抬到销离台 STAGE_LIFT (保持锁存时夹爪-销高度差)
            gap_z = getattr(self, "_grasp_gap_z", 0.02)
            return np.array([self.x[0], self.x[1], g["peg_z0"] + STAGE_LIFT + gap_z])
        off = self.peg_head() - self.x          # 实时销头-夹爪偏移 (夹持后锁存不变)
        if st == "转移":
            return g["hole"] + np.array([0.0, 0.0, 0.02]) - off   # 销头到孔口上方 2cm
        return g["goal"] - off                                      # 插入/完成: 销头到终点

    def peg_head(self):
        """销头世界坐标 (现场 site, 夹持后随夹爪物理移动)"""
        return self.env.data.site_xpos[self._site_ph].copy()

    # ── 证据量 (全现场几何) ──
    def _d_xy_peg(self):
        """夹爪-销抓握点 水平距离 (接近/对位/下降推进证据; 实时销位置)"""
        pg = getattr(self, "_peg_cur", self.geom["peg_grasp"])
        return float(np.linalg.norm(self.x[:2] - pg[:2]))

    def _d_hole_h(self):
        """销头-孔口 水平距离 (转移→插入 推进证据)"""
        return float(np.linalg.norm(self.peg_head()[:2] - self.geom["hole"][:2]))

    def _insert_depth(self):
        """销头到插入终点距离 (插入→完成 证据)"""
        return float(np.linalg.norm(self.peg_head() - self.geom["goal"]))

    # ── 主循环 ──
    def run(self, max_steps=500):
        """R0 主循环 — metaworld 单轮硬上限 500 步 (max_path_length), 截断即未完成"""
        env = self.env
        self._reset(self.seed)
        tr = {"t": [], "dist": [], "u_ff": [], "residual": [], "contact_p": [], "u_sat": [],
              "stage": [], "done": [], "x": [], "gripper": [], "force": [], "peg": [],
              "peg_head": [], "target": [], "grasped": [], "obs": [], "u_ff_vec": [],
              "u_sat_vec": [], "u_fb_vec": [], "u_fuse_vec": [], "u_limit_vec": [],
              "u_exec_vec": [], "v_vec": [], "z_k_vec": [], "io_trace": []}
        done = False
        truncated = False
        for step in range(int(max_steps)):
            # ① 上一拍控制器指令 → metaworld 动作 → 真实物理
            u_vec = getattr(self, "_u_vec", np.zeros(4))
            act = np.zeros(4)
            act[:3] = np.clip(u_vec[:3] / K_ACT, -1.0, 1.0)
            act[3] = GRIP_CLOSE if u_vec[3] > 0.5 else GRIP_OPEN
            try:
                env.step(act)
            except ValueError:
                # metaworld truncate (500 步到顶) — 未完成, 结束本轮
                truncated = True
                break
            # ② 观测刷新 (全部真值直读; x = obs hand 真实夹爪位)
            d = env.data
            o = np.asarray(env._get_obs(), dtype=np.float64).ravel()
            self._peg_cur = o[4:7].copy()        # 实时销位置 (抓取对准/证据用)
            x_new = o[0:3].copy()
            self.v = (x_new - self.x) / DT_ENV if step > 0 else np.zeros(3)
            self.x = x_new
            self.gripper = float(o[3])
            g = self.geom
            # 销状态: 夹持后销随夹爪 (MuJoCo 物理自动), obs[4:7] 与 site 同步
            # ③ 接触力合成 (引擎逻辑现场化; metaworld 无力传感器 → 几何合成)
            force = np.zeros(6)
            ph = d.site_xpos[self._site_ph].copy()             # 当前销头
            if not self.grasped:
                gap_z = max(0.0, 0.012 - (self.x[2] - g["peg_grasp"][2]))
                if self._d_xy_peg() < 0.03 and gap_z > 0:
                    force[2] = K_CONTACT * max(gap_z, 0.5 * D_CONTACT)
            else:
                dh = self._d_hole_h()
                if dh < D_CONTACT:
                    force[2] = K_CONTACT * max(0.0, D_CONTACT - dh)
            force_norm = float(np.clip(force[2] / (K_CONTACT * D_CONTACT), 0.0, 1.0))
            # 🐛 R0: 几何抓握位姿 — hand(真实夹爪)水平对准 + 降到销身 (被销顶住 ≈ peg_z+0.02,
            #   探针12 实测 hand 停 peg+0.021 时指已包住销上部; 只等力觉会卡死 (cognition 注释 151)
            at_grasp_pose = bool(self._d_xy_peg() < 0.025
                                 and self.x[2] < g["peg_grasp"][2] + 0.03)
            # ④ 39D 视觉结构 (引擎语义骨架, 几何全现场; [4:7] 用差分速度同引擎)
            cur = np.concatenate([self.x, [self.gripper], self.v,
                                  o[4:7], g["goal"], np.zeros(3), np.zeros(2)])
            prev = self.obs_prev if self.obs_prev is not None else cur
            target = self._stage_target()
            visual39 = np.concatenate([cur, prev, target])
            tactile4 = np.array([self.gripper, float(self.grasped), 0.0, 0.0])
            obs = self.perception.fuse_sensors(visual39, force, tactile4)
            # ⑤ 六层控制器 (同引擎: 前馈→估计→预测→校正→调度→限幅→执行)
            u_ff = self.accel.forward(obs)
            act4 = np.concatenate([self.u_prev[:3], [0.0]])
            latent_pred = self.est.predict(self.latent, act4)
            prior = self.dyn.predict(self.latent, act4)
            z_k = np.concatenate([self.x, [force_norm]])       # R0 直读无噪声
            corrected, residual = self.cognition.state_correction(prior, z_k, K=0.5)
            residual = np.asarray(residual, dtype=float).copy()
            residual[3] = force_norm
            r_scalar = float(np.linalg.norm(residual))
            contact_p = float(self.cognition.contact_probability(r_scalar, gain=8.0))
            self.latent = self.est.update(latent_pred, corrected)
            self.res_ema = (0.85 * self.res_ema + 0.15 * np.asarray(residual, dtype=float)
                            if self.res_ema is not None
                            else np.asarray(residual, dtype=float).copy())
            u_fb = np.concatenate([np.clip(0.5 * self.res_ema[:3], -0.5, 0.5), [0.0]])
            u, stage = self.sched.decide(u_ff, u_fb, contact_p, r_scalar)
            if np.ndim(u) == 0:
                u = np.zeros(4)
            u = np.asarray(u, dtype=float).copy()
            u[3] = self.sched.gripper_cmd(u_ff[3])
            u_sat = self.safety.saturate(u, limit=0.6)
            u_sat = np.asarray(u_sat, dtype=float).copy()
            u_sat[3] = float(u[3])
            u_vec = self.execr.execute(u_sat)
            if np.ndim(u_vec) == 0:
                u_vec = np.zeros(4)
            self._u_vec = np.asarray(u_vec, dtype=float).copy()
            self.u_prev = self._u_vec.copy()
            # ⑥ 夹持锁存与随动验证 (R0 语义: 深夹到 grp<0.60 锁存 — 探针12 成功夹持时
            #   grp 0.66 接触建立 → 0.28 深夹; 浅夹(0.78)就抬滑脱率高 (ep3-5 失败实锤).
            #   真夹住与否由抬起阶段 peg 随动判定 (MuJoCo: 夹住则 peg 跟夹爪升)
            g_close = float(1.0 - self.gripper)          # 夹紧度 (1=紧; 夹住销深夹≈0.7+)
            if not self.grasped and self.sched.stage() == "抓取":
                if self.gripper < 0.82:                  # obs gripper 开始闭合 (<0.82)
                    self._close_steps += 1
                    if self._close_steps >= 3 and self.gripper < 0.60:
                        self.grasped = True              # 深夹锁存 (夹住候选)
                        self._grasp_off0 = o[4:7] - self.x
                        self._grasp_gap_z = float(self.x[2] - o[4:7][2])
                        self.log(f"🔩 夹爪深夹到位 (obs gripper={self.gripper:.2f}) → 抬升试探")
                else:
                    self._close_steps = 0
            elif self.grasped:
                # 随动验证: 夹爪移动时 peg 相对偏移保持 = 真夹住; 滑脱/空夹 → 偏移漂移
                _off = o[4:7] - self.x
                if float(np.linalg.norm(_off - self._grasp_off0)) > 0.035:
                    self.grasped = False                  # 掉了 → grasp_force 0 → 调度器回退重抓
                    self._grasp_off0 = None
                    # 🐛 强制回退到接近: 滑脱时 peg 可能半挂在夹爪上 (z 未落回台面),
                    #   advance 的"落回台面"回退判据不触发 → 卡死在转移/插入 (ep1/2/4 350步实锤)
                    try:
                        if self.sched.stage_idx >= 4:
                            self.sched._goto(0, "⚠️ 插销滑脱 (peg 未随夹爪) → 强制回退重抓")
                            self.log("⚠️ 插销滑脱 → 强制回退接近重抓")
                    except Exception:
                        pass
            # ⑦ 阶段推进 (证据全现场)
            self.obs_prev = obs[0:18]
            d_xy = self._d_xy_peg()
            dh = self._d_hole_h()
            depth = self._insert_depth()
            lifted = float(ph[2]) - g["peg_z0"]
            # grasp_force = 夹持质量: 夹住且 peg 随动 → 1; 掉件/空夹 → 0 (调度器回退判据)
            _gf = 1.0 if (self.grasped and self._grasp_off0 is not None
                          and float(np.linalg.norm(o[4:7] - self.x - self._grasp_off0)) < 0.02) else 0.0
            self.sched.advance(contact_p=contact_p, dist_h=dh,
                               gripper=float(1.0 - self.gripper), depth=depth,
                               d_xy=d_xy, lifted=lifted,
                               at_grasp_pose=at_grasp_pose,
                               grasp_force=_gf,
                               peg_z=float(ph[2]), peg_z_grasp=g["peg_z0"])
            done = self.sched.stage() == "完成"
            # ⑧ 记录 (引擎 tr 兼容集)
            if os.environ.get("R0_TRACE") and step % 25 == 0:
                print(f"  [t={step*DT_ENV:.1f}s] st={self.sched.stage()} "
                      f"x={np.round(self.x,3)} tgt={np.round(target,3)} "
                      f"r={r_scalar:.3f} cp={contact_p:.2f} u={np.round(self._u_vec,3)} "
                      f"grp={self.gripper:.2f} grasped={self.grasped} gf={_gf}", flush=True)
            tr["t"].append(round(step * DT_ENV, 3))
            tr["dist"].append(d_xy if not self.grasped else dh)
            tr["u_ff"].append(float(np.linalg.norm(u_ff[:3])))
            tr["residual"].append(r_scalar)
            tr["contact_p"].append(contact_p)
            tr["u_sat"].append(float(np.linalg.norm(self._u_vec[:3])))
            tr["stage"].append(stage if self.sched.stage() in stage else f"阶段 {self.sched.stage()}")
            tr["done"].append(done)
            tr["x"].append(self.x.copy())
            tr["gripper"].append(self.gripper)
            tr["force"].append(force_norm)
            tr["peg"].append(o[4:7].copy())
            tr["peg_head"].append(ph.copy())
            tr["target"].append(target.copy())
            tr["grasped"].append(bool(self.grasped))
            tr["obs"].append(obs.copy())
            tr["u_ff_vec"].append(np.asarray(u_ff, dtype=float).copy())
            tr["u_sat_vec"].append(np.asarray(self._u_vec, dtype=float).copy())
            tr["u_fb_vec"].append(np.asarray(u_fb, dtype=float).copy())
            tr["u_fuse_vec"].append(np.asarray(u, dtype=float).copy())
            tr["u_limit_vec"].append(np.asarray(u_sat, dtype=float).copy())
            tr["u_exec_vec"].append(self._u_vec.copy())
            tr["v_vec"].append(self.v.copy())
            tr["z_k_vec"].append(z_k.copy())
            tr["io_trace"].append((round(step * DT_ENV, 3), {"step": step}))
            if done:
                break
        tr["io"] = tr["io_trace"][-1][1] if tr["io_trace"] else {}
        return tr


def quick_run(n_episodes=8, seed_base=100):
    """多轮真实化闭环 → 成功率统计"""
    print(f"🧮 R0 物理真实化: {n_episodes} 轮 (seed {seed_base}~{seed_base + n_episodes - 1})")
    n_ok = 0
    for ep in range(n_episodes):
        sim = RealStateSpaceSim(seed=seed_base + ep)
        tr = sim.run()
        ok = bool(tr["done"][-1])
        n_ok += 1 if ok else 0
        stages = sorted(set(str(s).replace("阶段 ", "") for s in tr["stage"]))
        print(f"  ep{ep + 1}: {len(tr['t'])} 步 · {'✅ 完成' if ok else '⚠️ 未完成'} "
              f"· 阶段 {'→'.join(stages)} · 终点 dist={tr['dist'][-1]:.4f}"
              f" · 夹持={tr['grasped'][-1]}", flush=True)
        if not ok:
            # 诊断: 卡在哪个阶段 / 夹持是否建立 / 接触概率
            from collections import Counter
            c = Counter(str(s).replace("阶段 ", "") for s in tr["stage"])
            print(f"    阶段停留: {dict(c)} · 末 gripper={tr['gripper'][-1]:.3f} "
                  f"· 接触峰={max(tr['contact_p']):.3f}", flush=True)
    print(f"🏁 成功率 {n_ok}/{n_episodes}")
    return n_ok


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    quick_run(n)
