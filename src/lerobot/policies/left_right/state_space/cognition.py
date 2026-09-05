"""cognition.py — S3 认知决策层 (状态空间模型画布)

🧪 状态校正器 (卡尔曼更新核心):
  残差 r = z_k − ĥ(x̂ₖ₋)  (传感器反馈 vs 先验预测之差)
  接触概率 = σ(残差·增益)
  校正后潜状态 x̂ₖ = x̂ₖ₋ + K·r  → 喂回先验预测器 (闭环)

🧭 动作调制器 (原状态机, 握有否决权): 6阶段状态机
  输入: u_ff 建议动作 (前馈加速器) + contact 概率/残差 (状态校正器)
  决策: 阶段切换 (接近→抓取→抬起→转移→插入→完成) + 动作融合
  融合: u = w_ff·u_ff + (1−w_ff)·u_fb
  否决权: 残差 > 阈值 → 强制减速/重试 (快路径无权独自行动)
"""
import numpy as np


def state_correction(prior_pred, z_k, K=0.5):
    """状态校正: 残差 r = z_k − prior_pred (传感器反馈 vs 先验预测);
    校正后潜状态 x̂ = prior_pred + K·r (卡尔曼更新核心, K=增益)"""
    residual = z_k - prior_pred
    corrected = prior_pred + K * residual
    return corrected, residual


def contact_probability(residual, gain=1.0):
    """接触概率: σ(残差·增益) — 残差大 → 接触/碰撞概率高"""
    return 1.0 / (1.0 + np.exp(-gain * residual))


class ActionModulator:
    """🧭 动作调制器 (原状态机, 握有否决权) — 8阶段状态机 + 按阶段动作融合

    阶段: 接近 → 对位 → 下降 → 抓取 → 抬起 → 转移 → 插入 → 完成
    (2026-08-25 老倪: 原 6 阶段从"手里已拿着光模块"开始, 缺「从初始位置到抓取光模块」的
     接近/对位/下降 三段 → 与操作视频 gen_insert_video 的八段状态机不同构。现补齐,
     状态空间模型与真机/仿真视频同一套阶段语义。)
    推进证据 (每步 advance 喂入, 真实调度不靠外部硬推):
      手-光模块水平距离 < 0.06      → 对位   (粗到位)
      手-光模块水平距离 < 0.02      → 下降   (精对位完成, 可垂直下刀)
      接触概率 > contact_th 或到达抓握位姿 → 抓取 (力觉/几何双证据)
      夹持建立 (gripper>0.8)     → 抬起   (夹爪已闭合)
      提起高度 > lift_h          → 转移   (光模块离台面)
      到位 (dist_h < align_th)   → 插入
      插入深度达标 (depth<阈值)   → 完成
    否决权: 残差 > veto_th → 强制减速重试; 连续 max_veto 次 → 异常上报
    动作融合按阶段调度:
      接近/对位/下降/抬起/转移 = 慢通道主导 (w_ff=0.3, 防碰撞)
      抓取/插入      = 前馈推力主导 (w_contact=0.85, 力控插入)
    夹持保持 (gripper latch): 抓取及之后阶段夹爪指令恒 1.0 — 否则抬起/转移阶段
      前馈层按"目标远→张开"输出 0, 光模块会掉 (真实系统夹持是状态锁存不是比例控制)。
    """

    STAGES = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"]
    GRASP_IDX = 3          # 「抓取」阶段序号 (≥ 此阶段夹爪锁存闭合)

    # 🚦 2026-08-26 老倪「动作调制器的速度总是慢一些」根因修复:
    #   原凸组合 u = w·u_ff + (1−w)·u_fb 在两向量量级差 21 倍时 (实测 |u_ff| 0.090 vs
    #   |u_fb| 0.0043 m/s) 退化成"把前馈砍到 w" — 实测 |u_fuse|/|u_ff| 恒 29%,
    #   慢通道只贡献 10% 速度却把 0.7 权重的噪声灌进方向 (方向抖动 4.77°→11.28°)。
    #   正规控制架构 = 前馈 + 反馈**相加** (反馈只做修正, 不缩放主项);
    #   "接触前要慢"改用**显式阶段限速**表达 (原来是靠凸组合意外砍出来的, 说不清道不明)。
    # 📊 2026-08-26 审计驱动调参 (tools/audit_state_machine.py 实测瓶颈):
    #   下降 2.02s 里 44% 时间贴 cap 0.05 → 抓握位姿是空中动作(夹爪张开跨在光模块两侧), 放到 0.09
    #   插入 1.81s 里 51% 贴 cap 0.06 → 力控要慢, 只微放到 0.07
    #   转移 2.08s 实速仅 0.113 远低于 cap 0.35 → 瓶颈不是 cap 而是比例控制末端磨蹭
    #     ⇒ 引入 STAGE_V_MIN 最小趋近速度 (证据未达标时给个速度下限, 别在末端磨)
    STAGE_V_CAP = {"接近": 0.35, "对位": 0.12, "下降": 0.09, "抓取": 0.04,
                   "抬起": 0.30, "转移": 0.35, "插入": 0.085, "完成": 0.02}
    STAGE_V_MIN = {"接近": 0.12, "对位": 0.04, "抬起": 0.10, "转移": 0.12}

    def __init__(self, w_ff=0.3, contact_th=0.6, veto_th=2.0, k_fb=1.0, v_cap=None,
                 w_contact=0.85, align_th=0.02, insert_depth=0.0005, max_veto=3,
                 align_xy_coarse=0.06, align_xy_fine=0.02, lift_h=0.08, grasp_th=0.8):
        # 🎯 2026-09-04 老倪(验收精度 0.5mm): insert_depth 4mm → 0.5mm (3D 到孔底;
        #   配合引擎孔壁 yz 对中, 插到底才判完成; 插入段时长仍 <0.5s 实测)
        self.w_ff = w_ff                # (保留兼容: fuse() 仍可用凸组合)
        self.k_fb = float(k_fb)         # 反馈增益 (相加式: u = u_ff + k_fb·u_fb)
        self.v_cap = dict(self.STAGE_V_CAP if v_cap is None else v_cap)   # 阶段限速 m/s
        self.v_min = dict(self.STAGE_V_MIN)      # 阶段最小趋近速度 (防末端磨蹭)
        self.confirm_n = 2          # 状态切换需连续 N 帧证据成立 (防噪声抖动误触发)
        self._pend = {}             # {目标阶段: 连续成立帧数}
        self._grasp_lost = 0        # 夹持丢失连续帧数 (回退重抓判据)
        self.contact_th = contact_th    # 接触判定阈值 (力觉证据)
        self.veto_th = veto_th          # 否决阈值 (残差异常)
        self.w_contact = w_contact      # 抓取/插入阶段前馈推力权重 (力控)
        self.align_th = align_th        # 孔位对准阈值 (转移→插入)
        self.insert_depth = insert_depth  # 插入深度达标 (插入→完成)
        self.max_veto = max_veto        # 连续否决上限 → 异常上报
        self.align_xy_coarse = align_xy_coarse  # 接近→对位 (手-光模块水平距离)
        self.align_xy_fine = align_xy_fine      # 对位→下降 (精对位)
        self.lift_h = lift_h                    # 抬起→转移 (光模块离台面高度)
        # 抓取→抬起 的夹持建立阈值 (夹爪闭合度 1=全闭)。⚠️ 真机/MuJoCo 里夹爪夹住实物后
        # 开度不可能到 0: 实测 metaworld 夹住 0.03m 光模块时闭合度饱和在 0.70 → 阈值必须
        # 按被夹物体尺寸标定, 写死 0.8 会永远等不到"夹持建立"而卡在抓取阶段。
        self.grasp_th = grasp_th
        self.stage_idx = 0
        self.veto_count = 0
        self.history = []               # 阶段切换历史 [(stage, reason)]

    def stage(self):
        return self.STAGES[self.stage_idx]

    def fuse(self, u_ff, u_fb):
        """接近阶段融合: u = w_ff·u_ff + (1−w_ff)·u_fb (慢通道主导)"""
        return self.w_ff * u_ff + (1.0 - self.w_ff) * u_fb

    def _goto(self, idx, reason):
        self.stage_idx = idx
        self.history.append((self.STAGES[idx], reason))

    def gripper_cmd(self, u_ff_g=0.0):
        """夹爪指令归状态机 (与操作视频状态机一致: 接近/对位/下降 张开, 抓取起闭合并保持)
        ⚠️ 不能听前馈层的"近距即闭合"启发: 对位/下降阶段手已经离光模块 <3cm, 前馈会提前
        把夹爪闭上 → 还没到抓取阶段夹爪就关了 (3D 视图里看不到"张开→夹紧"的抓取动作),
        且抓取阶段瞬间跳过 (gripper 早已 1.0)。夹持是状态锁存, 不是比例控制。"""
        return 1.0 if self.stage_idx >= self.GRASP_IDX else 0.0

    def _confirm(self, target_idx, reason):
        """状态切换需连续 confirm_n 帧证据成立 — 单帧噪声不足以推动状态机
        (审计: 证据在阈值±10% 带内可能滞留数十帧, 无确认机制则会来回抖)"""
        self._pend[target_idx] = self._pend.get(target_idx, 0) + 1
        if self._pend[target_idx] >= self.confirm_n:
            self._pend.clear()
            self._goto(target_idx, reason)
            return True
        return False

    def advance(self, contact_p=None, dist_h=None, gripper=None, depth=None,
                d_xy=None, lifted=None, at_grasp_pose=False, grasp_force=None,
                peg_z=None, peg_z_grasp=None):
        """状态机推进 — 感知/几何证据驱动 (每步调用)"""
        st = self.stage()
        # 🛟 夹持丢失 → 回退重抓 (审计建议的鲁棒性分支; 真机一定会掉件)
        #   判据: 抬起及之后阶段, 夹持力连续 5 帧 < 0.05 且光模块已落回抓握高度附近
        if self.stage_idx >= 4 and grasp_force is not None:
            self._grasp_lost = self._grasp_lost + 1 if float(grasp_force) < 0.05 else 0
            _fell = (peg_z is not None and peg_z_grasp is not None
                     and float(peg_z) < float(peg_z_grasp) + 0.02)
            if self._grasp_lost >= 5 and _fell:
                self._pend.clear()
                self._grasp_lost = 0
                self._goto(0, "⚠️ 夹持丢失且光模块落回台面 (连续5帧夹持力<0.05) → 回退重抓")
                return self.stage()
        # d_xy 缺省 (老调用方只喂 dist_h) → 退化用 dist_h 当水平距离证据
        dxy = d_xy if d_xy is not None else dist_h
        if st == "接近" and dxy is not None and dxy < self.align_xy_coarse:
            self._confirm(1, f"粗到位 手-光模块水平距离 {dxy:.4f} < {self.align_xy_coarse}")
        elif st == "对位" and dxy is not None and dxy < self.align_xy_fine:
            self._confirm(2, f"精对位完成 {dxy:.4f} < {self.align_xy_fine} → 可下降")
        elif st == "下降" and ((contact_p is not None and contact_p > self.contact_th)
                              or at_grasp_pose):
            # 两类证据任一成立即可闭爪: ①力觉触到光模块 ②几何到达抓握位姿
            #   (张开的夹爪下到光模块两侧时可能完全不接触 → 只等力觉会永远卡在下降)
            self._confirm(3, (f"触到光模块 接触概率 {contact_p:.2f} > {self.contact_th}"
                              if (contact_p is not None and contact_p > self.contact_th)
                              else "到达抓握位姿 (几何证据)"))
        elif st == "抓取" and gripper is not None and gripper > self.grasp_th:
            self._confirm(4, f"夹持建立 gripper={gripper:.2f}")
        elif st == "抬起" and lifted is not None and lifted > self.lift_h:
            self._confirm(5, f"光模块已提起 {lifted:.4f}m > {self.lift_h}m")
        elif st == "转移" and dist_h is not None and dist_h < self.align_th:
            self._confirm(6, f"对准孔口 dist_h={dist_h:.4f}")
        elif st == "插入" and depth is not None and depth < self.insert_depth:
            self._confirm(7, f"插入深度达标 depth={depth:.4f}")
        else:
            self._pend.clear()          # 证据不成立 → 清空待确认计数 (必须连续)
        return self.stage()

    def decide(self, u_ff, u_fb, contact_p, residual):
        """决策: ①否决权 (残差异常) ②前馈+反馈**相加** ③按阶段显式限速

        u = u_ff + k_fb·u_fb, 然后按当前阶段的速度上限等比缩放 (只削幅, 不改方向)。
        为什么不再用凸组合: 见 STAGE_V_CAP 上方注释 (量级差 21 倍 → 凸组合等于砍速度)。
        """
        _zero = np.zeros_like(np.asarray(u_ff, dtype=float))
        if residual > self.veto_th:
            self.veto_count += 1
            if self.veto_count >= self.max_veto:
                return _zero, f"异常: 连续否决 (残差 {residual:.2f})"
            return _zero, f"否决: 减速/重试 (残差 {residual:.2f})"
        self.veto_count = 0
        st = self.stage()
        u = np.asarray(u_ff, dtype=float) + self.k_fb * np.asarray(u_fb, dtype=float)
        n = float(np.linalg.norm(u[:3])) if u.ndim else abs(float(u))
        cap = self.v_cap.get(st)
        if cap is not None and n > cap > 0:
            u = u * (cap / n)              # 等比缩放: 保方向, 只削速度
            n = cap
        vmin = self.v_min.get(st)
        if vmin is not None and 1e-6 < n < vmin:
            u = u * (vmin / n)             # 最小趋近速度: 证据未达标时别在末端磨 (同样保方向)
        tag = " · 接触" if contact_p > self.contact_th else ""
        return u, f"阶段 {st}{tag}"
