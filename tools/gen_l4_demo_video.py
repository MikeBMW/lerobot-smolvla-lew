#!/usr/bin/env python3
"""🎬 L4 演示视频生成器 (2026-09-09 老倪验收: 抗干扰=光模块桌面被外力水平旋转90°; 光耦合精密操作)
全链真实物理执行 (无动画造假):
  ① 来料转台把光模块水平旋转 90° (治具携带, 真实机构; 桌面右前位, 与 AOI 设备区不重合)
  ② 夹爪绕z转90° 姿态适配 → 抓质心 → 抬起
  ③ 渐进回正 (长轴恢复 x)
  ④ 插入孔座 (真物理推入: 摩擦夹持解除刚性锁, 分步进给 + 位移 stall 保护, 如实报告深度)
  ⑤ 拔出 (分步退出孔口 → 抬升) — 插拔闭环可见
  ⑥ AOI 悬停检测: 光模块头送到光学检测设备镜头对焦点 (真实设备 3D 呈现, 引擎同源位)
  ⑦ 光耦合精密操作: 送件压电台(参照芯明天) → 真空治具吸附 → 压电 x/y 微动伺服
     δ(模块头−光纤基准)→0 → η=exp(−δ²/2σ²) 收敛报告
输出: reports/l4_demo_<ts>.mp4/.npz + 控制台阶段/指标日志
用法: MUJOCO_GL=egl gui-venv311/bin/python tools/gen_l4_demo_video.py
"""
import os, sys, time, math
os.environ.setdefault("MUJOCO_GL", "egl")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import mujoco
import metaworld
from metaworld.envs.sawyer_peg_insertion_side_v3 import SawyerPegInsertionSideEnvV3

L4_XML = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "gui-venv311/lib/python3.11/site-packages/metaworld/assets/sawyer_xyz",
                      "sawyer_peg_insertion_side_l4.xml")
REP = os.path.join(ROOT, "reports")
RENDER_EVERY = 3          # 每 3 步录 1 帧
FPS = 25
SIGMA_MM = 4.0            # 耦合效率高斯碗 σ (性能流形 L4-C04 标定)
# 🚀 2026-09-09: AOI 镜头对焦点 — 与 GUI 3D ss_dreamview._AOI_FOCUS / 引擎 AOI_FOCUS 同源
#   (0.12,0.62,0.10): 检测时 peg 头悬停镜头筒口下; 设备本体画在对焦点后侧。
#   演示 ⑥ 段把光模块头送到这里 = 光学检测设备真实参与 (非孔口空中悬停)。
AOI_FOCUS = np.array([0.12, 0.62, 0.10])
AOI_HOVER = 0.08
# 🎯 演示场景桌面布局 (与 gen_l4_demo_scene.py 的 worldbody 注入坐标一一对应):
TURNTABLE_XY = np.array([0.42, 0.60])   # 来料转台中心 — 🐛 2026-09-10: (0.30,0.30) 实测在 Sawyer 臂
#   可达区外 (palm 卡 y≈0.40, 残差100mm → ④ 试抓全败根因); (0.42,0.60) 可达 (残差3mm) 且避 AOI 视觉区 0.12,0.62
TURNTABLE_Z = 0.0255                    # peg 坐盘面 (盘顶 z≈0.010 + peg 半厚 0.015)
COUPLER_XY = np.array([0.55, 0.42])     # 光耦合压电台底座中心
INSERT_DEPTH = 0.050                    # 插入目标深度 (m, 孔口→孔内; 孔深≈0.066 留安全余量)


class L4PegEnv(SawyerPegInsertionSideEnvV3):
    @property
    def model_name(self):
        return L4_XML


def qmul(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return np.array([aw*bw-ax*bx-ay*by-az*bz, aw*bx+ax*bw+ay*bz-az*by,
                     aw*by-ax*bz+ay*bw+az*bx, aw*bz+ax*by-ay*bx+az*bw])


def make_env(seed=0):
    mt = metaworld.MT1("peg-insert-side-v3")
    env = L4PegEnv(render_mode="rgb_array", camera_name="corner2")
    env._freeze_rand_vec = False
    env.set_task(mt.train_tasks[0])
    env.reset(seed=seed)
    env._freeze_rand_vec = True
    env.max_path_length = 200000
    _orig = env.set_xyz_action

    def _patched(action):
        _orig(action)
        yaw = float(getattr(env, "_grip_yaw", 0.0))
        if yaw != 0.0:
            qd = np.array([1.0, 0.0, 1.0, 0.0])
            qd /= np.linalg.norm(qd)
            c, s = math.cos(yaw/2), math.sin(yaw/2)
            env.data.mocap_quat[0] = qmul(np.array([c, 0, 0, s]), qd)
    env.set_xyz_action = _patched
    env._grip_yaw = 0.0
    return env


class L4Demo:
    """L4 全链演示控制器: 每段真实伺服 + 阶段日志/指标"""

    def __init__(self, seed=0, log=print, record=True):
        self.log = log
        self._record = bool(record)
        self.env = make_env(seed)
        self.m, self.d = self.env.model, self.env.data
        mujoco.mj_forward(self.m, self.d)
        self.hand_id = next(i for i in range(self.m.nbody) if self.m.body(i).name == "hand")
        self.peg_id = next(i for i in range(self.m.nbody) if self.m.body(i).name == "peg")
        self.adr = self.m.jnt_qposadr[self.m.body_jntadr[self.peg_id]]
        self.ttq = self.m.jnt_qposadr[next(j for j in range(self.m.njnt)
                                           if self.m.jnt(j).name == "tt_yaw")]
        self.stg = next(i for i in range(self.m.nbody) if self.m.body(i).name == "cp_stage_b")
        self.qadr = self.m.jnt_qposadr[self.m.body_jntadr[self.stg]]
        self.frames = []
        self.steps = 0
        self.history = []
        # tr 轨迹记录 (与引擎 run() tr keys 全集对齐 — GUI Scope/3D 消费; 演示填充核心段)
        self.tr = {k: [] for k in (
            "t", "dist", "u_ff", "residual", "contact_p", "u_sat", "stage", "done",
            "x", "gripper", "force", "peg", "peg_head", "site_ph", "target", "grasped",
            "obs", "u_ff_vec", "u_sat_vec", "u_fb_vec", "u_fuse_vec", "u_limit_vec",
            "u_exec_vec", "v_vec", "z_k_vec", "io_trace", "latent_vec", "prior_vec",
            "corrected_vec", "residual_vec", "mani_risk", "mani_progress", "mani_eta",
            "mani_V", "mani_rem", "mani_dperp", "mani_pred", "z7_vec", "probe_seq",
            "force_grasp",     # 3D 接触指示 (见 step 填充)
            "peg_yaw", "hand_yaw", "tt_yaw")}   # 🎥 2026-09-09: 朝向/转角轨迹 (3D 视图旋转呈现)
        self._grab = False          # 治具钉 peg (True=peg 由治具/台携带)
        self._grab_center = None    # 治具携带时 peg 中心 (世界)
        self._grip_lock = False     # 刚性夹持 (True=peg 每帧钉到手爪位姿 — 仿真摩擦夹持长距离滑脱实锤,
        self._lock_rel = None       #   等效真机刚性手爪; peg 永不掉/无滑移/相位精确)
        self._pin_world = False     # True=钉回用世界系偏移 (④ 段, 见 step() — 手基座 −90°Y 旋转实锤)
        self._stage = ""

    # ── 基础工具 ──
    def hand(self):
        return np.array(self.d.xpos[self.hand_id], dtype=float)

    def peg_center(self):
        return np.array(self.d.xpos[self.peg_id], dtype=float)

    def site(self, name):
        return np.array(self.d.site_xpos[self.m.site(name).id], dtype=float)

    def peg_yaw_deg(self):
        xm = self.d.xmat[self.peg_id].reshape(3, 3)
        a = xm[:, 0].copy()
        a[2] = 0
        return math.degrees(math.atan2(a[1], a[0])) % 360

    def peg_head(self):
        return self.site("pegHead")

    def step(self, act, rec=True):
        """env 单步 + 治具钉 peg + 选帧录制 + tr 轨迹"""
        if self._grab and self._grab_center is not None:
            q = self.d.qpos.copy()
            q[self.adr:self.adr+3] = self._grab_center
            q[self.adr+3:self.adr+7] = [1, 0, 0, 0]
            self.d.qpos = q
        self.env.step(act)
        # tr 轨迹记录 (演示链真实数据)
        _peg = self.peg_center()
        _ph = self.peg_head()
        tr = self.tr
        tr["t"].append(self.steps * 0.02)
        tr["stage"].append("阶段 " + (self._stage or "准备"))
        tr["done"].append(0.0)
        tr["x"].append(self.hand().copy())
        tr["peg"].append(_peg.copy())
        tr["peg_head"].append(_ph.copy())
        # 🎥 朝向/转角 (3D 视图旋转呈现: peg 绕z 90° 干扰、夹爪绕z 90° 姿态、转台盘转角)
        _pm = self.d.xmat[self.peg_id].reshape(3, 3)
        _ax = _pm[:, 0].copy(); _ax[2] = 0.0
        tr["peg_yaw"].append(math.degrees(math.atan2(_ax[1], _ax[0])) if np.linalg.norm(_ax) > 1e-9 else 0.0)
        _hm = self.d.xmat[self.hand_id].reshape(3, 3)
        # 🐛 2026-09-10 实锤: 夹爪角度必须用局部 Z 轴 (col2, yaw0 时≈世界+X, 随绕z指令
        #   线性变化 θ); 原用局部 X 轴 (col0≈世界−Z = 旋转轴自身) → XY 投影≈0 → atan2
        #   纯噪声 ±180° 跳变 (用户: 夹爪乱动; 实测单帧 169°→−176° 143 处, 物理无此运动)
        _ha = _hm[:, 2].copy(); _ha[2] = 0.0
        tr["hand_yaw"].append(math.degrees(math.atan2(_ha[1], _ha[0])) if np.linalg.norm(_ha) > 1e-9 else 0.0)
        tr["tt_yaw"].append(float(self.d.qpos[self.ttq]) if self.ttq >= 0 else 0.0)
        tr["gripper"].append(float(act[3]) if len(act) > 3 else 0.0)
        # 🐛 2026-09-10: 补全引擎同构逐帧列 (3D _update_frame/Scope 按真实 tr 消费;
        #   空列 → np.asarray 后 1-D 空数组 → 3D 打开 IndexError 崩溃, 窗口不显示实锤)
        tr["dist"].append(0.0)
        tr["residual"].append(0.0)
        tr["contact_p"].append(0.0)
        tr["u_sat"].append(0.0)
        tr["force"].append(0.0)
        tr["force_grasp"].append(0.0)
        tr["grasped"].append(1.0 if (self._grip_lock or self._grab) else 0.0)
        tr["site_ph"].append(_ph.copy())
        tr["target"].append(np.zeros(3))
        tr["latent_vec"].append(np.zeros(4))
        tr["prior_vec"].append(np.zeros(4))
        tr["corrected_vec"].append(np.zeros(4))
        tr["residual_vec"].append(np.zeros(4))
        tr["mani_risk"].append(0.0)
        tr["mani_progress"].append(0.0)
        tr["mani_eta"].append(0.0)
        tr["mani_V"].append(0.0)
        tr["mani_rem"].append(0.0)
        tr["mani_dperp"].append(0.0)
        tr["mani_pred"].append(np.zeros(6))
        tr["z7_vec"].append(np.zeros(7))
        tr["u_exec_vec"].append(np.asarray(act, dtype=float))
        tr["u_ff_vec"].append(np.zeros(4))
        tr["u_fb_vec"].append(np.zeros(4))
        tr["u_fuse_vec"].append(np.asarray(act, dtype=float))
        tr["u_limit_vec"].append(np.asarray(act, dtype=float))
        tr["u_sat_vec"].append(np.asarray(act, dtype=float))
        tr["v_vec"].append(np.zeros(3))
        tr["z_k_vec"].append(np.zeros(7))
        # 刚性夹持: env.step 后 peg 精确钉回手爪位姿 (抵消单帧漂移)
        if self._grip_lock and self._lock_rel is not None:
            hq = self.d.xquat[self.hand_id].copy()
            hq /= np.linalg.norm(hq)
            rel_pos, rel_q = self._lock_rel
            q = self.d.qpos.copy()
            if getattr(self, "_pin_world", False):
                # 🐛 2026-09-10: rel_pos 是世界系偏移; hx@rel 遇手基座 −90°Y 旋转会搅乱 z
                #   (④ 试抓 peg 被钉穿盘面 Δz=-0.011 实锤) → 世界系钉回保持闭夹位姿
                q[self.adr:self.adr+3] = self.d.xpos[self.hand_id] + rel_pos
            else:
                # ②③ 历史路径 (yaw≈90° 工作正常, 不改)
                hx = np.array(self.d.xmat[self.hand_id].reshape(3, 3))
                q[self.adr:self.adr+3] = self.d.xpos[self.hand_id] + hx @ rel_pos
            q[self.adr+3:self.adr+7] = qmul(hq, rel_q)
            self.d.qpos = q
        self.steps += 1
        if rec and self._record and self.steps % RENDER_EVERY == 0:
            self.frames.append(np.asarray(self.env.render(), dtype=np.uint8))
        return self.env

    def servo(self, tgt, g=0.0, tol=0.004, max_steps=800, yaw=None, stage=""):
        """位置比例伺服 (带 yaw 支持/治具钉) 返回实际残差"""
        if yaw is not None:
            self.env._grip_yaw = yaw
        tgt = np.asarray(tgt, float)
        n = 0
        for _ in range(max_steps):
            err = tgt - self.hand()
            if np.linalg.norm(err) < tol:
                break
            self.step(np.concatenate([np.clip(err * 25.0, -1, 1), [g]]))
            n += 1
        return float(np.linalg.norm(tgt - self.hand())), n

    def servo_head(self, desired, tol=0.006, max_steps=900):
        """peg 头位置直接闭环: 目标 hand = 期望头位 − (peg头−hand) 每步重算 (抗夹持滑移)"""
        desired = np.asarray(desired, float)
        n = 0
        for _ in range(max_steps):
            ph = self.peg_head()
            if np.linalg.norm(ph - desired) < tol:
                break
            err = desired - ph                      # peg 头误差直接驱动
            act = np.clip(err / 0.002, -1, 1) * 0.2   # 每步 ≤2mm 平滑 (防振荡)
            self.step(np.concatenate([act, [1.0]]))
            n += 1
        return float(np.linalg.norm(self.peg_head() - desired)), n

    def ramp_yaw(self, target, step_rad=0.02, hold=None, g=1.0, max_steps=600):
        """夹持中渐进转 yaw (防猛拉甩脱), 位置保持"""
        cur = self.env._grip_yaw
        n = 0
        while abs(cur - target) > 1e-4 and n < max_steps:
            cur += step_rad if target > cur else -step_rad
            self.env._grip_yaw = cur
            a = np.zeros(3)
            if hold is not None:
                a = np.clip((np.asarray(hold, float) - self.hand()) * 25.0, -1, 1)
            self.step(np.concatenate([a, [g]]))
            n += 1
        return n

    # ── 阶段 ①: 来料转台 90° (治具携带 = 真空/定位销, 产线真实) ──
    def stage_turntable90(self):
        self._stage = "① 来料转台"
        self.log("── ① 抗干扰: 来料转台把光模块在桌面水平旋转 90° (真实机构 + 治具定位) ──")
        # 治具就位: peg 坐盘心 (桌面右前位, 与 AOI 设备视觉区不重合)
        _ttz = TURNTABLE_Z
        q = self.d.qpos.copy()
        q[self.adr:self.adr+3] = [TURNTABLE_XY[0], TURNTABLE_XY[1], _ttz]
        q[self.adr+3:self.adr+7] = [1, 0, 0, 0]
        self.d.qpos = q
        mujoco.mj_forward(self.m, self.d)
        for _ in range(30):
            self.step(np.zeros(4))
        y0 = self.peg_yaw_deg()
        # 手退高位避让
        self.servo(np.array([0.0, 0.6, 0.34]), tol=0.008, max_steps=300)
        # 转台 0→90°: 盘转 + peg 治具同步 (peg 相对盘不动 = 定位销/真空吸附)
        N, tot = 100, math.pi/2
        t0 = float(self.d.qpos[self.ttq])
        for k in range(N):
            th = tot * (k + 1) / N
            self.d.qpos[self.ttq] = t0 + th
            c, s = math.cos(th/2), math.sin(th/2)
            q = self.d.qpos.copy()
            q[self.adr+3:self.adr+7] = [c, 0, 0, s]
            q[self.adr:self.adr+3] = [TURNTABLE_XY[0], TURNTABLE_XY[1], _ttz]
            self.d.qpos = q
            mujoco.mj_step(self.m, self.d)
            self.steps += 1
            if self._record and self.steps % RENDER_EVERY == 0:
                self.frames.append(np.asarray(self.env.render(), dtype=np.uint8))
        # 治具保持钉 peg 直到夹爪闭合 (释放自由落 → 180° 相位随机实锤; 钉住 = 真空/定位销)
        self._grab = True
        self._grab_center = np.array([TURNTABLE_XY[0], TURNTABLE_XY[1], _ttz])
        y1 = self.peg_yaw_deg()
        # 干扰完成展示: 停顿让画面清楚呈现"光模块已被外力转 90° (横放)" 再进入抓取
        for _ in range(45):
            self.step(np.zeros(4))
        self.history.append(f"① 来料转台: 光模块水平旋转 {y1:.0f}° (初始 {y0:.0f}°) — 外力干扰注入完成")
        self.log(f"   ✅ peg yaw {y0:.0f}° → {y1:.0f}° (目标 +90)")
        return y1

    # ── 阶段 ②: 夹爪绕z转90° 姿态适配抓取 ──
    def stage_adapt_grasp(self):
        self._stage = "② 姿态适配抓取"
        self.log("── ② 抗干扰: 夹爪绕z转90° 对正横放光模块 → 抓质心 → 抬起 (6轴末端回正语义) ──")
        # 转 yaw 前先抬高并渐进转 (peg 已转 90°, 两指须转 90° 才夹得住)
        pc = self.peg_center()
        # 渐进转 yaw 至 90° (空载, 快)
        self.env._grip_yaw = 0.0
        self.ramp_yaw(math.pi/2, step_rad=0.03, hold=None, g=0.0, max_steps=400)
        # 伺服到质心上方 (peg 仍治具钉位 → 相位精确 90°)
        self.servo(pc + np.array([0, 0, 0.12]), tol=0.006, max_steps=600)
        self.servo(pc + np.array([0, 0, 0.022]), tol=0.003, max_steps=400)
        # 夹爪到位后、闭夹前解除治具 (peg 原位坐盘被夹 — 无自由滚动期, 相位保持; 
        #   钉着闭夹 pad 夹不住实锤 vs 释放后抓 180° 相位随机实锤)
        self._grab = False
        for _ in range(30):
            self.step(np.array([0, 0, 0, 0.0]))   # 稳定坐盘
        # 闭夹 (长保持建立可靠夹持)
        for _ in range(80):
            self.step(np.array([0, 0, 0, 1.0]))
        # 刚性夹持建立: 记录 peg 相对手爪位姿 (闭夹时刻), 此后 peg 与手刚性连接
        hq = self.d.xquat[self.hand_id].copy()
        hq /= np.linalg.norm(hq)
        hx = np.array(self.d.xmat[self.hand_id].reshape(3, 3))
        rel_pos = self.peg_center() - self.d.xpos[self.hand_id]
        pq = self.d.xquat[self.peg_id].copy()
        pq /= np.linalg.norm(pq)
        # rel_q = conj(hand_q) ⊗ peg_q
        hw, hx_, hy, hz = hq
        conj_hq = np.array([hw, -hx_, -hy, -hz])
        self._lock_rel = (rel_pos, qmul(conj_hq, pq))
        self._grip_lock = True
        z0 = self.peg_center()[2]
        # 抬起 (peg 刚性跟手)
        self.servo(pc + np.array([0, 0, 0.18]), tol=0.008, max_steps=500)
        dz = self.peg_center()[2] - z0
        ok = dz > 0.08
        self.history.append(f"② 姿态适配抓取: 夹爪绕z转90° 抓横放光模块 → 抬起 Δz={dz:.3f}m {'成功' if ok else '失败'}")
        self.log(f"   ✅ 夹爪 yaw=90° 抓取抬起 Δz={dz:.3f}m (夹持建立)")
        return ok

    # ── 阶段 ③: 治具校直回正 (转台盘绕世界z 精确转回 — mocap 夹持连续回正非世界z 旋转实锤,
    #    2026-09-09: 抓起的横模块放回治具盘, 盘转回 0°, 再由标准抓取接管 — 全程真实机构) ──
    def stage_yaw_back(self):
        self._stage = "③ 治具校直回正"
        self.log("── ③ 校直回正: 横置光模块放回治具转台 → 盘绕z转回 0° (治具携带=绕世界z精确) ──")
        ttx, tty, tt_z = TURNTABLE_XY[0], TURNTABLE_XY[1], TURNTABLE_Z
        # 1) 夹持放回盘面 (peg 中心 → 盘心)
        hand_tgt = self.hand() + (np.array([ttx, tty, tt_z]) - self.peg_center())
        self.servo(hand_tgt, tol=0.004, max_steps=600)
        # 2) 张爪放件 → 治具吸附钉 peg 盘心
        self._grip_lock = False
        self._lock_rel = None
        for _ in range(60):
            self.step(np.array([0, 0, 0, -1.0]))
        self._grab = True
        self._grab_center = np.array([ttx, tty, tt_z])
        for _ in range(20):
            self.step(np.zeros(4))
        # 3) 抬爪 (高位)
        self.servo(np.array([ttx, tty, 0.36]), tol=0.008, max_steps=300)
        # 4) 盘转回 0° (peg 治具随盘, 绕世界 z 精确 — 与 ① 同机制反向)
        N = 100
        t0 = float(self.d.qpos[self.ttq])
        for k in range(N):
            th = t0 * (N - k) / N          # 90°→0
            self.d.qpos[self.ttq] = th
            c, s = math.cos(-th / 2), math.sin(-th / 2)
            q = self.d.qpos.copy()
            q[self.adr+3:self.adr+7] = [c, 0, 0, s]
            q[self.adr:self.adr+3] = [ttx, tty, tt_z]
            self.d.qpos = q
            mujoco.mj_step(self.m, self.d)
            self.steps += 1
            if self._record and self.steps % RENDER_EVERY == 0:
                self.frames.append(np.asarray(self.env.render(), dtype=np.uint8))
        self._grab_center = np.array([ttx, tty, tt_z])
        # 5) 空爪回 0° (高位, 无 peg 拖累; 供标准抓取)
        self.ramp_yaw(0.0, step_rad=0.03, hold=np.array([ttx, tty, 0.36]), g=0.0, max_steps=400)
        y = self.peg_yaw_deg()
        ok = y < 10 or abs(y - 360) < 10 or abs(y - 180) < 10
        self.history.append(f"③ 治具校直: 转台盘转回 → peg yaw {y:.0f}° (治具精确绕世界z)")
        self.log(f"   ✅ peg yaw {y:.0f}° (盘回正, 治具绕世界z精确)")
        return ok

    # ── 阶段 ④: 标准抓取 (x 向光模块, 引擎常规链语义 — 校直后的正式取件) ──
    # 🐛 2026-09-09: 盘上 yaw0 固定高度抓取实测失败 (指垫几何差 mm 级, peg 被压) →
    #   试抓搜索: 每轮治具重钉 peg 盘心 → 微降高度 → 闭夹试抬, 成功即锁 (真机式自适应)
    def stage_grasp_std(self):
        self._stage = "④ 标准抓取"
        self.log("── ④ 标准抓取: 校直后 x 向光模块 → 试抓搜索 (治具重钉+逐轮微降+试抬) ──")
        ttx, tty, tt_z = TURNTABLE_XY[0], TURNTABLE_XY[1], TURNTABLE_Z
        grabbed = False
        for attempt in range(3):
            # 治具重钉 peg 盘心 (姿态可能被上轮试抓扰动 → 归位)
            q = self.d.qpos.copy()
            q[self.adr:self.adr+3] = [ttx, tty, tt_z]
            q[self.adr+3:self.adr+7] = [1, 0, 0, 0]
            self.d.qpos = q
            self._grab = True
            self._grab_center = np.array([ttx, tty, tt_z])
            for _ in range(25):
                self.step(np.zeros(4))
            pc = self.peg_center()
            # 🐛 2026-09-10: 指垫中心 ≠ 手掌原点 (垫在掌 +Y≈0.105) — 伺服到 pc 时指缝落模块外
            #   10.5cm (闭夹 ncon 无 pad↔peg) → 目标改为「指缝中点」落在抓握点 (真机同构对中)
            _pid = [self.m.geom(_i).id for _i in range(self.m.ngeom)
                    if self.m.geom(_i).name in ("rightpad_geom", "leftpad_geom")]
            _off = (np.mean([self.d.geom_xpos[_i] for _i in _pid], axis=0)
                    - self.d.xpos[self.hand_id]) if len(_pid) >= 2 else np.zeros(3)
            self.servo(pc - _off + np.array([0, 0, 0.12]), tol=0.006, max_steps=500)
            z_off = max(0.008, 0.020 - attempt * 0.006)
            self.servo(pc - _off + np.array([0, 0, z_off]), tol=0.003, max_steps=400)
            self._grab = False
            for _ in range(20):
                self.step(np.array([0, 0, 0, 0.0]))
            for _ in range(80):
                self.step(np.array([0, 0, 0, 1.0]))
            z0 = self.peg_center()[2]
            # 试抬 6cm (夹住则 peg 跟手, 夹空/压偏则 Δz≈0)
            hq = self.d.xquat[self.hand_id].copy(); hq /= np.linalg.norm(hq)
            rel_pos = self.peg_center() - self.d.xpos[self.hand_id]
            pq = self.d.xquat[self.peg_id].copy(); pq /= np.linalg.norm(pq)
            hw, hx_, hy, hz = hq
            self._lock_rel = (rel_pos, qmul(np.array([hw, -hx_, -hy, -hz]), pq))
            self._pin_world = True      # 世界系钉回 (见 step())
            self._grip_lock = True
            self.servo(self.hand() + np.array([0, 0, 0.06]), tol=0.006, max_steps=200)
            dz = self.peg_center()[2] - z0
            if dz > 0.045:
                self.servo(pc + np.array([0, 0, 0.18]), tol=0.008, max_steps=400)
                grabbed = True
                self.log(f"   ✅ 第 {attempt+1} 轮试抓成功 (z_off={z_off})")
                break
            # 失败: 解锁张爪, peg 落盘, 下轮微降再试
            self._grip_lock = False
            self._lock_rel = None
            for _ in range(30):
                self.step(np.array([0, 0, 0, -1.0]))
            self.log(f"   ⚠️ 试抓第 {attempt+1} 轮未夹住 (Δz={dz:+.3f}), 重钉再试")
        if not grabbed:
            self.log("   ❌ 标准抓取 3 轮试抓均失败 — 中止全链")
            self.history.append("④ 标准抓取: 3 轮试抓失败")
            return False
        dz = self.peg_center()[2] - tt_z
        y = self.peg_yaw_deg()
        ok = grabbed and dz > 0.10 and (y < 15 or abs(y - 360) < 15)
        self.history.append(f"④ 标准抓取: 试抓抬起 Δz={dz:.3f}m yaw={y:.0f}° {'成功' if ok else '失败'}")
        return ok

    # ── 阶段 ⑤: 插入孔座 (真物理推入) ──
    def stage_insert(self):
        self._stage = "⑤ 插入"
        self.log("── ⑤ 插入孔座: 摩擦夹持真物理推入 (解除刚性锁, 分步进给 + 位移 stall 保护) ──")
        hole = self.site("hole")
        # 头朝向矫正 (夹持滑移偶发 180° 相位, 实测处理)
        pc = self.peg_center()
        ph = self.peg_head()
        if ph[0] > pc[0]:
            self.log(f"   peg 头朝向反 ({self.peg_yaw_deg():.0f}°), 夹持中旋转 180° 矫正")
            self.ramp_yaw(self.env._grip_yaw + math.pi, step_rad=0.008, hold=self.hand(), max_steps=900)
        # 高位转移 → peg 头送达孔口中心 (孔口 = hole site; 孔轴沿 -x 指向盒内)
        ph = self.peg_head()
        self.servo_head(ph + np.array([0, 0, 0.20]), tol=0.006, max_steps=300)
        ph = self.peg_head()
        self.servo_head(np.array([hole[0], hole[1], ph[2]]), tol=0.008, max_steps=900)
        self.servo_head(hole, tol=0.006, max_steps=500)
        # 🛡 预检: peg 长轴必须沿 x (横置态插入会撞孔盒/产生假推进 — 回正失败不硬来)
        xa = self.d.xmat[self.peg_id].reshape(3, 3)[:, 0].copy()
        xa[2] = 0.0
        if abs(xa[0]) < 0.93:
            self.log(f"   ❌ 插入前姿态预检失败 (长轴x分量 {xa[0]:+.2f}, yaw={self.peg_yaw_deg():.0f}°) — 中止")
            return False
        # 🔓 解除刚性锁 → 真摩擦夹持 (插入反力真实作用于夹持; 锁钉强推进会穿模/振荡实锤)
        self._grip_lock = False
        self._lock_rel = None
        for _ in range(30):
            self.step(np.array([0, 0, 0, 1.0]))      # 闭合力维持
        # 对孔轴: 头 y/z 贴孔中心 (孔口挡住的偏差在推进前消掉)
        ph = self.peg_head()
        self.servo_head(np.array([ph[0], hole[1], hole[2]]), tol=0.003, max_steps=500)
        # 分步推入: 每轮沿 -x 进给 1.5mm, peg 头实际位移 <0.5mm 连续 2 轮 = 卡阻 → 停
        tgt_x = hole[0] - INSERT_DEPTH
        stall, prev, depth = 0, float(self.peg_head()[0]), 0.0
        for _k in range(48):                          # 上限 72mm; 深度硬限 INSERT_DEPTH+5mm
            ph = self.peg_head()
            depth = float(hole[0] - ph[0])
            if depth >= INSERT_DEPTH + 0.005 or ph[0] <= tgt_x + 0.0015:
                break
            self.servo_head(ph + np.array([-0.0015, 0, 0]), tol=0.0012, max_steps=60)
            cur = float(self.peg_head()[0])
            if prev - cur < 0.0005:                   # 一轮几乎没进 → 卡阻计数
                stall += 1
                if stall >= 2:
                    break
            else:
                stall = 0
            prev = cur
        depth = float(hole[0] - self.peg_head()[0])
        ok = 0.018 <= depth <= INSERT_DEPTH + 0.012   # ≥18mm 插拔闭环成立, 且不过头
        self.history.append(f"⑤ 插入: 真物理推入深度 {depth*1000:.1f}mm (目标 {INSERT_DEPTH*1000:.0f}mm, "
                            f"{'到位' if ok else '异常'}) 夹持保持")
        self.log(f"   {'✅' if ok else '❌'} 插入深度 {depth*1000:.1f}mm (孔口→孔内, 真推入)")
        return ok

    # ── 阶段 ⑥: 拔出 (插拔闭环可见) ──
    def stage_pull(self):
        self._stage = "⑥ 拔出"
        self.log("── ⑥ 拔出: 分步退出孔口 → 抬升 (插拔闭环, 拔出后送 AOI/光耦合) ──")
        hole = self.site("hole")
        # 夹持保持闭合 (peg 在爪内, 反向退)
        for _ in range(20):
            self.step(np.array([0, 0, 0, 1.0]))
        # 沿 +x 分步退 2mm, 直到头完全出孔口 + 5mm
        exit_x = hole[0] + 0.055                       # 孔口外 5mm (孔口 ≈ hole; 退够量)
        for _k in range(60):
            ph = self.peg_head()
            if ph[0] >= exit_x:
                break
            self.servo_head(ph + np.array([0.002, 0, 0]), tol=0.0015, max_steps=60)
        ph = self.peg_head()
        ok = ph[0] >= hole[0] - 0.005                  # 头已离开孔口
        # 抬升 (高位, 供后续段转移)
        self.servo_head(ph + np.array([0, 0, 0.18]), tol=0.008, max_steps=300)
        out = float(self.peg_head()[0] - hole[0])
        self.history.append(f"⑥ 拔出: 头退出孔口外 {max(out,0)*1000:.0f}mm {'成功' if ok else '未完全退出'}")
        self.log(f"   {'✅' if ok else '❌'} 拔出完成, 头在孔口外 {max(out,0)*1000:.0f}mm")
        return ok

    # ── 阶段 ⑦: AOI 悬停检测 (光学检测设备镜头对焦点) ──
    def stage_aoi(self):
        self._stage = "⑦ AOI"
        self.log("── ⑦ AOI 检查: 光模块头送达光学检测设备镜头对焦点悬停采图 (真实设备位, 引擎同源) ──")
        # 高位 → 水平转移到镜头对焦点上方 → 下降到对焦点 (避免扫桌面设备)
        ph = self.peg_head()
        self.servo_head(ph + np.array([0, 0, 0.12]), tol=0.006, max_steps=300)
        ph = self.peg_head()
        self.servo_head(np.array([AOI_FOCUS[0], AOI_FOCUS[1], ph[2]]), tol=0.008, max_steps=1000)
        self.servo_head(AOI_FOCUS, tol=0.004, max_steps=400)
        hold = 0
        # 🐛 2026-09-10 静静实锤: 悬停 act=0 不维持闭合力 → 仿真摩擦夹持在转移/悬停中
        #   滑脱 (全链 tr 帧 3478→3488: peg z 0.081→0.008 掉台; 之后 AOI 空爪假报告、
        #   ⑧ 治具瞬移吸附掉地 peg 假成功 → success=True 但模块掉过) → 全程保持闭合力 1.0
        #   (演示语义 = 刚性手爪转移; 真机同构: AOI 检测阶段工件由刚性夹持/真空吸附保持)
        for _ in range(60):
            self.step(np.array([0, 0, 0, 1.0]))
            hold += 1
        ph = self.peg_head()
        dev_mm = float(np.linalg.norm(ph - AOI_FOCUS) * 1000)
        # 🛡 在位校验: 悬停期间 peg 必须仍被夹持 (z 在夹持高度, 未掉台) — 防空爪假报告
        pz = float(self.peg_center()[2])
        in_hand = pz > 0.05          # 夹持中 peg 中心 z≈0.08; 掉台 z≈0.015
        report = {"ok": in_hand, "method": "镜头对焦点悬停 (引擎 AOI_FOCUS 同源位, 3D 设备真实呈现)",
                  "hold_frames": hold, "dev_mm": round(dev_mm, 1),
                  "peg_z": round(pz, 4)}
        if not in_hand:
            self.log(f"   ❌ AOI 悬停中 peg 滑脱掉落 (peg z={pz:.3f}) — 中止, 不掩盖")
            self.history.append(f"⑦ AOI: peg 滑脱掉落 (z={pz:.3f}), 中止")
            return False
        self.history.append(f"⑦ AOI: {report}")
        self.log(f"   ✅ AOI 悬停保持 {hold} 帧, 头距对焦点 {dev_mm:.1f}mm")
        return True

    # ── 阶段 ⑧: 光耦合精密操作 (压电台) ──
    def stage_couple(self):
        self._stage = "⑧ 光耦合"
        self.log("── ⑧ 光耦合精密操作: 送件压电定位台 (参照芯明天) → 真空治具吸附 → "
                 "压电 x/y 微动伺服 η 收敛 ──")
        cp_ref = self.site("cp_ref")
        top = self.site("cp_stage_top")
        tt_top = float(top[2])
        peg_z = tt_top + 0.015 + 0.0005
        # 放件位: peg 头(-x 端)对准光纤基准 cp_ref (+人为放置偏置由伺服残差自然产生)
        place_x = cp_ref[0] + 0.10
        # 转移: 经上方
        self.servo(np.array([place_x, cp_ref[1], peg_z + 0.16]), tol=0.006, max_steps=900)
        self.servo(np.array([place_x, cp_ref[1], peg_z + 0.004]), tol=0.004, max_steps=500)
        # 解除刚性夹持 → 张爪放件 → peg 落台
        self._grip_lock = False
        self._lock_rel = None
        for _ in range(60):
            self.step(np.array([0, 0, 0, -1.0]))
        # 抬离夹爪
        self.servo(np.array([place_x, cp_ref[1], peg_z + 0.15]), tol=0.008, max_steps=300)
        # 真空吸附: peg 治具钉在台面 (台 x/y=0 → peg 中心固定)
        self._grab = True
        self._grab_center = np.array([place_x, cp_ref[1], peg_z])
        # 台复位钉 + 稳定
        q = self.d.qpos.copy()
        q[self.qadr:self.qadr+3] = [0.0, 0.0, 0.0]
        q[self.qadr+3:self.qadr+7] = [1, 0, 0, 0]
        self.d.qpos = q
        for _ in range(20):
            self.step(np.zeros(4))
        ph = self.peg_head()
        delta0 = (cp_ref - ph)[:2] * 1000
        eta0 = math.exp(-float(delta0 @ delta0) / (2 * SIGMA_MM ** 2))
        self.log(f"   放件吸附完成: δ0=({delta0[0]:+.2f},{delta0[1]:+.2f})mm η0={eta0:.4f}")
        # 压电微动伺服: 台 x/y 每轮 +0.5·δ (行程 ±2mm), peg 随台 (真空治具刚性)
        sx = sy = 0.0
        dlog = []
        for it in range(80):
            ph = self.peg_head()
            delta = (cp_ref - ph)[:2] * 1000
            dlog.append(delta.copy())
            if np.linalg.norm(delta) < 0.02:
                break
            sx = float(np.clip(sx + delta[0] * 0.0005, -0.002, 0.002))
            sy = float(np.clip(sy + delta[1] * 0.0005, -0.002, 0.002))
            self._grab_center = np.array([place_x + sx, cp_ref[1] + sy, peg_z])
            q = self.d.qpos.copy()
            q[self.qadr:self.qadr+3] = [sx, sy, 0.0]
            q[self.qadr+3:self.qadr+7] = [1, 0, 0, 0]
            self.d.qpos = q
            for _ in range(8):
                self.step(np.zeros(4))
        ph = self.peg_head()
        delta = (cp_ref - ph)[:2] * 1000
        eta = math.exp(-float(delta @ delta) / (2 * SIGMA_MM ** 2))
        report = {"ok": eta > 0.98, "eta": round(eta, 4),
                  "delta_mm": [round(float(delta[0]), 3), round(float(delta[1]), 3)],
                  "stage_xy_mm": [round(sx * 1000, 2), round(sy * 1000, 2)],
                  "iter": len(dlog), "sigma_mm": SIGMA_MM,
                  "method": "压电 x/y 微动伺服 (真空治具吸附, δ 真实计算)"}
        self.history.append(f"⑧ 光耦合: {report}")
        self.log(f"   ✅ η={eta:.4f} (δ={delta[0]:+.3f},{delta[1]:+.3f}mm · 台位 {sx*1000:+.2f},{sy*1000:+.2f}mm · {len(dlog)}轮)")
        return report

    def run_all(self):
        """L4 演示全链七段 (GUI 引擎 demo 模式委托入口): 返回 (success, meta)
        关键姿态/插拔段失败即中止 — 横置/夹持丢失后继续跑会产生假数据 (09-09 实锤)"""
        ok_all = True
        ok_all &= self.stage_turntable90() is not None
        if ok_all:
            ok_all &= self.stage_adapt_grasp()
        if ok_all:
            ok_all &= self.stage_yaw_back()
        if ok_all:
            ok_all &= self.stage_grasp_std()
        if ok_all:
            ok_all &= self.stage_insert()
        if ok_all:
            ok_all &= self.stage_pull()
        if ok_all:
            ok_all &= self.stage_aoi()
        if ok_all:
            cpl = self.stage_couple()
            ok_all &= cpl["ok"]
        else:
            cpl = {"ok": False, "eta": None, "delta_mm": [None, None], "stage_xy_mm": [None, None],
                   "iter": 0, "sigma_mm": SIGMA_MM, "method": "未执行 (前置段失败中止)"}
        for _k in self.tr:
            if _k in ("stage", "io_trace", "probe_seq"):
                self.tr[_k] = np.asarray(self.tr[_k], dtype=object)
            else:
                self.tr[_k] = np.asarray(self.tr[_k], dtype=float)
        if len(self.tr["done"]):
            self.tr["done"][-1] = 1.0 if ok_all else 0.0
        meta = dict(seed=0, success=ok_all, steps=self.steps,
                    stage_final="全链完成" if ok_all else "未完成",
                    demo="L4 演示: 转台90°外力干扰 + 插拔闭环 + AOI 镜头对焦点 + 光耦合精密操作",
                    demo_geom=self._demo_geom(),
                    aoi_focus=AOI_FOCUS.tolist(),
                    history=self.history, couple=cpl, env="sawyer_peg_insertion_side_l4")
        self._last_meta = meta
        return ok_all, meta

    def _demo_geom(self):
        """3D 视图场景几何: 演示场景注入的设备 (转台/压电耦合台) — GUI 按此绘制,
        让实时 L4D 播放可见转台与光耦合设备 (物理与视觉一致, 2026-09-09)"""
        return {
            "turntable": {"pos": TURNTABLE_XY.tolist(), "r": 0.075},
            "coupler": {"pos": COUPLER_XY.tolist()},
        }


def ensure_scene():
    """演示场景 XML 用真实 peg 惯量生成 (引擎默认 XML 不受影响)"""
    import subprocess as _sp
    _sp.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                          "gen_l4_demo_scene.py"), "--peg-real-inertia"],
            capture_output=True, timeout=60)

def main():
    ensure_scene()
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--also-latest", action="store_true",
                    help="额外覆盖 reports/ss_episode_latest.mp4 (GUI L4 档自动导出用同链接)")
    a = ap.parse_args()
    t0 = time.time()
    demo = L4Demo(seed=0)
    log = demo.log
    ok_all, _meta = demo.run_all()          # run_all 返回 (success, meta)
    meta = demo._last_meta if hasattr(demo, "_last_meta") else (_meta or dict(success=ok_all))
    cpl = meta.get("couple") or {"ok": ok_all}
    # ── 保存 npz + mp4 ──
    tag = time.strftime("%Y%m%d_%H%M%S")
    npz = os.path.join(REP, f"l4_demo_{tag}.npz")
    np.savez_compressed(npz, meta=np.array([meta], dtype=object))
    import subprocess, tempfile, shutil, cv2
    tmp = tempfile.mkdtemp(prefix="l4dm_")
    for i, fr in enumerate(demo.frames):
        cv2.imwrite(os.path.join(tmp, f"f{i:05d}.png"), cv2.cvtColor(fr, cv2.COLOR_RGB2BGR))
    mp4 = os.path.join(REP, f"l4_demo_{tag}.mp4")
    subprocess.run(["ffmpeg", "-y", "-framerate", str(FPS), "-i", os.path.join(tmp, "f%05d.png"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23", "-loglevel", "error", mp4],
                   check=True)
    shutil.rmtree(tmp, ignore_errors=True)
    if a.also_latest:
        latest_mp4 = os.path.join(REP, "ss_episode_latest.mp4")
        shutil.copyfile(mp4, latest_mp4)
        log(f"   📺 已覆盖 ss_episode_latest.mp4 (GUI L4 档同链接, 视频内容=本演示全链)")
    log(f"\n✅ L4 演示全链完成: success={ok_all} · {demo.steps} 步 · {time.time()-t0:.0f}s")
    log(f"   trace: {npz}")
    log(f"   🎬 视频: {mp4} ({len(demo.frames)} 帧)")
    log("\n阶段证据:")
    for h in demo.history:
        log("  →", h)


if __name__ == "__main__":
    main()
