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

    def __init__(self, log=None, seed=0, vision=False, vision_every=25):
        self.log = log or (lambda *a: None)
        self.seed = seed
        self.vision = vision          # R1: 工件感知 (peg/hole) 走 YOLO; hand 恒编码器真值
        self.vision_every = vision_every   # YOLO 刷新间隔 (步); 工件静止, 中间步沿用上次
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
        self._site_ee = m.site("endEffector").id          # (仅参考; 控制锚=obs hand)
        self._site_ph = m.site("pegHead").id              # 销头 (插入端)
        self._site_hole = m.site("hole").id               # 孔口 (真值参考)
        self._site_goal = m.site("goal").id               # 插入终点 (真值参考)
        # 🎯 R1 视觉感知状态: 工件 (peg/hole) 定位走 YOLO; 夹持后销=编码器+锁存偏移
        self._vis = {"peg": None, "hole": None, "shot": 0, "miss": 0, "n": 0,
                     "hole_off": None, "det3d": {}}    # hole_off = goal−孔口 现场偏移 (模拟 CAD 已知)
        self._vis_ok = False
        # 🎯 R1 视觉感知 (工件定位): YOLO hand 检测漂移 12-20cm 不可控 (定标实锤) —
        #   真机同构: 机械臂末端=编码器 (obs hand 精确), 视觉只定位工件 (peg/hole)
        self._aligner = None
        if self.vision:
            self._load_aligner()

    def _load_aligner(self):
        """加载 YOLO 对齐器 (检测 + 深度反投影, 同 GUI 链路的真实模型)"""
        import os as _os
        _REPO = _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                               "..", ".."))
        _cands = [_os.path.join(_REPO, "runs", "detect", "outputs", "yolo_peg", "peg_v1", "weights", "best.pt"),
                  _os.path.join(_REPO, "outputs", "yolo_peg", "peg_v1", "weights", "best.pt")]
        _w = next((c for c in _cands if _os.path.isfile(c)), _cands[0])
        _dc = [_os.path.join(_REPO, "outputs", "yolo_peg_depth", "peg_depth_v1-2", "weights", "best.pt"),
               _os.path.join(_REPO, "outputs", "yolo_peg_depth", "peg_depth_v1", "weights", "best.pt")]
        _dw = next((c for c in _dc if _os.path.isfile(c)), None)
        _ss_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))  # tools/gui
        _yolo_dir = _os.path.join(_REPO, "src", "lerobot", "policies", "yolo_3d")
        import importlib.util as _ilu
        spec = _ilu.spec_from_file_location("r1_yolo_aligner",
                                            _os.path.join(_yolo_dir, "yolo_state_aligner.py"))
        _m = _ilu.module_from_spec(spec)
        spec.loader.exec_module(_m)
        self._aligner = _m.YoloStateAligner(_w, self.env, depth_weights=_dw)
        self.log(f"🎯 R1 YOLO 已加载: {_os.path.basename(_w)} · 深度 {_os.path.basename(_dw) if _dw else '无'}")

    def _vis_refresh(self):
        """🎯 YOLO 感知刷新一次: render → detect_3d → peg/hole 3D (EMA 平滑 + 跳变保护)
        返回检出数; 未检出沿用上次值。peg 定位噪声 ±1-3cm → EMA α=0.5 压到 ~1cm
        (夹爪悬停期间多次刷新收敛; 单帧跳变 >5cm 视为误检丢弃)"""
        try:
            img = self.env.render()
            det3d = self._aligner.detect_3d(img)
            n = 0
            if det3d.get("peg") is not None:
                _p = np.asarray(det3d["peg"], dtype=float)
                _old = self._vis["peg"]
                if _old is not None and float(np.linalg.norm(_p - _old)) < 0.05:
                    _p = 0.5 * _p + 0.5 * _old          # EMA (悬停多次刷新收敛)
                self._vis["peg"] = _p
                n += 1
            if det3d.get("hole") is not None:
                self._vis["hole"] = np.asarray(det3d["hole"], dtype=float)  # 仅统计
                n += 1
            self._vis["n"] += n
            self._vis["miss"] += (2 - n)
            self._vis["shot"] += 1
            self._vis["det3d"] = {k: np.asarray(v, dtype=float) for k, v in det3d.items()}
            # 可视化消费 (真实感知视频): 本帧渲染图 + 2D 检测框 (detect_3d 内 predict 的缓存)
            self._vis["img"] = img
            self._vis["boxes"] = getattr(self._aligner, "_last_res", None)
            if os.environ.get("R0_TRACE"):
                o = np.asarray(self.env._get_obs(), dtype=np.float64).ravel()
                _pe = np.linalg.norm(self._vis["peg"] - o[4:7]) if self._vis["peg"] is not None else float("nan")
                print(f"  [vis] 检出{n}/2 · peg误差{_pe*1000:.0f}mm"
                      f" · vis_peg={np.round(self._vis['peg'],3) if self._vis['peg'] is not None else None}"
                      f" · 真peg={np.round(o[4:7],3)}", flush=True)
            return n
        except Exception as e:
            self.log(f"⚠️ YOLO 刷新失败: {e}")
            self._vis["miss"] += 2
            self._vis["shot"] += 1
            return 0

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
            "hand0": o[0:3].copy(),                               # 夹爪初始
        }
        # 🎯 R1: 现场孔偏移 goal−孔口 (模拟真机 CAD 已知的孔深方向/深度);
        #   视觉孔位 = YOLO hole + 此偏移 → 插入终点 (视觉只给孔口, 孔底不可见)
        self._vis["hole_off"] = (self.geom["goal"] - self.geom["hole"]).copy()
        # 销头相对销 body 的现场偏置 (R1 夹持后销头 = hand+锁存偏移+此偏置)
        self.geom["head_off"] = (d.site_xpos[self._site_ph] - o[4:7]).copy()
        # R1 视觉初始定位 (第一步前刷新, 工件位置未知 → 视觉找)
        self._vis["peg"] = self._vis["hole"] = None
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
        self._z_stall = 0          # 下降停滞帧数 (被销/台顶住判据)
        self._z_prev = None        # 上一帧 hand z
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
            return self._hole_p() + np.array([0.0, 0.0, 0.02]) - off   # 销头到孔口上方 2cm
        return self._goal_p() - off                                     # 插入/完成: 销头到终点

    def peg_head(self):
        """销头世界坐标 (R0: site 真值; R1 夹持后: 编码器 hand + 锁存偏移 + 销头偏置 — 真机无 site)"""
        if self.grasped and self._grasp_off0 is not None and self.vision:
            ho = self.geom.get("head_off", np.zeros(3))
            return self.x + self._grasp_off0 + ho
        return self.env.data.site_xpos[self._site_ph].copy()

    # ── R1 视觉感知 helper: 孔口/终点 (工位固定标定值 — 插入工位不随机, 产线一次标定;
    #   视觉 hole 检测实测 6-37cm 漂移不可控 (R1 trace 实锤), 只作统计不参与控制) ──
    def _hole_p(self):
        """孔口位置 (工位标定值)"""
        return self.geom["hole"]

    def _goal_p(self):
        """插入终点 (工位标定: 孔口 + 现场孔深偏移)"""
        return self.geom["goal"]

    # ── 证据量 (全现场几何) ──
    def _d_xy_peg(self):
        """夹爪-销抓握点 水平距离 (接近/对位/下降推进证据; 实时销位置)"""
        pg = getattr(self, "_peg_cur", self.geom["peg_grasp"])
        return float(np.linalg.norm(self.x[:2] - pg[:2]))

    def _d_hole_h(self):
        """销头-孔口 水平距离 (转移→插入 推进证据; 孔口=感知位置)"""
        return float(np.linalg.norm(self.peg_head()[:2] - self._hole_p()[:2]))

    def _insert_depth(self):
        """销头到插入终点距离 (插入→完成 证据; 终点=感知孔口+CAD偏移)"""
        return float(np.linalg.norm(self.peg_head() - self._goal_p()))

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
            # ② 观测刷新 (x = obs hand 编码器真值; 销/孔感知: R0 真值 / R1 视觉)
            d = env.data
            o = np.asarray(env._get_obs(), dtype=np.float64).ravel()
            # 🎯 R1 真实视觉: **每帧渲染 + detect_3d** (老倪红线: 不能造假 — 禁用节流/冻结/
            #   复用旧值). 每步 env.step 后 render() → YOLO 检测 → 本帧真值.
            #   ⚠️ 成本: ~0.5-1s/步 × 500 步 ≈ 4-9 分钟/轮 (真流程的代价, 接受)
            #   ⚠️ 物理事实: 固定相机下夹爪贴近工件会遮挡 → peg 检测崩 (真实感知退化,
            #      不掩盖 — 这正是 RealityGap 要暴露的; 真机用 eye-in-hand 相机解决)
            if self.vision and self._aligner is not None:
                self._vis_refresh()
            x_new = o[0:3].copy()
            self.v = (x_new - self.x) / DT_ENV if step > 0 else np.zeros(3)
            self.x = x_new
            self.gripper = float(o[3])
            # 下降停滞检测 (被销/台顶住): 每步 z 位移 <0.4mm 累计; 连续 ≥8 帧 = 物理接触顶住.
            #   (R1 视觉 peg z 偏低 1.5cm 实测 — at_grasp_pose 用视觉 z 会永远等不到, 卡下降)
            if self._z_prev is not None and self.sched.stage() in ("下降", "抓取"):
                if abs(x_new[2] - self._z_prev) < 0.0004:
                    self._z_stall += 1
                else:
                    self._z_stall = 0
            else:
                self._z_stall = 0
            self._z_prev = float(x_new[2])
            # 销位置感知: 夹持后 = 编码器 hand+锁存偏移 (真机无视觉跟销);
            # R1 未夹持 = YOLO peg (悬停高度刷新, 下降期冻结防遮挡幻影); R0 = obs 真值
            if self.grasped and self._grasp_off0 is not None:
                self._peg_cur = (self.x + self._grasp_off0).copy()
            elif self.vision and self._vis["peg"] is not None:
                self._peg_cur = np.asarray(self._vis["peg"], dtype=float)
            else:
                self._peg_cur = o[4:7].copy()
            g = self.geom
            # ③ 接触力合成 (几何合成; metaworld 无力传感器; 销头=peg_head() 感知一致)
            force = np.zeros(6)
            ph = self.peg_head()                             # 当前销头 (感知语义)
            if not self.grasped:
                gap_z = max(0.0, 0.012 - (self.x[2] - self._peg_cur[2]))
                if self._d_xy_peg() < 0.03 and gap_z > 0:
                    force[2] = K_CONTACT * max(gap_z, 0.5 * D_CONTACT)
            else:
                dh = self._d_hole_h()
                if dh < D_CONTACT:
                    force[2] = K_CONTACT * max(0.0, D_CONTACT - dh)
            force_norm = float(np.clip(force[2] / (K_CONTACT * D_CONTACT), 0.0, 1.0))
            # 🐛 R1: 几何抓握位姿 — 水平对准视觉 peg + 下降停滞 (z 连续 ≥8 帧不动 = 被销/台顶住,
            #   指已包住销身). 视觉 peg z 偏低不可信, 不用 z 阈值 (0/6 卡下降实锤)
            at_grasp_pose = bool(self._d_xy_peg() < 0.03 and self._z_stall >= 8)
            # ④ 39D 视觉结构 (引擎语义骨架; 感知一致: 销=_peg_cur, 终点=_goal_p)
            cur = np.concatenate([self.x, [self.gripper], self.v,
                                  self._peg_cur, self._goal_p(), np.zeros(3), np.zeros(2)])
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
                        # 锁存偏移用感知销 (R1: 视觉 peg; R0: 真值) — 夹持后机器人"以为"的销位置
                        self._grasp_off0 = self._peg_cur - self.x
                        self._grasp_gap_z = float(self.x[2] - self._peg_cur[2])
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
            # 🔌 真实 io 快照 (画布节点名 key, 与引擎 _io_snapshot 同构 → 播放/3D/总线复用)
            tr["io_trace"].append((round(step * DT_ENV, 3), self._io_snapshot(
                o, obs, force_norm, u_ff, latent_pred, prior, z_k, corrected, residual,
                contact_p, u_fb, u, stage, u_sat, self._u_vec, step, at_grasp_pose)))
            if done:
                break
        tr["io"] = tr["io_trace"][-1][1] if tr["io_trace"] else {}
        return tr

    # ── 🔌 真实 io 快照 (画布节点名 key — YOLO/2D→3D 用真实检测, 非引擎几何) ──
    def _io_snapshot(self, o, obs, force_norm, u_ff, latent_pred, prior, z_k,
                     corrected, residual, contact_p, u_fb, u, stage, u_sat,
                     u_vec, frame_id, at_grasp_pose):
        """每帧真实模块 I/O — 与引擎 _io_snapshot 同构 (画布播放/3D/总线消费同一 key)
        🎯 YOLO/📐2D→3D = 本帧真实检测 (detect_3d 输出或最近刷新缓存), 不再写引擎几何"""
        _v3 = self._vis["peg"] if (self.vision and self._vis["peg"] is not None) else o[4:7]
        _vh = self._vis["hole"] if (self.vision and self._vis["hole"] is not None) else self.geom["hole"]
        _conf = "🎥" if self.vision else "--"
        return {
            "📦 metaworld 数据源": {
                "in": [], "out": [("图像流 (真实渲染帧)", f"帧#{frame_id}"),
                                  ("状态流 39D (编码器+视觉)", obs[:39])]},
            "🎯 YOLO 目标检测": {
                "in": [("图像流", f"帧#{frame_id}")],
                "out": [("peg 3D (detect_3d)", _v3),
                        ("hole 3D (detect_3d)", _vh),
                        ("hand 3D (视觉, 不参与控制)",
                         (self._vis.get("det3d", {}).get("hand")
                          if (self.vision and self._vis.get("det3d", {}).get("hand") is not None)
                          else self.x)),
                        ("检测源", _conf)]},
            "📐 2D→3D 解算": {
                "in": [("检测框 2D", "真实反投影")],
                "out": [("peg 3D", _v3), ("hole 3D", _vh),
                        ("hand 3D", self.x)]},   # hand=编码器 (真机同构)
            "🖐 触觉感知": {
                "in": [], "out": [("触觉 4D", obs[39:43])]},
            "📡 传感器融合": {
                "in": [("视觉 39D", obs[:39]), ("触觉 4D", obs[39:43])],
                "out": [("obs 43D", obs)]},
            "⚡ 前馈加速器": {
                "in": [("obs 43D", obs)], "out": [("u_ff 4D", u_ff)]},
            "🔮 自适应状态估计器": {
                "in": [("潜状态", self.latent)], "out": [("latent_pred 4D", latent_pred)]},
            "📈 先验动力学预测器": {
                "in": [("潜状态", self.latent)], "out": [("prior 4D", prior)]},
            "🧪 状态校正器": {
                "in": [("prior", prior), ("z_k", z_k)],
                "out": [("corrected", corrected), ("residual", residual),
                        ("contact_p", contact_p)]},
            "🧭 动作调制器": {
                "in": [("u_ff", u_ff), ("u_fb", u_fb), ("contact_p", contact_p)],
                "out": [("u 融合", u), ("stage", stage)]},
            "🛡 安全限幅": {
                "in": [("u", u)], "out": [("u_sat", u_sat)]},
            "🤖 执行器": {
                "in": [("u_sat", u_sat)], "out": [("u_vec 下发", u_vec)]},
            "🌍 物理世界": {
                "in": [("u_vec", u_vec)],
                "out": [("末端 hand", self.x), ("销 peg", self._peg_cur),
                        ("夹爪", self.gripper), ("力 norm", force_norm),
                        ("抓握位姿", at_grasp_pose)]},
        }


def quick_run(n_episodes=8, seed_base=100, vision=False, vision_every=25):
    """多轮真实化闭环 → 成功率统计 (vision=True = R1 工件视觉感知)"""
    tag = "🎥 R1 视觉工件感知" if vision else "🧮 R0 物理真实化"
    print(f"{tag}: {n_episodes} 轮 (seed {seed_base}~{seed_base + n_episodes - 1})")
    n_ok = 0
    for ep in range(n_episodes):
        sim = RealStateSpaceSim(seed=seed_base + ep, vision=vision, vision_every=vision_every)
        tr = sim.run()
        ok = bool(tr["done"][-1])
        n_ok += 1 if ok else 0
        stages = sorted(set(str(s).replace("阶段 ", "") for s in tr["stage"]))
        vinfo = ""
        if vision:
            v = sim._vis
            rate = (v["n"] / (v["shot"] * 2) * 100) if v["shot"] else 0
            vinfo = f" · YOLO检出率 {rate:.0f}% ({v['n']}/{v['shot']*2})"
        print(f"  ep{ep + 1}: {len(tr['t'])} 步 · {'✅ 完成' if ok else '⚠️ 未完成'} "
              f"· 阶段 {'→'.join(stages)} · 终点 dist={tr['dist'][-1]:.4f}"
              f" · 夹持={tr['grasped'][-1]}{vinfo}", flush=True)
        if not ok:
            from collections import Counter
            c = Counter(str(s).replace("阶段 ", "") for s in tr["stage"])
            print(f"    阶段停留: {dict(c)} · 末 gripper={tr['gripper'][-1]:.3f} "
                  f"· 接触峰={max(tr['contact_p']):.3f}", flush=True)
    print(f"🏁 成功率 {n_ok}/{n_episodes}")
    return n_ok


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("n", type=int, nargs="?", default=8)
    ap.add_argument("--vision", action="store_true", help="R1: 工件 (peg/hole) 走 YOLO 视觉")
    ap.add_argument("--every", type=int, default=25, help="YOLO 刷新间隔 (步)")
    ap.add_argument("--seed", type=int, default=100)
    a = ap.parse_args()
    quick_run(a.n, a.seed, vision=a.vision, vision_every=a.every)
