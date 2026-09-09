# -*- coding: utf-8 -*-
"""state_space_sim_real.py — R0 物理真实化闭环 (2026-09-04 静静, 设计见 docs/closed_loop_realization_design.md)

六层控制器 (perception/parallel/cognition/dynamics/safety/execution 源码 importlib 加载, 同引擎)
  指令 → metaworld peg-insert-side-v3 env.step 真实物理 (接触/夹持/插入动力学)
  感知 = env 真值直读 (R0; R1 将换成 渲染帧→YOLO→3D)

与引擎 state_space_sim.py 差异:
  - 物理推进: 引擎自积分 → env.step (真实 MuJoCo)
  - 几何: 引擎写死常量 → 每轮现场采样 (探针证实 metaworld 跨进程漂移 >10cm)
  - 状态: x/光模块/gripper 全部从 env 观测刷新, 不做引擎积分
  - 夹持: 引擎锁存 → 闭合指令 + gripper 收敛判夹持 (metaworld 夹住销饱和 ~0.70, 空夹 ~0.29)
  - 前馈: 解析律 u=Kp(target−pos) (不挂引擎训练 MLP — 引擎语义 39D 与真实世界错位)
  - 步频: 引擎 dt=0.02 (50Hz) → env step (~10Hz), 控制器时间常数按新步频

用法: python3 state_space_sim_real.py [轮数]
"""
import importlib.util
import os
import sys
import numpy as np


# ── 🧮 流形层加载 (2026-09-07 真实化补齐可视化输出 — 老倪: 流形节点要有输出) ──
def _load_simreal_manifold():
    """定位并 import manifold_layer.py (同引擎 _load_manifold 探测; 失败 None 不阻塞)"""
    try:
        _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        for cand in (os.path.join(_root, "src", "lerobot", "manifold"),
                     os.path.join(_root, "src", "lerobot", "policies", "left_right", "state_space"),
                     getattr(sys, "_MEIPASS", "")):
            p = os.path.join(cand, "manifold_layer.py")
            if os.path.isfile(p):
                _m = importlib.util.spec_from_file_location("_mani_real", p)
                if _m is not None:
                    _mod = importlib.util.module_from_spec(_m)
                    _m.loader.exec_module(_mod)
                    return _mod
    except Exception:
        pass
    return None


def _load_simreal_predictor():
    """定位并 import manifold/predictor_layer.py (JEPA predictor; 失败 None 不阻塞)"""
    try:
        _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        for cand in (os.path.join(_root, "src", "lerobot", "manifold"),
                     getattr(sys, "_MEIPASS", "")):
            p = os.path.join(cand, "predictor_layer.py")
            if os.path.isfile(p):
                _m = importlib.util.spec_from_file_location("_mani_pred_real", p)
                if _m is not None:
                    _mod = importlib.util.module_from_spec(_m)
                    _m.loader.exec_module(_mod)
                    return _mod
    except Exception:
        pass
    return None


_MANI_MOD = _load_simreal_manifold()
_PRED_MOD = _load_simreal_predictor()


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
    # 🚀 2026-09-08 L3 扩展: 全链 (插→拔→AOI→回放) 需 >500 步 — 放行环境硬上限
    try:
        env.max_path_length = 3000
    except Exception:
        pass
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
# 🛡 插入遇阻保护参数 (2026-09-07, seed100 滑脱实锤 — peg 头顶孔沿无倒角刚体,
#   推力>夹持保持 → peg 被逐次压滑出夹爪 (site真值-推算差 12→15mm 递增))
INSERT_STALL_FRAMES = 5     # 推而不进连续帧数 → 确认遇阻 (5 帧 ≈ 0.5s @10Hz)
INSERT_JIGGLE_FRAMES = 12   # 回撤窗口帧数 (0.08m/s × 12帧 ≈ 15mm 脱离孔口, 解除应力)
INSERT_BACKOFF_U = 0.08     # 回撤速度 (沿孔轴反向, 松开顶住应力)
GRASP_SLIP_MM = 0.008       # 夹持随动验证: peg 相对夹爪漂移阈值 (宽限期后严格 8mm — 2026-09-07
                            #   晚收紧: 20mm 漏检真滑 10-20mm (seed100/105 site-推算差 5→20mm 递增
                            #   实锤); 当初 8mm 误报是浅夹(0.40)就抬, 现已深夹 0.50+宽限 20帧)
GRASP_SLIP_GRACE = 20       # 锁存后宽限帧数 (深夹过程 peg 被挤向根部属正常, 期间阈值放宽 20mm)
INS_DEV_MM = 0.008          # 插入段 site-推算偏差守卫: 夹持后 peg 头编码器推算 vs 真实位置
                            #   偏差 >8mm 连续 3 帧 = peg 已在夹爪内滑 → 推算"假对准" → 立即回
                            #   接近重抓刷新锁存 (毫米级插入, 感知偏差>8mm 时推算引导无意义;
                            #   R0 用 site 真值, R1 真机同构替代 = 力觉/视觉偏差)
INS_DEV_FRAMES = 3
STAGE_APPROACH_H = 0.09
STAGE_ALIGN_H = 0.05
STAGE_DESCEND_H = 0.004
# 🚀 2026-09-08 L3 扩展 (插拔+AOI 闭环, mode=full): AOI 检测工位 — 台面固定标定设备
#   (真机=产线一次标定, 同 hole 语义; 3D 视图画镜头设备, 引擎只伺服到对焦点)
AOI_FOCUS = np.array([0.12, 0.62, 0.10])   # 镜头光学对焦点 (光模块头悬停检测位)
AOI_HOVER = 0.08                            # AOI转移: 对焦点上方悬停高度 (m)
PULL_BACK = 0.16                            # 拔出: 光模块头拉出孔口沿孔轴反方向距离 (m)
PEG_HEAD_OFF_XY = 0.13  # 光模块头相对抓握点沿 -X 0.13 (现场用 site, 此值仅兜底)


class RealStateSpaceSim:
    """R0 物理真实化 — run() 返回时间序列 (结构与引擎 tr 兼容)"""

    def __init__(self, log=None, seed=0, vision=False, vision_every=25, mode=None):
        self.log = log or (lambda *a: None)
        self.seed = seed
        self._abort = False   # ⏹ 2026-09-09: GUI ⏹停止/🔄重启置位 → run 循环提前退出 (防双 env 并发 mujoco segfault)
        # 🎯 2026-09-09 L4 干扰测试: cap=L4 档 run 时注入 (拿起前光模块移位/转向) — 见 _inject_peg_jitter
        self._jitter_on = False
        self._jitter_round = 0
        self._jitter_done = False
        self._jitter_meta = None
        self._grasp_th = 0.50   # 🧩 可调深夹阈值 (90° 干扰抓取实验)
        # 🏆 L4 流形预测器训练权重 — v4 优先 (512/4层: clean+jitter+CY+分维加权;
        #   v5 CY修复 抗干扰64.6%; v4/v2 兜底)
        _md = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self._pred_w_path = None
        for _w in ("l4_mani_predictor_v5.pt", "l4_mani_predictor_v4.pt", "l4_mani_predictor_v2.pt"):
            _p = os.path.join(_md, "models", _w)
            if os.path.exists(_p):
                self._pred_w_path = _p
                break
        # 🚀 2026-09-08 L3 扩展: 任务链模式 "insert"(默认回归=插入完成) / "full"(插拔+AOI 闭环)
        #   环境变量 SS_MODE=full 可全局启用; GUI ▶运行 接线见 simulink_module
        self.mode = mode or os.environ.get("SS_MODE", "insert")
        self._frame_sink = None    # 📸 2026-09-08: 帧采集钩子 (smolvla 图像数据; None=关)
        if self.mode not in ("insert", "full"):
            raise ValueError(f"mode 必须是 insert/full, 收到 {self.mode!r}")
        self.vision = vision          # R1: 工件感知 (光模块/hole) 走 YOLO; hand 恒编码器真值
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
        # 🧠 2026-09-06 静静 (晚, 多布局重训完成): 多布局学生 (models/ss_left_brain.npz,
        #   71ep×49765帧真实 metaworld 教师蒸馏 30K 步) 在 gen 采集管道实测 47/48=97.9%
        #   追平教师; 引擎快演全 MLP 主执行完成。sim_real 默认仍解析 (seed100 固定布局
        #   的 hand-peg 相对方位在训练分布边缘 → MLP 接近段输出反向, 绝对坐标 4σ 守卫
        #   盲区 — 已知问题), SS_USE_MLP=1 启用分层学生 (插入段恒解析伺服)。
        if os.environ.get("SS_USE_MLP") == "1":
            print("🧠 SS_USE_MLP=1: 分层伺服 (前段蒸馏 MLP 主执行 + 插入段解析)")
        else:
            self.accel.forward = self.accel.analytic_forward
        # B = 每步实际位移/速度指令 — 实测标定: metaworld act=u/0.5 伺服稳态 ~9mm/步@act1,
        #   位移 ≈ u × 0.018s (引擎 dt=0.02 巧合同量级); 原 B=0.1 预测过冲 5 倍 →
        #   残差 0.5 级爆发 → contact_p 误判接触 (夹爪离销 20cm 空闭合) → 卡死循环
        self.est = self.parallel.AdaptiveStateEstimator(A=1.0, K=0.2, B=0.02)
        self.dyn = self.dynamics.PriorDynamicsPredictor(A=1.0, B=0.02, use_wm=True)
        # use_wm=True (2026-09-06 晚): 右脑已多布局重训 (models/ss_right_brain.npz,
        #   真实 mj_contactForce 力标签 acc 0.998) → R0 布局域内 → contact 融合主执行;
        #   位置先验仍默认线性 (predict 不传 obs, 引擎纯积分下线性即最优, 09-06 实测)
        self.execr = self.execution.RobotExecutor()
        self.world = self.execution.PhysicalWorld(noise=0.0)   # R0 直读真值, 不加模拟噪声
        # 夹爪结构 site id (现场解析, 每轮 reset 后刷新 xpos)
        m = self.env.model
        self._site_ee = m.site("endEffector").id          # (仅参考; 控制锚=obs hand)
        self._site_ph = m.site("pegHead").id              # 光模块头 (插入端)
        self._site_hole = m.site("hole").id               # 孔口 (真值参考)
        self._site_goal = m.site("goal").id               # 插入终点 (真值参考)
        # 🎯 R1 视觉感知状态: 工件 (光模块/hole) 定位走 YOLO; 夹持后销=编码器+锁存偏移
        self._vis = {"peg": None, "hole": None, "shot": 0, "miss": 0, "n": 0,
                     "hole_off": None, "det3d": {}}    # hole_off = goal−孔口 现场偏移 (模拟 CAD 已知)
        self._vis_ok = False
        # 🎯 R1 视觉感知 (工件定位): YOLO hand 检测漂移 12-20cm 不可控 (定标实锤) —
        #   真机同构: 机械臂末端=编码器 (obs hand 精确), 视觉只定位工件 (光模块/hole)
        self._aligner = None
        if self.vision:
            self._load_aligner()
        # 🧠 2026-09-07 老倪: 原子技能肌肉记忆 (仿小脑) — 每次运行观察技能段轨迹,
        #   连续成功稳定后固化标杆, 命中时快通道给目标 (越练越顺); 失败不固化。
        #   开关: SS_MUSCLE=0 可关; 默认开 (引擎级自动积累, 无侵入 GUI)
        # 🐛 2026-09-08 静静 (R1 视觉 9/9 失败实锤): 肌肉记忆仅限 R0/确定性环境 —
        #   快通道用历史轮标杆 u_exec 开环重放接近/对位/下降/抓取段, R1 视觉/接触有
        #   随机性 (布局微漂+peg 被碰史不同) → 标杆与新状态失配 → 下降按旧轨迹落点偏 →
        #   空夹循环 (SS_MUSCLE=0 同轮 352 步成功 vs =1 失败 500 步); 且 R1 成功轮会
        #   把标杆库混入不同代码版本轨迹 (污染)。R0 确定性仿真标杆可重复 (09-07 老倪
        #   验收场景 6 轮), 不受影响。GUI ▶运行 = R1 视觉 → 小脑自动关闭, 走实时感知。
        if os.environ.get("SS_MUSCLE") != "0" and not self.vision:
            try:
                from muscle_memory import get_memory
                self.muscle = get_memory()
                self._mm_on = True
            except Exception:
                self.muscle = None
                self._mm_on = False
        else:
            self.muscle = None
            self._mm_on = False
        self._mm_stage = ""       # 当前记录阶段
        self._mm_step = 0         # 阶段内步计数
        self._mm_hits = 0         # 快通道命中帧数 (统计/展示)
        self._mm_seg = ""         # 当前重放段名
        self._mm_u = None         # 当前段标杆 u_exec 序列
        self._mm_i = 0            # 段内重放帧索引

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
        """🎯 YOLO 感知刷新一次: render → detect_3d (每步真实执行, 本帧结果→det3d/boxes/检出率)
        控制估值 _vis["peg"] 更新策略 (2026-09-07 静静, R1 视觉契约落地 — 血泪实测):
        - 悬停区 (接近/对位, 夹爪远离销): 每步 EMA 更新 — 深度模型定位 1mm (10 布局标定)
        - 下降/抓取期: 夹爪遮挡 → 视觉 peg 漂移 26-48mm (probe 实锤: 手降到 z=0.13 即
          30mm 尺度漂) → 冻结控制估值 (工件静止物理 → 位置不变, 悬停值即真值;
          检测仍每步执行并记录 — 非造假, 真机同构: 来料定位后按编码器+力觉抓取)
        - 大跳变 (>5cm) 单帧视为误检; 连续 2 帧同位置确认才采信 (滑脱回退后 peg 真被
          碰移的场景 — 否则永远抓旧位)"""
        try:
            img = self.env.render()
            det3d = self._aligner.detect_3d(img)
            n = 0
            st = ""
            sched = getattr(self, "sched", None)
            if sched is not None:
                try:
                    st = sched.stage() or ""
                except Exception:
                    st = ""
            g = getattr(self, "geom", None)
            peg_z0 = float(g["peg_z0"]) if g else 0.03
            # 🐛 2026-09-07 静静 (定位状态机): 视觉 peg 只在"手远离无遮挡"时可信 —
            #   手进入 peg 上方 ~10cm (corner2 斜视角) 检测框就混入夹爪 → 漂 2-9cm (实锤)。
            #   peg 静止 (工件) → 首轮定位 (_reloc=True) 高位刷新 1mm 后即锁存;
            #   滑脱/遇阻回接近重抓 (置 _reloc=True) 时解冻重定位被碰移的销。
            allow_loc = bool(getattr(self, "_reloc", True))
            frozen = st in ("下降", "抓取") or bool(self.grasped)
            if not frozen and allow_loc:
                frozen = float(self.x[2]) - peg_z0 < 0.06   # 手已贴近(悬停线下) = 遮挡区
            if not allow_loc:
                frozen = True                                # 已定位锁存
            # 🐛 2026-09-07 静静: 幻影免疫 — 夹爪接近时 YOLO 光模块框会锁到夹爪上
            #   (vis_peg≈hand, z=0.083=夹爪高度, 误差 92mm 实锤)。躺台面的 peg 未被夹持时
            #   z 必≈台面 (geom.peg_z0±半径); z 超窗 = 检测到夹爪/其它 → 丢弃。
            #   (peg 被碰移仍在台面 z 不变, 不误杀; 真机同构: 托盘高度一次标定)
            if det3d.get("光模块") is not None:
                _p = np.asarray(det3d["光模块"], dtype=float)
                _ghost = (not frozen and not self.grasped
                          and abs(float(_p[2]) - peg_z0) > 0.02)
                _old = self._vis["peg"]
                if _ghost:
                    # 幻影: 不采信不 EMA (检测仍记录在 det3d/检出率 — 诚实)
                    self._vis["ghost"] = self._vis.get("ghost", 0) + 1
                    self._vis["pend"] = None
                    self._vis["peg"] = _old          # 保持旧估值 (None 则 None)
                elif _old is not None and not frozen:
                    _d = float(np.linalg.norm(_p - _old))
                    if _d < 0.05:
                        _p = 0.5 * _p + 0.5 * _old          # EMA (悬停多次刷新收敛)
                        self._vis["pend"] = None
                    else:
                        # 大跳变: 连续 2 帧同候选确认才采信 (单帧=误检丢弃; 2 帧=工件真被碰移)
                        _pend = self._vis.get("pend")
                        if _pend is not None and float(np.linalg.norm(_p - _pend[1])) < 0.02:
                            self._vis["pend"] = (_pend[0] + 1, _p)
                            if _pend[0] + 1 >= 2:
                                self.log(f"🎯 视觉 peg 大跳变 {_d*100:.0f}cm 连续确认 → 采信 (销被碰移)")
                                _p = 0.5 * _p + 0.5 * _old
                                self._vis["pend"] = None
                            else:
                                _p = _old
                        else:
                            self._vis["pend"] = (1, _p)
                            _p = _old
                    self._vis["peg"] = _p
                    self._reloc = False                      # 定位完成 → 锁存 (手再低不刷新)
                elif _old is not None:
                    self._vis["peg"] = _old                  # frozen: 保持冻结值
                else:
                    self._vis["peg"] = _p                    # 首帧直接采信 (悬停位)
                    self._vis["pend"] = None
                    self._reloc = False
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
            # 🧩 2026-09-07: 当前阶段写入 _vis (线程安全共享) → GUI 轮询读到 → 原子技能 SK 节点高亮
            self._vis["stage"] = st or ""
            # 📸 2026-09-08: VLM 真实编码关键帧 — 每阶段第 6 帧存一张 (画面稳定后),
            #   供 node_ss_vlm 真实编码 (SmolVLM 吃真实渲染图, 不造假); 回退重进同阶段会覆盖
            if img is not None and st:
                if st != self._kf_stage_prev:
                    self._kf_stage_prev = st
                    self._kf_cnt = 0
                else:
                    self._kf_cnt += 1
                if st not in self._key_frames and self._kf_cnt >= 6:
                    self._key_frames[st] = np.asarray(img).copy()
            if os.environ.get("R0_TRACE"):
                o = np.asarray(self.env._get_obs(), dtype=np.float64).ravel()
                _pe = np.linalg.norm(self._vis["peg"] - o[4:7]) if self._vis["peg"] is not None else float("nan")
                print(f"  [vis] 检出{n}/2 · peg误差{_pe*1000:.0f}mm"
                      f" · vis_peg={np.round(self._vis['peg'],3) if self._vis['peg'] is not None else None}"
                      f" · 真peg={np.round(o[4:7],3)}", flush=True)
            return n
        except Exception as e:
            # 🐛 2026-09-04: 异常必须显性 (GUI 里 log 可能是 no-op, 吞掉 = 断点进不去还找不到原因)
            import traceback as _tb
            _tb.print_exc()
            self.log(f"⚠️ YOLO 刷新失败: {e}")
            self._vis["miss"] += 2
            self._vis["shot"] += 1
            return 0

    # ── 每轮复位: 现场采样几何 ──
    def _reset(self, seed):
        env = self.env
        # 🎯 L4 干扰: 每轮 reset 重新允许注入 (注入一次/轮)
        self._jitter_done = False
        # 🐛 2026-09-04 静静 (测试顺序耦合实锤): metaworld reset(seed=…) **忽略 seed**
        #   (sawyer_xyz_env.py: seed param "Ignored, use seed() instead") — 解冻后
        #   _get_state_rand_vec 走 **全局 np.random.uniform**, 布局由进程全局随机状态
        #   决定 → 同一 seed 在不同用例序列后给出不同光模块位置 (复现: seed100 光模块头初位
        #   [0.0283,0.5398] vs 污染后 [0.0345,0.6169]), 500 步插不进孔 (基线 6/12 根源)。
        #   修复: 采样前固定全局 np.random, 让 seed 真正决定布局 (可复现, 非造假 —
        #   不同 seed 仍给出不同布局, 同 seed 恒同布局)。
        import numpy as _npg
        env._freeze_rand_vec = False
        _npg.random.seed(seed * 7919 + 13)
        env.reset(seed=seed)
        env._freeze_rand_vec = True
        d = env.data
        # 🎯 2026-09-09 L4 干扰注入: 拿起前把光模块(peg free body)移位+转向 (qpos 注入 →
        #   mj_forward → 现场几何/obs 重读 = 真实来料偏移; 决策链靠现场几何自恢复)
        if self._jitter_on and not self._jitter_done:
            self._inject_peg_jitter(d)
            self._jitter_done = True
        o = np.asarray(env._get_obs(), dtype=np.float64).ravel()
        # 现场几何 (metaworld 跨进程漂移 → 每轮从 MuJoCo data 读, 不信常量)
        self.geom = {
            "goal": d.site_xpos[self._site_goal].copy(),          # 插入终点
            "hole": d.site_xpos[self._site_hole].copy(),          # 孔口
            "peg_grasp": o[4:7].copy(),                           # 销抓握点 (obs 语义)
            "peg_head0": d.site_xpos[self._site_ph].copy(),       # 光模块头初始
            "peg_z0": float(o[6]),                                # 销初始 z (抬升判据锚)
            #   🐛 2026-09-07 静静: 原 o[4] 是 peg **x** (obs[4:7]=xyz 实锤, o[4]=0.0585 是 x,
            #   o[6]=0.03 才是 z) → 抬升锚/幻影免疫全错位。R0 曾靠抬升目标补偿巧合能跑,
            #   修后必须 R0 回归 + R1 幻影免疫才真正生效
            "hand0": o[0:3].copy(),                               # 夹爪初始
            # 🚀 2026-09-08 L3 扩展: AOI 检测工位 (固定标定设备, 同 hole 语义非随机)
            "aoi_focus": AOI_FOCUS.copy(),
            "peg0_place": o[4:7].copy(),                          # 放回目标 (body 初始位, 全链闭环)
        }
        # 🐛 2026-09-07 静静: 带孔盒中心现场采样 (metaworld 盒随布局漂移, 3D 场景要画对
        #   box 才能让孔口/插入点落在盒上 — 老倪"插入位置偏了"实锤: 写死 mouth y=0.462
        #   vs seed104 现场 0.424 偏 3.8cm)
        try:
            self.geom["box_center"] = d.xpos[env.model.body("box").id].copy()
        except Exception:
            self.geom["box_center"] = None
        # 🎯 R1: 现场孔偏移 goal−孔口 (模拟真机 CAD 已知的孔深方向/深度);
        #   视觉孔位 = YOLO hole + 此偏移 → 插入终点 (视觉只给孔口, 孔底不可见)
        self._vis["hole_off"] = (self.geom["goal"] - self.geom["hole"]).copy()
        # 光模块头相对销 body 的现场偏置 (R1 夹持后光模块头 = hand+锁存偏移+此偏置)
        self.geom["head_off"] = (d.site_xpos[self._site_ph] - o[4:7]).copy()
        # R1 视觉初始定位 (第一步前刷新, 工件位置未知 → 视觉找)
        self._vis["peg"] = self._vis["hole"] = None
        self._reloc = True            # 🐛 2026-09-07: 首轮需视觉定位; 滑脱回接近时再置 True
        # 📸 2026-09-08: VLM 真实编码关键帧缓存 (每阶段存一帧真实渲染图; R1 vision 才有)
        self._key_frames = {}
        self._kf_stage_prev = None
        self._kf_cnt = 0
        self._peg_cur = None          # 视觉 peg 控制估值 (None=尚未定位)
        self.grasped = False
        self.peg_off = None            # (保留字段, 夹持用 _grasp_off0)
        self._grasp_off0 = None
        self._off0_anchored = False    # 🐛 2026-09-07: 夹持真值锚定标志 (每轮重置)
        self._grasp_gap_z = 0.015
        self._close_steps = 0
        # 🛡 插入遇阻保护状态 (2026-09-07, seed100 滑脱实锤修复)
        self._depth_prev = float(self._insert_depth())
        self._stall = 0            # 推而不进连续帧数
        self._stall_events = 0     # 本阶段遇阻事件计数
        self._jiggle = 0           # 遇阻窗口剩余帧 (0=不在窗口)
        self._jiggle_axis = 2      # 微调轴: 先 z 后 y 交替 (保留兼容)
        self._jiggle_dir = 1.0     # 微调方向 (±) (保留兼容)
        self._retreat_then = None  # 回撤窗口结束后回退的目标阶段 (5=转移, 0=接近; None=不回退)
        self._grasp_age = 0        # 夹持锁存后帧数 (随动验证宽限期)
        # 🐛 2026-09-04 静静 (探针12 实锤): 控制锚必须用 obs[0:3] hand (腕部=真实夹爪 claw),
        #   不能用 endEffector site — site 是腕下 4cm 的虚拟视觉点, 降到 光模块 高度时真实夹爪
        #   还悬空 2-3.5cm → 空夹 (接触实验里 '光模块 接触' 实为 光模块 贴桌面, 误读成夹持).
        #   探针12: hand 降到 光模块 身 (hand_z≈peg_z+0.02 被销顶住) 闭合 grp~0.66 夹住, 抬升随动.
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
        #   夹住与否由抬起阶段 光模块 随动验证决定, 见 grasp_force)
        self.sched = self.cognition.ActionModulator(
            grasp_th=self._grasp_th,  # 夹紧度阈值 (可调; 原 0.50)
                                # 防浅夹 (obs 0.5x) 锁存即抬 → peg 未压稳滑脱 (seed100 实锤)
                                # (浅夹 0.72 就抬滑脱率高; 深夹到 0.60 以下夹持力才足)
            align_th=0.025,     # 转移→插入 孔位对准 (光模块头-孔口水平, 视觉精度余量)
            insert_depth=0.006,  # 插入→完成: 光模块头离终点 6mm 内算完成 (metaworld 插入物理
                                #   精度余量; 引擎 0.004 在真实物理下差 0.1mm 磨死 — ep5 实锤)
            lift_h=0.08,        # 抬起→转移: 销升 8cm (孔口高 0.13, 销初始 0.03 — 升够才平移防撞台)
            max_veto=5,
            mode=self.mode,     # 🚀 2026-09-08: insert / full (插拔+AOI 闭环)
        )
        # 🚀 2026-09-08 L3 扩展 (mode=full): AOI/放回 流程状态 (每轮重置)
        self._aoi_hold = 0          # AOI检测 对焦保持帧数 (到位后累计 = 采图时长)
        self._drop_ready = False    # 放下: 到位触台 → 开爪标志
        self._drop_released = False # 放下: 开爪完成 (观测夹爪已开) → 可判完成
        self._f_max = 0.0           # 全轮接触力峰值 (AOI 报告过程指标)
        self._depth_min = 9.9       # 插入段最小残余深度 (离孔底, AOI 报告)
        self._aoi_report = None     # AOI 检测报告 (PASS/FAIL + 真实过程指标)
        self._went_back_0 = False   # 是否曾回接近重抓 (AOI 报告过程指标)
        self.stage_hist = []
        self._grasp_off0 = None    # 锁存瞬间 光模块−x (随动验证锚)
        self._grasp_gap_z = 0.015  # 锁存瞬间 夹爪z−销z (抬升目标补偿)
        self._off_prev = None      # 上一帧 光模块−夹爪 (真值随动跟踪, 锚定判据 v2)
        self._x_prev = None        # 上一帧 夹爪位置 (判夹爪是否在动 — 抬升试探锚定)
        self._close_steps = 0      # 抓取阶段闭合指令持续步数
        self._z_stall = 0          # 下降停滞帧数 (被销/台顶住判据)
        self._z_prev = None        # 上一帧 hand z
        self._ins_dev = 0          # 插入段 site-推算偏差连续帧数 (peg 夹爪内滑守卫)
        # 插入阶段最小推力: 光模块头进孔后摩擦阻力大, 比例项趋零 → 无 v_min 会磨死在孔口
        #   (ep3 插到 13mm 推不动 96 步实锤; 引擎 STAGE_V_MIN 无插入, 真实物理需要)
        self.sched.v_min["插入"] = 0.02

    # ── 🎯 L4 干扰注入 (2026-09-09): 拿起前光模块被移动位置+转换角度 ──
    #   peg = mujoco free body (qpos 7 维: 平移3+四元数4); 注入后 mj_forward →
    #   现场几何/obs 全重读 → 决策链解析伺服自动跟踪新摆放 (容忍干扰), 插入目标(孔)不动
    def _inject_peg_jitter(self, d):
        try:
            import mujoco as _mj
            import numpy as _npg2
            m = self.env.model
            _adr = None
            # peg body 的 joint (探针: body 'peg' jntadr=9 → free 7维 qpos); joint 名未必含 'peg'
            for _i in range(m.nbody):
                if m.body(_i).name == "peg":
                    _j = m.body_jntadr[_i]
                    if _j >= 0 and m.jnt_type[_j] == 0:   # 0 = FREE
                        _adr = m.jnt_qposadr[_j]
                    break
            if _adr is None:
                self.log("⚠️ L4 干扰: 未找到 peg 自由度, 跳过")
                return
            _rng = _npg2.random.RandomState(918273 + int(self.seed) * 131
                                            + getattr(self, "_jitter_round", 0) * 37)
            _ov = getattr(self, "_jitter_override", None)   # 显式干扰 (回归测试用)
            if _ov:
                _dxy = _npg2.array([_ov.get("dx", 0.0), _ov.get("dy", 0.0)])
                _dz = _ov.get("dz", 0.0)
                _yaw = _ov.get("yaw", 0.0)
                _shell90 = _ov.get("shell90", True)
            else:
                _dxy = _rng.uniform(-0.035, 0.035, 2)     # 台面平移 ±3.5cm
                _dz = _rng.uniform(-0.004, 0.010)         # 高度微扰
                # 🧩 2026-09-09 (C1b): peg 物理转角 ±15° 可成功域; 光模块体壳 = 刚性贴体
                #   装饰 (hinge 铰接破坏抓取动力学实锤 → 无独立 90° 旋转; 90° 干扰动作由
                #   视频动画层表达, 真机 6 轴末端回正)
                _yaw = _rng.uniform(-0.26, 0.26)          # ±15° (物理可成功域)
                _shell90 = False
            q = d.qpos.copy()
            q[_adr:_adr + 3] += [_dxy[0], _dxy[1], _dz]
            _c, _s = float(_npg2.cos(_yaw / 2)), float(_npg2.sin(_yaw / 2))
            q[_adr + 3:_adr + 7] = [_c, 0.0, 0.0, _s]   # 绕 z (竖轴) 旋转
            d.qpos = q
            # 🧩 2026-09-09 (C1): 光模块体壳水平旋转 90° (shell hinge) — 视觉干扰表达;
            #   peg 物理本体只转可成功域小角 (长条盒 90° 无绕z DOF 夹不起实锤)
            try:
                if _shell90:
                    for _j2 in range(m.njnt):
                        if m.jnt(_j2).name == "shell_yaw":
                            _qa = d.qpos.copy()
                            _qa[m.jnt_qposadr[_j2]] = float(_npg2.pi / 2)
                            d.qpos = _qa
                            break
            except Exception:
                pass
            try:
                _mj.mj_forward(m, d)
            except Exception:
                pass
            self._jitter_meta = {
                "dx_cm": round(float(_dxy[0]) * 100, 1),
                "dy_cm": round(float(_dxy[1]) * 100, 1),
                "dz_mm": round(float(_dz) * 1000, 1),
                "yaw_deg": round(float(_npg2.degrees(_yaw)), 1),
                "shell90": bool(_shell90),   # 🧩 光模块体壳水平转 90° (视觉)
            }
            # 🐛 2026-09-09 实锤: 肌肉记忆固化标杆按"场景=seed"命中 → 干扰布局(peg 移位)误重放
            #   旧动作 → 把 peg 推飞死循环 (diag: 225 步对位卡死 + peg 漂移 10cm)。分层语义:
            #   标杆绑定摆放 → 布局变了标杆失效 → 关快通道, 全精算伺服 (L2 能力不丢, 只在
            #   不匹配时正确降级; 无干扰轮 muscle 照常)
            if getattr(self, "_mm_on", False):
                self._mm_on = False
                self.log("🧠 L4 干扰: 肌肉记忆旁路关闭 (摆放已变无标杆) — 全精算伺服适应")
            self.log("🎯 L4 抗干扰测试: 拿起前光模块已移位 "
                     f"Δ=({_dxy[0]*100:+.1f},{_dxy[1]*100:+.1f})cm dz={_dz*1000:+.0f}mm "
                     f"· 转向 {_npg2.degrees(_yaw):+.0f}° — 现场几何重读, 决策链自主适应")
        except Exception as _ej:
            self.log(f"⚠️ L4 干扰注入失败: {_ej}")

    # ── 阶段子目标 (八阶段, 几何全现场, 锚 = 夹爪) ──
    # 夹持前 (接近→抓取): 目标 = 销抓握点上方 — ⚠️ 用**实时光模块位置** self._peg_cur
    #   (回退重抓时销可能被首次下降碰移, 静态采样坐标会空夹 — ep3-5 失败实锤)
    # 夹持后 (抬起→插入): 目标由"光模块头当前位置 + 实时夹爪偏移"驱动 —
    #   光模块头相对夹爪的方向/距离锁存后不变, 把光模块头送到孔口/终点即得夹爪目标
    def _stage_target(self):
        g = self.geom
        st = self.sched.stage()
        pg = getattr(self, "_peg_cur", g["peg_grasp"])     # 实时光模块位置 (obs[4:7])
        if pg is None:
            # 🐛 2026-09-07: R1 视觉尚未定位 peg → 原地悬停等检出 (诚实, 不回落真值)
            return np.array([self.x[0], self.x[1], self.x[2] + 0.01])
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
        off = self.peg_head() - self.x          # 实时光模块头-夹爪偏移 (夹持后锁存不变)
        if st == "转移":
            return self._hole_p() + np.array([0.0, 0.0, 0.02]) - off   # 光模块头到孔口上方 2cm
        if st == "插入":
            # 🐛 2026-09-06 静静: 两段式插入 — ①peg 头垂直对齐孔口中心高度 (z_err≤4mm)
            #   ②沿孔轴水平推入孔底。原单段直线(悬高2cm→孔底)是斜插: peg 头圆柱端面
            #   无倒角 (mujoco 刚体) → 端面下缘顶孔口上缘 → z 卡在孔口上方 5-10mm 磨死
            #   (seed109 实锤: z孔偏+0.010 depth 6.3cm 卡 56 步后滑脱)。
            hp = self._hole_p()
            ph_now = self.peg_head()
            # 🐛 2026-09-07 静静 (seed100 遇阻实锤): z 对齐判据 4mm → 1.2mm —
            #   孔间隙仅 1-2mm (peg 半径 15mm 无倒角刚体), 残留 z_err 2.6mm 水平推必顶
            #   孔口上沿 (遇阻#1 实测 z_err=+2.6mm 卡死; z 校到 0.6mm 即推进 1.5mm)。
            if abs(float(ph_now[2] - hp[2])) > 0.0012:
                # 段① 垂直降: xy 保持 (转移已对准), z 降到孔口中心
                return np.array([ph_now[0], ph_now[1], hp[2]]) - off
            return self._goal_p() - off          # 段② 水平推入 (z 已同轴)
        # 🚀 2026-09-08 L3 扩展 (mode=full): 拔出/AOI/回程/放下 目标 (全头语义 ph→目标点, 锚=夹爪)
        if st == "拔出":
            # 两段式: ①沿孔轴反方向拉出 (头到孔外 PULL_BACK, 同孔高) ②垂直抬离
            #   (头高于孔口 0.10 — 平移不刮盒沿); _insert_depth() 与 advance 同判据
            axis = (g["goal"] - g["hole"])
            axis = axis / (float(np.linalg.norm(axis)) or 1.0)
            exit_pt = g["hole"] - axis * PULL_BACK          # 孔外拉出点 (孔高)
            if self._insert_depth() <= getattr(self.sched, "pull_out_m", 0.045):
                ph_t = np.array([exit_pt[0], exit_pt[1], g["hole"][2]])
            else:
                ph_t = np.array([exit_pt[0], exit_pt[1], g["hole"][2] + 0.10])
            return ph_t - off
        if st == "AOI转移":
            return g["aoi_focus"] + np.array([0.0, 0.0, AOI_HOVER]) - off
        if st == "AOI检测":
            return g["aoi_focus"] - off          # 光模块头到镜头对焦点 (悬停检测位)
        if st == "回程":
            return g["peg_head0"] + np.array([0.0, 0.0, 0.05]) - off
        if st == "放下":
            return g["peg_head0"] - off          # 光模块头落回初始位 (放件, 随后开爪)
        return self._goal_p() - off                                     # 插入/完成: 光模块头到终点

    def peg_head(self):
        """光模块头世界坐标 (夹持后=编码器 hand+锁存偏移+头偏置 — 真机同构, 无 site 依赖,
        off 锁死不追滑脱; 滑脱由随动验证回退。未夹持: R0=site 真值 / R1=视觉)"""
        # 🧪 R0 诊断开关 (SS_R0_SITE_PEGHEAD=1): 夹持后也返回 site 真值 —
        #   验证失败轮是"感知对准误差"(可感知修)还是"夹持几何物理"(不可调参修)
        if os.environ.get("SS_R0_SITE_PEGHEAD") == "1" and not self.vision:
            return self.env.data.site_xpos[self._site_ph].copy()
        if self.grasped and self._grasp_off0 is not None:
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
        """夹爪-销抓握点 水平距离 (接近/对位/下降推进证据; 实时光模块位置)"""
        pg = getattr(self, "_peg_cur", self.geom["peg_grasp"])
        if pg is None:
            return 9.9   # 未定位 → 视为远离 (不推进)
        return float(np.linalg.norm(self.x[:2] - pg[:2]))

    def _d_hole_h(self):
        """光模块头-孔口 水平距离 (转移→插入 推进证据; 孔口=感知位置)"""
        return float(np.linalg.norm(self.peg_head()[:2] - self._hole_p()[:2]))

    def _insert_depth(self):
        """光模块头到插入终点距离 (插入→完成 证据; 终点=感知孔口+CAD偏移)"""
        return float(np.linalg.norm(self.peg_head() - self._goal_p()))

    # ── 主循环 ──
    def run(self, max_steps=None, cap=None):
        """R0 主循环 — metaworld 单轮硬上限 (insert 默认 500 步 / full 全链 2000 步)。

        🐛 2026-09-08 静静: 原默认 500 步 — mode=full (插拔+AOI 13 段) 实测需 850-1000 步,
        默认 500 必截断未完成 (45ce9453 GUI 接线漏传 max_steps → GUI 勾 L3 全链同样截断,
        09-08 实锤)。显式传 max_steps 仍可覆盖。
        🚀 2026-09-08 L4 档 (cap="l4"): 自主恢复 — 失败回退/重抓不放弃, 预算 ×2
        (full 4000 / insert 1000), 直到最终完成任务或真死局 (物理不可恢复); 引擎分级
        回退 (遇阻/空夹/滑脱→重对孔/重抓) 即恢复执行体, L4 只给足恢复预算 + 标注。"""
        self._cap = cap
        # 🐛 2026-09-09: GUI 档位是大写 "L4", 引擎判小写 "l4" → 预算×2 从未生效 (静态核实)
        cap = str(cap).lower() if cap else None
        if cap == "l4":
            self.log(f"🏆 L4 自主恢复档: 失败回退不放弃 (预算 ×2) — 直到任务最终完成或物理死局")
            # 🎯 2026-09-09 L4 抗干扰: 拿起前光模块移位/转向 自动注入 (每轮新干扰)
            self._jitter_on = True
            self._jitter_round = getattr(self, "_jitter_round", 0) + 1
        else:
            self._jitter_on = False
        if max_steps is None:
            max_steps = (MAX_STEPS * 2 if cap == "l4" else MAX_STEPS) if self.mode == "full" \
                else (1000 if cap == "l4" else 500)
        env = self.env
        self._reset(self.seed)
        # 🧠 2026-09-07 肌肉记忆: 本轮观察开始 (记录各技能段轨迹; 失败轮不固化)
        if getattr(self, "_mm_on", False) and self.muscle is not None:
            try:
                self.muscle.begin_episode(self.seed)
            except Exception:
                pass
        tr = {"t": [], "dist": [], "u_ff": [], "residual": [], "contact_p": [], "u_sat": [],
              "stage": [], "done": [], "x": [], "gripper": [], "force": [], "peg": [],
              "peg_head": [], "site_ph": [], "target": [], "grasped": [], "obs": [], "u_ff_vec": [],
              "u_sat_vec": [], "u_fb_vec": [], "u_fuse_vec": [], "u_limit_vec": [],
              "u_exec_vec": [], "v_vec": [], "z_k_vec": [], "io_trace": [],
              "latent_vec": [], "prior_vec": [], "corrected_vec": [], "residual_vec": [],
              # 🧮 2026-09-07: 流形层全程序列 (对齐引擎 tr keys — Scope 流形格/波形消费顶层
              #   mani_*, 非 io_trace; 真实化轨迹此前无 → Scope 流形格空 = 老倪"流形没输出")
              "mani_risk": [], "mani_progress": [], "mani_eta": [], "mani_V": [],
              "mani_rem": [], "mani_dperp": [], "mani_pred": [],   # 🧠 2026-09-08: JEPA 预测流形 (旁路 6 维)
              "z7_vec": [],   # 🧠 2026-09-09: 旁路 z R7 (夹持后 x→光模块头) 供 predictor 训练同构采集
              "probe_seq": []}   # 🔭 2026-09-05: 每步前馈探针 (播放逐帧同步直方图/归因)
        done = False
        truncated = False
        for step in range(int(max_steps)):
            # ⏹ 2026-09-09: 停止请求 (GUI ⏹停止/🔄重启先置 _abort=True → 本步末退出,
            #   线程 join 后才允许开新引擎 — 双 metaworld env 并发 mujoco C segfault 实锤)
            if getattr(self, "_abort", False):
                self.log("⏹ 收到停止请求 — 本轮提前结束 (引擎线程退出中)")
                break
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
            # 🎯 L4 死局早停 (2026-09-09): 仅**未夹持**时 peg 在台面被夹爪推移 >10cm
            #   或压翻(z<0.012) → 本布局不可恢复 → break 交 attempts 层换新干扰布局重试
            #   (夹持转移段 peg 离初始 >10cm 是正常 → grasped 时跳过, 防误杀)
            if cap == "l4" and not getattr(self, "grasped", False) \
                    and step > 80 and step % 40 == 0:
                try:
                    _pg0 = self.geom.get("peg_grasp")
                    _pgc = o[4:7]
                    _drift = float(np.linalg.norm(_pgc - _pg0)) if _pg0 is not None else 0.0
                    if _drift > 0.10 or float(_pgc[2]) < 0.012:
                        self.log(f"🎯 L4 布局死局检测: 未夹持但 peg 漂移 {_drift*100:.0f}cm / "
                                 f"z={_pgc[2]:.3f} (被碰移/压翻) → 换新干扰布局重试")
                        truncated = True
                        break
                except Exception:
                    pass
            # 📸 2026-09-08: 数据采集帧钩子 (smolvla 图像数据集生成; 默认 None 零开销)
            if self._frame_sink is not None:
                try:
                    self._frame_sink(self, act, o)
                except Exception:
                    pass
            # 🎯 R1 真实视觉: **每帧渲染 + detect_3d** (老倪红线: 不能造假 — 禁用节流/冻结/
            #   复用旧值). 每步 env.step 后 render() → YOLO 检测 → 本帧真值.
            #   ⚠️ 成本: ~0.5-1s/步 × 500 步 ≈ 4-9 分钟/轮 (真流程的代价, 接受)
            #   ⚠️ 物理事实: 固定相机下夹爪贴近工件会遮挡 → 光模块 检测崩 (真实感知退化,
            #      不掩盖 — 这正是 RealityGap 要暴露的; 真机用 eye-in-hand 相机解决)
            if self.vision and self._aligner is not None:
                self._vis_refresh()
            x_new = o[0:3].copy()
            self.v = (x_new - self.x) / DT_ENV if step > 0 else np.zeros(3)
            self.x = x_new
            self.gripper = float(o[3])
            # 下降停滞检测 (被销/台顶住): 每步 z 位移 <0.4mm 累计; 连续 ≥8 帧 = 物理接触顶住.
            #   (R1 视觉 光模块 z 偏低 1.5cm 实测 — at_grasp_pose 用视觉 z 会永远等不到, 卡下降)
            #   🚀 2026-09-08: 放下段也统计 (放件触台判据 _z_stall>=6 → 开爪)
            if self._z_prev is not None and self.sched.stage() in ("下降", "抓取", "放下"):
                if abs(x_new[2] - self._z_prev) < 0.0004:
                    self._z_stall += 1
                else:
                    self._z_stall = 0
            else:
                self._z_stall = 0
            self._z_prev = float(x_new[2])
            # 光模块位置感知: 夹持后 = 编码器 hand+锁存偏移 (真机无视觉跟销);
            # R1 未夹持 = YOLO 光模块 (首轮/回退高位定位, 遮挡冻结); R0 = obs 真值
            if self.grasped and self._grasp_off0 is not None:
                self._peg_cur = (self.x + self._grasp_off0).copy()
            elif self.vision:
                # 🐛 2026-09-07 静静: R1 视觉未检出/冻结 → 保持上次估值 —
                #   禁止回退 obs 真值 o[4:7] 冒充检测 (老倪红线; 原 else 分支泄漏真值)
                if self._vis["peg"] is not None:
                    _pv = np.asarray(self._vis["peg"], dtype=float).ravel()
                    # 🐛 2026-09-09: 形状守卫 — F5 调试下偶现 0D/异常形状检测值
                    #   (concat dims 崩 698 实锤), 丢弃保持旧估值 (同幻影免疫哲学)
                    if _pv.size == 3:
                        self._peg_cur = _pv
                    elif getattr(self, "_peg_shape_warned", 0) < 3:
                        self._peg_shape_warned = getattr(self, "_peg_shape_warned", 0) + 1
                        self.log(f"⚠️ 防御: 视觉 peg 形状异常 {np.asarray(self._vis['peg']).shape} "
                                 f"→ 丢弃保旧估值 (来源 detect_3d 输出)")
                # else: 保持 self._peg_cur (None → _stage_target 原地等待定位)
            else:
                self._peg_cur = o[4:7].copy()   # 🧩 2026-09-09: 中心抓实验失败还原 (90° 指缝物理夹不住)
            g = self.geom
            # ③ 接触力合成 (几何合成; metaworld 无力传感器; 光模块头=peg_head() 感知一致)
            force = np.zeros(6)
            ph = self.peg_head()                             # 当前光模块头 (感知语义)
            if not self.grasped:
                gap_z = 0.0 if self._peg_cur is None else max(
                    0.0, 0.012 - (self.x[2] - self._peg_cur[2]))
                if self._d_xy_peg() < 0.03 and gap_z > 0:
                    force[2] = K_CONTACT * max(gap_z, 0.5 * D_CONTACT)
            else:
                dh = self._d_hole_h()
                if dh < D_CONTACT:
                    force[2] = K_CONTACT * max(0.0, D_CONTACT - dh)
            force_norm = float(np.clip(force[2] / (K_CONTACT * D_CONTACT), 0.0, 1.0))
            # 🐛 R1: 几何抓握位姿 — 水平对准视觉 光模块 + 下降停滞 (z 连续 ≥8 帧不动 = 被销/台顶住,
            #   指已包住销身). 视觉 光模块 z 偏低不可信, 不用 z 阈值 (0/6 卡下降实锤)
            at_grasp_pose = bool(self._d_xy_peg() < 0.03 and self._z_stall >= 8)
            # ④ 39D 视觉结构 (引擎语义骨架; 感知一致: 销=_peg_cur, 终点=_goal_p)
            _pc = self._peg_cur
            if _pc is None:
                _pc = np.zeros(3)                     # 未定位 → 视觉零占位 (控制语义仍走 _peg_cur=None 等待)
            elif np.asarray(_pc).ndim != 1 or np.asarray(_pc).size != 3:
                # 🐛 2026-09-09 兜底: _peg_cur 形状异常 (0D/2D) → 置零占位不崩 (根因守卫见 676)
                if getattr(self, "_peg_shape_warned", 0) < 3:
                    self._peg_shape_warned = getattr(self, "_peg_shape_warned", 0) + 1
                    self.log(f"⚠️ 防御: _peg_cur 形状 {np.asarray(_pc).shape} → concat 置零占位")
                _pc = np.zeros(3)
            cur = np.concatenate([self.x, [self.gripper], self.v,
                                  _pc, self._goal_p(), np.zeros(3), np.zeros(2)])
            prev = self.obs_prev if self.obs_prev is not None else cur
            target = self._stage_target()
            # 🧠 2026-09-07 肌肉记忆 (仿小脑): ①观察 — 每帧记录 (stage, x, u_exec);
            #   ②快通道 — 固化标杆后整段 u_exec 重放 (跳过 MLP 精算, "练熟的动作
            #   小脑直接给力"); 安全链 (decide/反馈/饱和限幅) 全保留。
            if getattr(self, "_mm_on", False) and self.muscle is not None:
                try:
                    _stg = str(self.sched.stage()).replace("阶段 ", "").split("·")[0].strip()
                    if _stg != self._mm_stage:          # 阶段切换 → 段步计数重置
                        self._mm_stage = _stg
                        self._mm_step = 0
                    # 观察 (每帧喂 u_exec 待算 → 用上帧值; 段切换首帧用当前 u)
                    _u_obs = getattr(self, "_u_vec", np.zeros(4))
                    self.muscle.feed(_stg, self.x, _u_obs)
                    # 快通道整段重放: run() 开头已预取标杆 (_mm_mode="replay")
                    # → 每帧 u_ff 在下方 ⑤ 段被 _mm_u 接管 (见 u_ff 替换)
                    self._mm_step += 1
                except Exception:
                    pass
            visual39 = np.concatenate([cur, prev, target])
            tactile4 = np.array([self.gripper, float(self.grasped), 0.0, 0.0])
            obs = self.perception.fuse_sensors(visual39, force, tactile4)
            # ⑤ 六层控制器 (同引擎: 前馈→估计→预测→校正→调度→限幅→执行)
            # 🧠 分层伺服 (2026-09-06 晚, 同 gen 采集管道): 前段 = 蒸馏 MLP 真实主执行
            #   (多布局重训, 域守卫兜底); 插入段 = 毫米级接触 → 解析伺服精插
            st_now = self.sched.stage()
            u_ff = (self.accel.analytic_forward(obs) if st_now == "插入"
                    else self.accel.forward(obs))
            # 🧠 2026-09-07 肌肉记忆快通道 (仿小脑): 固化标杆后整段 u_exec 直接重放 —
            #   "动作练熟, 小脑自动执行": 前馈 u_ff = 标杆序列同帧值 (跳过 MLP 精算);
            #   安全链 (decide/反馈/饱和限幅) 全保留 — 若环境异常偏离, 残差/接触反馈
            #   仍会让 decide 修正, 不会瞎冲。插入段(毫米级)仍走解析伺服精插。
            _stn = str(st_now).replace("阶段 ", "").split("·")[0].strip()
            if (getattr(self, "_mm_on", False) and self.muscle is not None):
                # 阶段切换 → 预取该段标杆
                if _stn != getattr(self, "_mm_seg", ""):
                    self._mm_seg = _stn
                    self._mm_i = 0
                    if _stn in ("接近", "对位", "下降", "抓取", "抬起"):
                        _cu, _cx = self.muscle.get_champ(self.seed, _stn)
                        self._mm_u = _cu
                    else:
                        self._mm_u = None   # 转移/插入/完成: 实时决策 (毫米级)
                # 重放: 有标杆且未耗尽 → 前馈用标杆
                if self._mm_u is not None and self._mm_i < len(self._mm_u):
                    u_ff = self._mm_u[self._mm_i]
                    if self._mm_hits == 0:
                        self.log(f"🧠 肌肉记忆快通道: {_stn} 段标杆 u_exec 重放 (小脑接管前馈)")
                    self._mm_hits += 1
                    self._mm_i += 1
            act4 = np.concatenate([self.u_prev[:3], [0.0]])
            latent_pred = self.est.predict(self.latent, act4)
            prior = self.dyn.predict(self.latent, act4)
            z_k = np.concatenate([self.x, [force_norm]])       # R0 直读无噪声
            corrected, residual = self.cognition.state_correction(prior, z_k, K=0.5)
            residual = np.asarray(residual, dtype=float).copy()
            residual[3] = force_norm
            r_scalar = float(np.linalg.norm(residual))
            contact_p = float(self.cognition.contact_probability(r_scalar, gain=8.0))
            # 🧠 右脑 contact 融合 (2026-09-06 晚, 多布局重训 acc 0.998): 训练 WM 判闭爪
            #   时机作证据, 与经验残差公式取 max — 域外返回 None → 公式兜底
            _cw = self.dyn.contact_of(np.asarray(obs, dtype=np.float32)[:39], act4)
            if _cw is not None:
                contact_p = max(contact_p, _cw)
            self.latent = self.est.update(latent_pred, corrected)
            # 🧭 3D 视图向量通道 (对齐引擎 tr 格式 — 2026-09-07 老倪: sim.run 轨迹喂
            #   DreamView3D 缺 residual_vec KeyError 崩; 引擎同款: prior/latent/corrected/residual)
            tr["prior_vec"].append(np.asarray(prior, dtype=float).copy())
            tr["latent_vec"].append(np.asarray(self.latent, dtype=float).copy())
            tr["corrected_vec"].append(np.asarray(corrected, dtype=float).copy())
            tr["residual_vec"].append(np.asarray(residual, dtype=float).copy())
            self.res_ema = (0.85 * self.res_ema + 0.15 * np.asarray(residual, dtype=float)
                            if self.res_ema is not None
                            else np.asarray(residual, dtype=float).copy())
            u_fb = np.concatenate([np.clip(0.5 * self.res_ema[:3], -0.5, 0.5), [0.0]])
            u, stage = self.sched.decide(u_ff, u_fb, contact_p, r_scalar)
            # 🔭 2026-09-05: 真实化探针快照(含阶段) — 播放逐帧同步直方图/归因/阶段色带
            # 🧠 前馈探针 (真实 MLP 激活, 诊断通道): 2026-09-08 老倪目检实锤 — 真实化主路径
            #   是解析伺服 (09-06 决策, 布局域外 MLP 输出反向), accel.probe 恒空 → 前馈激活
            #   直方图/归因窗口无数据。修复: 每步补一次真 MLP 前向**仅填探针, 不参与控制**,
            #   直方图展示的是真实 MLP 在想什么 (若主路径为 MLP 则本就是同一次前向)。
            try:
                _acc = self.accel
                if _acc is not None and getattr(_acc, "_ff", None) is not None:
                    # 每步重算诊断前向 → probe_seq 逐帧真实 MLP 激活
                    # (MLP 主路径时 = 与 forward 同一次前向, 多算一次仅 0.1ms 级)
                    # ⚠️ 勿 clear(): _ff 覆盖全部探针 key 且 _seq 自增 — clear 会把 _seq
                    #   重置为恒 1, 直方图窗口按 _seq 去重 → 灌入帧全被当重复丢弃 (08-22 实锤)
                    _acc._ff(np.asarray(obs[:39], dtype=np.float32))
                _pr = _acc.probe
                if _pr is not None and _pr.get("act_raw") is not None:
                    _snap = dict(_pr)
                    _snap["stage"] = stage
                    tr["probe_seq"].append(_snap)
            except Exception:
                pass
            if np.ndim(u) == 0:
                u = np.zeros(4)
            u = np.asarray(u, dtype=float).copy()
            u[3] = self.sched.gripper_cmd(u_ff[3])
            u_sat = self.safety.saturate(u, limit=0.6)
            u_sat = np.asarray(u_sat, dtype=float).copy()
            u_sat[3] = float(u[3])
            # 🚀 2026-09-08 L3 扩展: 放下放件 — 到位后开爪指令直接覆盖 (状态机保持
            #   "抓取起锁存闭合", 放件属引擎执行细节: 先松爪, 爪开观测后判完成)
            if getattr(self, "_drop_ready", False) and not getattr(self, "_drop_released", False):
                u_sat[3] = 0.0
            # 🛡 插入段 site-推算偏差守卫 (2026-09-07 晚 静静, 重抓位置策略核心):
            #   peg 在夹爪内滑 → 编码器推算 peg 头 = "假对准" (实测 site-推算差 5→20mm 递增),
            #   毫米级插入下推算引导无意义; 偏差 >8mm 连续 3 帧 → 立即回接近重抓 (刷新锁存
            #   偏移), 不等随动验证 (滑动常被 20 帧宽限吞, seed100/105 实锤) 也不等遇阻 3 次。
            #   R0 用 site 真值; R1/真机同构替代 = 力觉/视觉偏差 (插入段视觉 peg 被遮挡)。
            if (st_now == "插入" and self.grasped and not self.vision
                    and self._grasp_off0 is not None):
                _sdev = float(np.linalg.norm(self.env.data.site_xpos[self._site_ph]
                                             - self.peg_head()))
                if _sdev > INS_DEV_MM:
                    self._ins_dev += 1
                    if self._ins_dev >= INS_DEV_FRAMES:
                        self._ins_dev = 0
                        self.grasped = False
                        self._grasp_off0 = None
                        self.log(f"🔄 插入感知偏差 {_sdev*1000:.0f}mm"
                                 f" (peg 夹爪内滑) → 回接近重抓刷新锁存")
                        try:
                            if self.sched.stage_idx >= 0:
                                self.sched._goto(0, "🔄 插入感知偏差大 → 回接近重抓")
                                self._reloc = True     # 回接近 → 视觉重定位被碰移的销
                        except Exception:
                            pass
                else:
                    self._ins_dev = 0
            # 🛡 插入遇阻保护 (2026-09-07 静静, seed100 滑脱实锤修复):
            #   遇阻机制 (实测): peg 头顶孔沿时推力 > 夹持保持 → peg 在夹爪内逐次受压
            #   滑动 (site真值-编码器推算差 12→15mm 递增) → 推算"假对准" → 微调按错目标
            #   瞎调无效; 回退转移时 peg 仍卡孔沿 → 拉扯脱出。
            #   策略: 遇阻确认 → 充分回撤脱离 (12帧≈15mm, 解除应力, peg 不再累积滑动)
            #   → 分级回退: 第1-2次回退转移重新对孔 (z对齐已收紧1.2mm), 第3次回退接近
            #   重抓 (peg 已滑 → 刷新锁存偏移)。真机同构: 插孔遇阻先退再对, 不硬顶。
            if st_now == "插入" and self.grasped:
                _dnow = float(self._insert_depth())
                _adv = self._depth_prev - _dnow          # >0 = peg 头在向孔底推进
                self._depth_prev = _dnow
                if _adv > 0.0008:                        # 恢复推进 → 清除遇阻状态
                    self._stall = 0
                    self._stall_events = 0
                elif self._jiggle <= 0:                  # 不在回撤窗口才累计顶住帧
                    if float(np.linalg.norm(u_sat[:2])) > 0.03:   # 指令仍在水平推
                        self._stall += 1
                        if self._stall >= INSERT_STALL_FRAMES:
                            self._stall = 0
                            self._stall_events += 1
                            self._jiggle = INSERT_JIGGLE_FRAMES    # 回撤窗口
                            if self._stall_events >= 3:
                                self._stall_events = 0
                                self._retreat_then = 0              # 回接近重抓 (刷新锁存)
                                self.log("🛡 插入遇阻 3 次 → 回撤脱离后回退接近重抓 (刷新锁存)")
                            else:
                                self._retreat_then = 5              # 回转移重新对孔
                                self.log(f"🛡 插入遇阻#{self._stall_events} → 回撤脱离后回退"
                                         f"{'转移重新对孔' if self._retreat_then == 5 else '接近重抓'}"
                                         f" [site-推算差="
                                         f"{np.linalg.norm(self.env.data.site_xpos[self._site_ph]-self.peg_head())*1000:.1f}mm"
                                         f" depth={_dnow*1000:.1f}mm]")
                    else:
                        self._stall = 0
            else:
                self._stall = 0
                self._stall_events = 0
            if self._jiggle > 0:                         # 回撤窗口: 沿孔轴反向满速, 脱离接触
                self._jiggle -= 1
                u_sat[1] = u_sat[2] = 0.0
                u_sat[0] = -float(np.sign(u_sat[0]) if abs(u_sat[0]) > 1e-6 else 1.0) * INSERT_BACKOFF_U
                if self._jiggle == 0 and getattr(self, "_retreat_then", None) is not None:
                    try:
                        if self.sched.stage_idx >= self._retreat_then:
                            self.sched._goto(self._retreat_then,
                                             f"🛡 插入遇阻回撤脱离 → 回退{'转移' if self._retreat_then == 5 else '接近'}重试")
                            if self._retreat_then == 0:
                                self._reloc = True     # 回接近 → 视觉重定位
                            self.log(f"🛡 回撤完成 → 回退{'转移重新对孔' if self._retreat_then == 5 else '接近重抓'}")
                    except Exception:
                        pass
                    self._retreat_then = None
            u_vec = self.execr.execute(u_sat)
            if np.ndim(u_vec) == 0:
                u_vec = np.zeros(4)
            self._u_vec = np.asarray(u_vec, dtype=float).copy()
            self.u_prev = self._u_vec.copy()
            # ⑥ 夹持锁存与随动验证 (R0 语义: 深夹到 grp<0.60 锁存 — 探针12 成功夹持时
            #   grp 0.66 接触建立 → 0.28 深夹; 浅夹(0.78)就抬滑脱率高 (ep3-5 失败实锤).
            #   真夹住与否由抬起阶段 光模块 随动判定 (MuJoCo: 夹住则 光模块 跟夹爪升)
            g_close = float(1.0 - self.gripper)          # 夹紧度 (1=紧; 夹住销深夹≈0.7+)
            if not self.grasped and self.sched.stage() == "抓取":
                if self.gripper < 0.82:                  # obs gripper 开始闭合 (<0.82)
                    self._close_steps += 1
                    if self._close_steps >= 3 and self.gripper < 0.60 and self._peg_cur is not None:
                        self.grasped = True              # 深夹锁存 (夹住候选)
                        self._grasp_age = 0              # 随动验证宽限期起点
                        # 锁存偏移用感知销 (R1: 视觉 光模块; R0: 真值) — 夹持后机器人"以为"的光模块位置
                        self._grasp_off0 = self._peg_cur - self.x
                        self._grasp_gap_z = float(self.x[2] - self._peg_cur[2])
                        self.log(f"🔩 夹爪深夹到位 (obs gripper={self.gripper:.2f}) → 抬升试探")
                else:
                    self._close_steps = 0
            elif self.grasped:
                self._grasp_age += 1
                # 随动验证: 夹爪移动时 光模块 相对偏移保持 = 真夹住; 滑脱/空夹 → 偏移漂移
                # 🐛 2026-09-07: 阈值 3.5cm → 8mm (宽限期 20 帧 20mm — 深夹期 peg 被挤向
                #   根部属正常, 过后 peg 漂移>8mm 即夹持失效, 早发现早重抓, 别等插入被顶脱)
                _off = o[4:7] - self.x
                _slip_th = 0.020 if self._grasp_age < GRASP_SLIP_GRACE else GRASP_SLIP_MM
                # 🐛 2026-09-08 静静 (R1 误判滑脱实锤修复): 旧锚定要求 |off−off0|<8mm 才换真值 —
                #   锁存瞬间视觉残差恰 >8mm (seed104 R1 实测 8.3mm) → 永不锚定 → 宽限期后
                #   判据偏差 (恒=视觉残差 8.3mm) > 8mm → **真夹住 (peg 真值全程随动, 几何与
                #   R0 成功轮相同) 也被判"滑脱"强制回退** → 回退碰移 peg → 反复夹不起 (09-08
                #   老倪目击)。正解: 锚定判据 = 抬升试探物理事实 — 夹爪在动 (Δx>1mm) 而 peg
                #   真值跟随 (off 帧间漂移<3mm) 即夹住, 立即锚定当前真值 off。视觉残差从此
                #   不参与夹持后判定 (真机同构: 机械夹持后工件位置由夹爪/编码器保证, 09-07 语义)。
                if (not getattr(self, "_off0_anchored", False)
                        and self._grasp_off0 is not None and self._grasp_age >= 3):
                    _dx = (float(np.linalg.norm(self.x - self._x_prev))
                           if self._x_prev is not None else 0.0)
                    _doff = (float(np.linalg.norm(_off - self._off_prev))
                             if self._off_prev is not None else 9e9)
                    if (_dx > 0.001 and _doff < 0.003) or (
                            self._grasp_age >= 15
                            and float(np.linalg.norm(_off - self._grasp_off0)) < GRASP_SLIP_MM):
                        self._grasp_off0 = _off.copy()
                        self._grasp_gap_z = float(self.x[2] - o[4:7][2])
                        self._off0_anchored = True
                        self.log(f"🎯 夹持真值锚定 (抬升试探 peg 跟手): off0="
                                 f"{np.round(self._grasp_off0,4)} "
                                 f"(视觉残差不再影响滑脱判定, 转移/插入走编码器)")
                if float(np.linalg.norm(_off - self._grasp_off0)) > _slip_th:
                    self.grasped = False                  # 掉了 → grasp_force 0 → 调度器回退重抓
                    self._grasp_off0 = None
                    self._off0_anchored = False
                    # 🐛 强制回退到接近: 滑脱时 光模块 可能半挂在夹爪上 (z 未落回台面),
                    #   advance 的"落回台面"回退判据不触发 → 卡死在转移/插入 (ep1/2/4 350步实锤)
                    try:
                        if (self.sched.RETREAT_LO <= self.sched.stage_idx <= self.sched.RETREAT_HI):
                            self._went_back_0 = True    # 🚀 AOI 报告过程指标: 曾回抓
                            self.sched._goto(0, "⚠️ 光模块滑脱 (peg 未随夹爪) → 强制回退重抓")
                            self._reloc = True     # 回接近 → 视觉重定位被碰移的销
                            self.log("⚠️ 光模块滑脱 → 强制回退接近重抓")
                    except Exception:
                        pass
                # 真值随动跟踪 (锚定判据 v2 用: 夹爪移动量 + peg 相对漂移)
                self._x_prev = self.x.copy()
                self._off_prev = _off.copy()
            # ⑦ 阶段推进 (证据全现场)
            # 🚀 2026-09-08 L3 扩展 (mode=full): AOI/放回 流程事件 + 过程指标统计
            _stg = self.sched.stage()
            self._f_max = max(self._f_max, force_norm)          # 接触力峰值 (全轮)
            if _stg == "插入":
                self._depth_min = min(self._depth_min, depth)   # 插入残余深度最小 (离孔底)
            if self.mode == "full":
                dist_aoi = float(np.linalg.norm(ph - g["aoi_focus"]))
                if _stg == "AOI检测" and dist_aoi < 0.008:      # 对焦到位 → 采图保持
                    self._aoi_hold += 1
                    if self._aoi_hold >= self.sched.aoi_hold:
                        ok = bool(self._depth_min < 0.008 and self._f_max < 1.0
                                  and not getattr(self, "_went_back_0", False))
                        self._aoi_report = {
                            "ok": ok,
                            "insert_depth_min_mm": round(float(self._depth_min) * 1000, 2),
                            "force_peak": round(float(self._f_max), 3),
                            "insert_stall_events": int(getattr(self, "_stall_events", 0)),
                            "went_back_grasp": bool(getattr(self, "_went_back_0", False)),
                        }
                        self.log(f"📷 AOI 检测完成: {'PASS ✅' if ok else 'FAIL ❌'} "
                                 f"插入残余深度 {self._aoi_report['insert_depth_min_mm']}mm "
                                 f"接触力峰 {self._aoi_report['force_peak']} "
                                 f"(过程指标: 深度<8mm & 力峰<1.0 & 无回抓)")
                        self.sched._goto(self.sched.STAGES.index("回程"),
                                         "📷 AOI 检测完成 → 回程放件")
                elif _stg == "AOI检测":
                    self._aoi_hold = 0
                if _stg == "AOI转移":
                    # 到位 = 头到 hover 点 (focus 上方 AOI_HOVER), 容差 2cm — 判据目标
                    #   是悬停点不是对焦点 (advance 用 dist_aoi 永远等不到, 09-08 实锤)
                    _hover_pt = g["aoi_focus"] + np.array([0.0, 0.0, AOI_HOVER])
                    if float(np.linalg.norm(ph - _hover_pt)) < 0.02:
                        self.sched._goto(self.sched.STAGES.index("AOI检测"),
                                         f"已到 AOI 镜头上方 (头悬停位) → 对焦检测")
                if _stg == "回程":
                    # 回到初始位上方 (头 xy 到位且离台>2cm) → 放下
                    if (float(np.linalg.norm(ph[:2] - g["peg_head0"][:2])) < 0.02
                            and ph[2] > g["peg_head0"][2] + 0.02):
                        self.sched._goto(self.sched.STAGES.index("放下"), "回程到位 → 放下放件")
                if _stg == "放下":
                    # 放件: body 真值回初始位且下降停滞 (触台) → 开爪 → 爪开观测 → 判完成
                    _body_err = float(np.linalg.norm(o[4:7] - g["peg0_place"]))
                    if not self._drop_ready and _body_err < 0.012 and self._z_stall >= 6:
                        self._drop_ready = True
                        self.grasped = False          # 放件语义: 松爪 (peg 留台)
                        self._grasp_off0 = None
                        self.log(f"📦 放下到位 (body 偏差 {_body_err*1000:.0f}mm) → 开爪放件")
                    if self._drop_ready and not self._drop_released:
                        if float(1.0 - self.gripper) < 0.30:    # 观测夹爪已开 (夹紧度<0.3)
                            self._drop_released = True
                            self.log("🤖 夹爪已张开 — 光模块放回初始位完成")
            else:
                dist_aoi = 9.9
            self.obs_prev = obs[0:18]
            d_xy = self._d_xy_peg()
            dh = self._d_hole_h()
            depth = self._insert_depth()
            lifted = float(ph[2]) - g["peg_z0"]
            # grasp_force = 夹持质量: 夹住且 光模块 随动 → 1; 掉件/空夹 → 0 (调度器回退判据)
            #   (放下放件中 _drop_released 后恒 0 — 该段不在调度器回退范围, 正常)
            _gf = (0.0 if getattr(self, "_drop_ready", False) else
                   1.0 if (self.grasped and self._grasp_off0 is not None
                           and float(np.linalg.norm(o[4:7] - self.x - self._grasp_off0)) < 0.02)
                   else 0.0)
            self.sched.advance(contact_p=contact_p, dist_h=dh,
                               gripper=float(1.0 - self.gripper), depth=depth,
                               d_xy=d_xy, lifted=lifted,
                               at_grasp_pose=at_grasp_pose,
                               grasp_force=_gf,
                               peg_z=float(ph[2]), peg_z_grasp=g["peg_z0"],
                               hole_z=float(g["hole"][2]),  # 🐛 2026-09-06: 转移→插入 z 条件
                               dist_aoi=dist_aoi,
                               placed=bool(getattr(self, "_drop_released", False)
                                           and float(np.linalg.norm(
                                               o[4:7] - g["peg0_place"])) < 0.015))
            done = self.sched.stage() == "完成"
            # ⑧ 记录 (引擎 tr 兼容集)
            if os.environ.get("R0_TRACE") and step % 25 == 0:
                print(f"  [t={step*DT_ENV:.1f}s] st={self.sched.stage()} "
                      f"x={np.round(self.x,3)} tgt={np.round(target,3)} "
                      f"r={r_scalar:.3f} cp={contact_p:.2f} u={np.round(self._u_vec,3)} "
                      f"grp={self.gripper:.2f} grasped={self.grasped} gf={_gf}", flush=True)
            # 🆕 2026-09-04 静静: 周期进度日志 (GUI 真实化运行 5-9 分钟必须看得见在动 —
            #   每 25 步 log 一次: 步骤/阶段/YOLO 检出, 轮询增量 flush 到控制台;
            #   否则长时间静默 = 用户以为卡死 (老倪报两次"卡死,只能鼠标动"的背景))
            if step % 25 == 0:
                _v = self._vis
                _vs = (f"YOLO 检出率 {_v['n']}/{_v['shot']*2}"
                       f" ({(_v['n']/(_v['shot']*2)*100) if _v['shot'] else 0:.0f}%)"
                       if _v.get("shot") else "YOLO 未启动")
                self.log(f"[{step}/{int(max_steps)}] 阶段={self.sched.stage()} "
                         f"残差={r_scalar:.3f} 接触p={contact_p:.2f} "
                         f"grp={self.gripper:.2f} grasped={self.grasped} · {_vs}")
            tr["t"].append(round(step * DT_ENV, 3))
            tr["dist"].append(d_xy if not self.grasped else dh)
            tr["u_ff"].append(float(np.linalg.norm(u_ff[:3])))
            tr["residual"].append(r_scalar)
            tr["contact_p"].append(contact_p)
            tr["u_sat"].append(float(np.linalg.norm(self._u_vec[:3])))
            tr["stage"].append(stage if self.sched.stage() in stage else f"阶段 {self.sched.stage()}")
            tr["done"].append(done)
            tr["x"].append(self.x.copy())
            # 🐛 2026-09-07 静静 (老倪目检实锤): metaworld obs gripper 语义 1=张开 0=闭合,
            #   与引擎快演 gripper (0=张开 1=夹紧) 相反 → 3D 视图 (gap 公式按 1=夹紧) 显示
            #   真实化轨迹时反相: 初始真张开显示闭合, 夹紧真闭合显示张开。
            #   统一: tr 输出**夹紧度** 1−obs (0=张开 1=夹紧, 同引擎), 3D/Scope 语义一致。
            tr["gripper"].append(float(1.0 - self.gripper))
            tr["force"].append(force_norm)
            tr["peg"].append(o[4:7].copy())
            tr["peg_head"].append(ph.copy())
            tr["site_ph"].append(self.env.data.site_xpos[self._site_ph].copy())
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
            # 🧮 流形层逐帧发布 (2026-09-07 真实化补齐 — 老倪: 接触/性能流形在可视化层要有输出;
            #   输入 = 真实 hand/光模块头(site)/阶段目标/下发速度, 与引擎同构但用现场几何)
            try:
                if _MANI_MOD is not None:
                    if getattr(self, "_mani_cm", None) is None:
                        # 🧠 2026-09-08 JEPA predictor 注入 (旁路): WorldModelPredictor 几何 R7 实例 —
                        #   LatentPredictor(z+a→z') + ManifoldReadout(→流形坐标); 每帧真调用
                        #   (断点可进), 随机权重 → 预测列诚实标注 trained=False (待训练)。
                        _pred = None
                        if _PRED_MOD is not None:
                            try:
                                _pred = _PRED_MOD.WorldModelPredictor(
                                    z_dim=7, hidden_dim=512, num_layers=4)   # v2 架构 (23193帧)
                                # 🏆 2026-09-09 部署: 加载训练权重 (v4 优先 512/4层 — clean 45.7% /
                                #   抗干扰 57.4%; v2 同架构兜底), JEPA z+a→z'→流形 每帧真调
                                if os.path.exists(self._pred_w_path):
                                    import torch as _th3
                                    _pred.load_state_dict(
                                        _th3.load(self._pred_w_path, map_location="cpu"))
                                    self.log(f"🏆 L4 流形预测器已部署 ({os.path.basename(self._pred_w_path)} — "
                                             "JEPA LatentPredictor→ManifoldReadout, trained=True)")
                                else:
                                    self.log("🧠 JEPA 预测流形旁路已接: 权重未找到 "
                                             f"({self._pred_w_path}) → 随机权重对照")
                                self.log("🧠 JEPA 预测流形旁路已接: LatentPredictor→ManifoldReadout "
                                         "(每帧真调用; 预测列=trained 对照)")
                            except Exception as _pe:
                                _pred = None
                                self.log(f"⚠️ predictor 注入失败(旁路跳过): {_pe}")
                        self._mani_cm = _MANI_MOD.ContactManifold(
                            hole_pos=self.geom["goal"], hole_mouth=self.geom["hole"],
                            predictor=_pred)
                        self._mani_pm = _MANI_MOD.PerformanceManifold(
                            hole_pos=self.geom["goal"], predictor=_pred)
                    _ms2 = str(self.sched.stage()).replace("阶段 ", "").split("·")[0].strip()
                    _mc2 = self._mani_cm.decompose(self.x, ph, target,
                                                   getattr(self, "v", np.zeros(3)), _ms2)
                    _mp2 = self._mani_pm.evaluate(ph, stage=_ms2)
                    # 🧠 JEPA 预测流形 (旁路对照): 几何潜空间 z R⁷ + 当前动作 → 预测流形坐标
                    # 🐛 2026-09-09: 夹持后 x→光模块头 (x+grasp_off0+head_off) — rem(头到孔底)
                    #   才可辨识 (插入段夹爪 x 几乎不动, 原 z7 无头位置 → rem 预测上限受限)
                    _mpred = None
                    try:
                        import torch
                        _hx = self.x
                        if self.grasped and self._grasp_off0 is not None:
                            _hx = self.x + self._grasp_off0 + self.geom.get("head_off", np.zeros(3))
                        _z7 = np.concatenate([_hx - np.asarray(target, float),
                                              _hx - np.asarray(o[4:7], float),
                                              [1.0 if self.grasped else 0.0]])
                        tr["z7_vec"].append(_z7.copy())
                    except Exception:
                        tr["z7_vec"].append(np.zeros(7))
                    if self._mani_cm.predictor is not None:
                        try:
                            _a4 = np.asarray(self._u_vec, dtype=float).ravel()[:4]
                            if _a4.size < 4:
                                _a4 = np.zeros(4)
                            with torch.no_grad():
                                _mpred = self._mani_cm.predict_manifold(
                                    torch.from_numpy(_z7.astype(np.float32)).unsqueeze(0),
                                    torch.from_numpy(_a4.astype(np.float32)).unsqueeze(0))
                        except Exception:
                            _mpred = None
                    self._mani_out = {"cm": _mc2, "pm": _mp2,
                                      "pred": _mpred,
                                      "lat": np.asarray(latent_pred, dtype=float),
                                      "vel": (np.asarray(prior, dtype=float)
                                              - np.asarray(latent_pred, dtype=float))}
                    tr["mani_risk"].append(float(_mc2["risk"]))
                    tr["mani_progress"].append(float(_mc2["progress"]))
                    tr["mani_V"].append(float(_mc2["V"]))
                    tr["mani_eta"].append(float(_mp2["eta"]))
                    tr["mani_rem"].append(float(-_mp2["d_axial"]))
                    tr["mani_dperp"].append(float(_mp2["d_perp_norm"]))
                    if _mpred is not None:
                        tr["mani_pred"].append(_mpred["manifold"][0].float().cpu().numpy())
                    else:
                        tr["mani_pred"].append(np.zeros(6))
            except Exception:
                self._mani_out = None
                tr["mani_risk"].append(0.0); tr["mani_progress"].append(0.0)
                tr["mani_V"].append(0.0); tr["mani_eta"].append(0.0)
                tr["mani_rem"].append(0.0); tr["mani_dperp"].append(0.0)
                tr["mani_pred"].append(np.zeros(6))
            # 🔌 真实 io 快照 (画布节点名 key, 与引擎 _io_snapshot 同构 → 播放/3D/总线复用)
            tr["io_trace"].append((round(step * DT_ENV, 3), self._io_snapshot(
                o, obs, force_norm, u_ff, latent_pred, prior, z_k, corrected, residual,
                contact_p, u_fb, u, stage, u_sat, self._u_vec, step, at_grasp_pose)))
            if done:
                break
        tr["io"] = tr["io_trace"][-1][1] if tr["io_trace"] else {}
        # 🐛 2026-09-07 静静 (老倪"插入位置偏了"实锤): 3D 场景孔/盒必须用**本轮现场几何**
        #   (metaworld 布局每进程漂移: seed104 孔口 y=0.424 vs 3D 写死 0.462 偏 3.8cm)。
        #   set_trajectory 见 tr["_meta"] 自动 _apply_meta → 场景孔口/盒/peg0 与轨迹对齐。
        g = self.geom
        tr["_meta"] = {
            "goal": g["goal"].copy(), "hole_mouth": g["hole"].copy(),
            "peg0": g["peg_grasp"].copy(),
            # 🚀 2026-09-08 L3 扩展: AOI 工位/报告/模式 (3D 视图据此画检测设备)
            "aoi_focus": g["aoi_focus"].copy(),
            "mode": self.mode,
            "aoi_report": dict(self._aoi_report) if self._aoi_report else None,
            "seed": int(self.seed),
            "steps": len(tr["t"]),
            "stage_final": str(tr["stage"][-1]).replace("阶段 ", "") if tr["stage"] else "",
            "vision": bool(self.vision),
            "done": bool(tr["done"][-1]) if tr["done"] else False,
            "mm_hits": int(getattr(self, "_mm_hits", 0)),
        }
        # 📸 2026-09-08: VLM 关键帧随轨迹走 (node_ss_vlm 播放/双击取当前阶段真实帧编码)
        if getattr(self, "_key_frames", None):
            tr["key_frames"] = {k: np.asarray(v).copy() for k, v in self._key_frames.items()}
        # 🧠 2026-09-07 肌肉记忆: 本轮结束 — 成功轮提交段轨迹供固化/精进, 失败轮不固化
        if getattr(self, "_mm_on", False) and self.muscle is not None:
            try:
                _ok = bool(tr["done"][-1]) if tr["done"] else False
                _r = self.muscle.end_episode(_ok)
                if _r and _r.get("learned"):
                    self.log(f"🧠 肌肉记忆: {_r['msg']}")
                elif not _ok:
                    self.log("🧠 肌肉记忆: 本轮未完成 — 失败轮不固化 (继续练习)")
                # 固化状态汇总 (每轮结束展示一次)
                try:
                    _st = self.muscle.status()
                    if _st:
                        _parts = []
                        for _s, _sk in _st.items():
                            _parts.append(f"场景{_s}: {','.join(_sk)}")
                        self.log(f"🧠 肌肉记忆库: {'; '.join(_parts)}")
                except Exception:
                    pass
            except Exception:
                pass
        if g.get("box_center") is not None:
            tr["_meta"]["box_center"] = g["box_center"].copy()
        # 🧠 2026-09-09 分层记忆: 本轮结果入共享库 (L3 流程经验 + L4 预测质量 + meta)
        try:
            self._write_shared_memory(tr)
        except Exception:
            pass
        return tr

    def _write_shared_memory(self, tr):
        """🧠 分层记忆入库 (真源 src/lerobot/memory/memory_store.py → data/shared_memory.json):
        L3.flows 长程流程经验 (段路径/成败/步数) · L4.predict 筹划 (mani 预测残差) · meta"""
        import sys as _s, os as _o
        _rp = _o.path.dirname(_o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
        _rp_src = _o.path.join(_rp, "src")
        if _rp_src not in _s.path:
            _s.path.insert(0, _rp_src)
        try:
            from lerobot.memory import memory_store as _ms
        except Exception:
            return
        try:
            stg = []
            for s in (tr.get("stage") or []):
                s2 = str(s).replace("阶段 ", "")
                if not stg or s2 != stg[-1]:
                    stg.append(s2)
            n = len(tr.get("t", []))
            done = bool(tr["done"][-1]) if tr.get("done") else False
            # L4: mani 预测残差 (mani_pred vs 真值 6 维均值)
            mae = None
            if tr.get("mani_pred") and len(tr["mani_pred"]) == len(tr.get("mani_progress", [])) and n > 0:
                try:
                    import numpy as _np
                    pr = _np.asarray(tr["mani_pred"], float)
                    if pr.shape[1] == 6:
                        gt = _np.stack([_np.asarray(tr[f"mani_{k}"], float) for k in
                                        ("progress", "risk", "V", "eta", "rem", "dperp")], axis=1)
                        mae = [round(float(v), 4) for v in _np.abs(pr - gt).mean(0)]
                except Exception:
                    mae = None
            _ms.put("l3", "flows", {
                "seed": int(self.seed), "mode": self.mode,
                "cap": str(getattr(self, "_cap", "") or ""),
                "done": done, "steps": n, "stages": stg,
                "mani_mae": mae, "t": __import__("time").strftime("%m-%d %H:%M"),
            }, cap=40)
            if mae:
                _ms.put("l4", "predict", {
                    "seed": int(self.seed), "mode": self.mode, "done": done,
                    "steps": n, "mae": mae,
                    "t": __import__("time").strftime("%m-%d %H:%M"),
                }, cap=40)
            _ms.put("meta", "task", "光模块插拔 (insert/full)")
            _ms.put("meta", "cap", str(getattr(self, "_cap", "") or "L2"))
        except Exception:
            pass

    # ── 🔌 真实 io 快照 (画布节点名 key — YOLO/2D→3D 用真实检测, 非引擎几何) ──
    def _io_snapshot(self, o, obs, force_norm, u_ff, latent_pred, prior, z_k,
                     corrected, residual, contact_p, u_fb, u, stage, u_sat,
                     u_vec, frame_id, at_grasp_pose):
        """每帧真实模块 I/O — 与引擎 _io_snapshot 同构 (画布播放/3D/总线消费同一 key)
        🎯 YOLO/📐2D→3D = 本帧真实检测 (detect_3d 输出或最近刷新缓存), 不再写引擎几何
        🆕 2026-09-04 老倪红线: 未检出 = 诚实标 None, **禁止回退引擎真值 o[4:7] 冒充检测**
          (vision 模式下 YOLO 节点显示 = 视觉说了算: 检出→检测值, 未检出→None 明确标注)"""
        _conf = "🎥" if self.vision else "--"
        # 🧮 流形 channel (2026-09-07 真实化补齐 — 主循环算好存 self._mani_out)
        _mo = getattr(self, "_mani_out", None) or {}
        _mc = _mo.get("cm") or {}
        _mp = _mo.get("pm") or {}
        _lat = _mo.get("lat", np.zeros(4))
        _vel = _mo.get("vel", np.zeros(4))
        # 🧠 2026-09-09: JEPA 预测流形旁路 (引擎每帧真调 predict_manifold → _mani_out["pred"])
        _mpd = _mo.get("pred") or {}
        _mpr6 = _mpd.get("manifold")
        if _mpr6 is not None:
            try:
                _mpred6 = np.round(_mpr6[0].float().cpu().numpy(), 5)
            except Exception:
                _mpred6 = "(不可用)"
        else:
            _mpred6 = "(无 predictor)"
        # 检测真值: vision 且本帧有检出 → 检测值; 未检出 → None (诚实, 不顶替)
        _peg_d = self._vis["peg"] if (self.vision and self._vis["peg"] is not None) else None
        _hole_d = self._vis["hole"] if (self.vision and self._vis["hole"] is not None) else None
        _v3 = _peg_d if _peg_d is not None else ("未检出" if self.vision else o[4:7])
        _vh = _hole_d if _hole_d is not None else ("未检出" if self.vision else self.geom["hole"])
        _vhand = (self._vis.get("det3d", {}).get("hand")
                  if (self.vision and self._vis.get("det3d", {}).get("hand") is not None)
                  else self.x)                       # hand=编码器 (真机同构, 恒真值)
        _miss_mark = (" [未检出→None]" if self.vision and _peg_d is None else "")
        return {
            "📦 metaworld 数据源": {
                "in": [], "out": [("图像流 (真实渲染帧)", f"帧#{frame_id}"),
                                  ("状态流 39D (编码器+视觉)", obs[:39])]},
            "🎯 YOLO 目标检测": {
                "in": [("图像流", f"帧#{frame_id}")],
                "out": [("peg 3D (detect_3d)", _v3),
                        ("hole 3D (detect_3d)", _vh),
                        ("hand 3D (编码器, 不参与工件定位)", _vhand),
                        ("检测源", _conf + _miss_mark)]},
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
            # 🧮 流形层逐帧 channel (2026-09-07 真实化补齐 — 与引擎同构, 老倪: 可视化层要有输出)
            "🧮 接触流形": {
                "in": [("几何 (手/销/孔)", "真实 site+编码器")],
                "out": [("流形进度 e∥ (m)", _mc.get("progress", 0.0)),
                        ("法向偏离 e⊥ (m)", _mc.get("risk", 0.0)),
                        ("V=½‖e‖²", _mc.get("V", 0.0)),
                        ("状态", _mc.get("state", "—"))]},
            "🧮 性能流形": {
                "in": [("几何 (销/孔)", "真实 site")],
                "out": [("横向错位 δ⊥ (m)", _mp.get("d_perp_norm", 0.0)),
                        ("插深剩余 (m)", -_mp.get("d_axial", 0.0) if _mp else 0.0),
                        ("V_p=½δᵀWδ", _mp.get("Vp", 0.0)),
                        ("耦合效率 η", _mp.get("eta", 0.0))]},
            "🧮 潜空间": {
                "in": [("潜状态/先验", "估计器+动力学")],
                "out": [("潜坐标 (位置3+预测力)", _lat),
                        ("速度场 prior−x̂₋", _vel)]},
            # 🧠 流形专家预测器 channel (2026-09-09 补 — 老倪: 预测器节点要有输入输出;
            #   引擎每帧真调 predict_manifold 的旁路结果发布到数据总线, 画布播放同源展示)
            "🧠 流形专家预测器": {
                "in": [("潜空间 z (几何 R7)", "相对目标/销 + 夹持位"),
                       ("动作 a R4", "执行下发 u_vec")],
                "out": [("预测流形 6D (JEPA)", _mpred6),
                        ("权重", "随机 (trained=False)")]},
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
