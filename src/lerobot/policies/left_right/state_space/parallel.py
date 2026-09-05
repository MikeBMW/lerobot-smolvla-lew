"""parallel.py — S2 并行处理层 (快慢分离, 状态空间模型画布)

快通道 (前馈加速器 = 左脑 MLP):  obs → 建议动作 u_ff (权重 30%)
  - 直接映射, 无递归无延迟, 毫秒级 (~5ms)
  - 🧠 2026-09-04 老倪拍板: forward 主路径 = 训练左脑 MLP (547K) 蒸馏权重
    models/ss_left_brain.npz (tools/export_ss_left_brain.py 导出, 纯 numpy 4层 Linear,
    GUI gui-venv311 无 torch 也能跑)。解析比例律降级为 analytic_forward:
    权重缺失时的显式回退 + 标定层/功能审计的 Kp 字面量对象 (verification F-B02)。
  - obs 约定: 39D/43D 皆可 — [0:3]=末端, [3]=夹爪开度, [36:39]=目标(孔位);
    43D = 39D + 4D 触觉尾巴, MLP 只吃 [:39]。

慢通道 (自适应状态估计器, 原右脑 GRU): obs → 递归潜状态 + 卡尔曼预测-校正
  - 状态转移 A ≈ GRU 循环权重 W_hh (世界动力学)
  - 卡尔曼增益 K ≈ 更新门/重置门 (信预测 vs 信观测)
  - ~15ms, 产生修正信号 + contact 概率

输出汇合到 S3 认知决策层: 调度器 u = w_ff·u_ff + (1−w_ff)·u_fb
"""
import os

import numpy as np

W_FF = 0.3            # 前馈加速器建议权重 (认知调度器采纳比例)
LATENCY_FAST_MS = 5   # 快通道时耗
LATENCY_SLOW_MS = 15  # 慢通道时耗

# 仓库根 = parallel.py 上溯 6 级 (文件→state_space→left_right→policies→lerobot→src→根)
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))))
NPZ_DEFAULT = os.path.join(_REPO_ROOT, "models", "ss_left_brain.npz")
_NPZ_CACHE = {}       # npz 路径 → (W, b, sm, ss, am, astd); 实例化复用, 避免每 tick np.load 2.1MB


def load_npz_weights(npz_path):
    """加载蒸馏 MLP 权重 npz → (W[4], b[4], sm, ss, am, astd); 结果模块级缓存"""
    if npz_path not in _NPZ_CACHE:
        d = np.load(npz_path)
        _NPZ_CACHE[npz_path] = ([d[f"W{i}"] for i in range(4)], [d[f"b{i}"] for i in range(4)],
                                d["sm"], d["ss"], d["am"], d["astd"])
    return _NPZ_CACHE[npz_path]


def mlp_ff_forward(npz_path, probe=None):
    """蒸馏 MLP 前馈闭包 (与 state_space_sim.load_trained_left_brain 同款纯 numpy 实现,
    2026-09-04 收敛到此, sim 版保留为薄兼容层)
    probe: 可选 dict — 每 tick 写入隐层激活探针 (层能量/稀疏度/top活跃单元/输出归因),
    用于 GUI 展示"前馈加速器在想什么"。None = 零开销。"""
    W, b, sm, ss, am, astd = load_npz_weights(npz_path)

    def _layer_stat(a):
        """单层激活摘要: 能量(L2) / 稀疏度(ReLU 后零占比) / top3 活跃单元"""
        nz = int((a > 0).sum())
        top = np.argsort(a)[-3:][::-1]
        return {"act_l2": float(np.linalg.norm(a)),
                "active": nz, "dim": int(a.shape[0]),
                "top3": [(int(j), float(a[j])) for j in top]}

    def ff_forward(obs):
        o = np.asarray(obs, dtype=float)
        x = (np.asarray(o[:39], dtype=np.float32) - sm) / ss
        x1 = np.maximum(0.0, W[0] @ x + b[0])
        x2 = np.maximum(0.0, W[1] @ x1 + b[1])
        x3 = np.maximum(0.0, W[2] @ x2 + b[2])
        u_norm = W[3] @ x3 + b[3]
        u_xyz = np.clip(u_norm[:3] * astd[:3] + am[:3], -0.6, 0.6)
        # 夹爪 0/1 跳变回归学不好 → 规则控制 (同 ss_verify_trained.py)
        pos = o[0:3]
        target = o[36:39] if o.shape[-1] >= 39 else o[0:3]
        dist_h = float(np.linalg.norm(pos[:2] - target[:2]))
        u_grip = 1.0 if dist_h < 0.03 else 0.0
        if probe is not None:
            probe["_seq"] = probe.get("_seq", 0) + 1   # 🔭 帧序号 (窗口桥接去重)
            # 🧠 探针: 每层在想什么 (激活能量/稀疏度/top 活跃单元) + 输出归因
            probe["obs"] = {"hand": [round(v, 4) for v in pos],
                            "target": [round(v, 4) for v in target],
                            "d_h": round(float(np.linalg.norm(pos - target)), 4),
                            "d_xy": round(dist_h, 4),
                            "gripper": round(float(o[3]), 3)}
            probe["layers"] = [_layer_stat(a) for a in (x1, x2, x3)]
            # 输出归因: u 每维 = W3 行 · x3 → 找贡献最大的隐单元 (它在"指挥"动作)
            contrib = np.abs(W[3]) * x3[None, :]          # (4, 512)
            probe["out_contrib"] = []
            for d in range(3):
                j3 = np.argsort(contrib[d])[-3:][::-1]
                probe["out_contrib"].append(
                    [(int(j), float(W[3][d, j] * x3[j])) for j in j3])
            probe["u_ff"] = [round(v, 4) for v in (u_xyz[0], u_xyz[1], u_xyz[2], u_grip)]
            probe["act_raw"] = [x1, x2, x3]   # 全量激活 (每层512, 供直方图/分布可视化)
        return np.concatenate([u_xyz, [u_grip]])

    return ff_forward


D_GUARD = 0.25   # 稳定性守卫域: hand→目标 3D 距离 (2026-09-04 扩域数据 p99.9=0.25, max 0.263)
# 2026-09-04 实证 (勿删): 蒸馏 MLP 只在训练域内闭环收敛 (±1cm 扰动 done=True);
#   域外发散 (±3cm 扰动 1/3 seed 失败, ±5cm+ 全失败 → hand 恒速飞出 9m)。
#   解析比例律全局稳定 (全扰动 ≤±20cm done=True)。故域外由解析教师兜底。
#   训练域由 export_dataset(perturb=0.12) 决定; 扩域 → 重训 (tools 管道: export→build→lerobot_train→export_ss_left_brain)。


class FeedforwardAccelerator:
    """⚡ 前馈加速器 — 快路径: obs → u_ff 建议动作 (4D: dx dy dz gripper)

    🧠 2026-09-04 老倪拍板: __init__ 加载训练左脑 MLP (547K) 蒸馏权重
    (models/ss_left_brain.npz, 纯 numpy 4层 Linear), forward 跑真模型前向 —
    解析比例律退役为主路径, 降级为: 稳定性守卫 (域外兜底) + 标定层 Kp 字面量对象
    + 对比诊断 (analytic_forward)。self.loaded / self.n_mlp / self.n_guard 可查实际模式。
    """

    def __init__(self, w_ff=W_FF, npz_path=None):
        self.w_ff = w_ff            # 建议权重 (调度器按此比例采纳)
        self.npz_path = npz_path or NPZ_DEFAULT
        self.loaded = False         # True = MLP 已加载 (forward 主执行)
        self.n_mlp = 0              # 域内 MLP 调用计数 (可查: 真实执行占比)
        self.n_guard = 0            # 域外守卫调用计数
        self.probe = {}             # 🧠 隐层激活探针 (每 tick 更新, 展示"在想什么")
        try:
            self._ff = mlp_ff_forward(self.npz_path, self.probe)
            self.loaded = True
        except Exception as e:
            # 不静默: 打印明确警告 (真实执行可追溯), forward 走 analytic_forward
            print(f"⚠️ FeedforwardAccelerator: MLP 权重加载失败 ({self.npz_path}): {str(e)[:80]}"
                  f"\n   → 解析回退 analytic_forward (Kp={1.2}); 重新导出: "
                  f"~/lerobot-venv/bin/python tools/export_ss_left_brain.py")
            self._ff = None

    def forward(self, obs):
        """逆动力学建议 u_ff = π_ff(obs)。主路径 = 蒸馏 MLP (训练左脑 547K 行为);
        状态出训练域 (d>D_GUARD, 实证 MLP 域外发散) → 解析守卫兜底 (全局稳定, 同教师)。
        权重缺失时整体回退解析 (见 __init__ 警告与 self.loaded)。"""
        obs = np.asarray(obs, dtype=float)
        if self._ff is None:
            return self.analytic_forward(obs)
        target = obs[36:39] if obs.shape[-1] >= 39 else obs[0:3]
        d_guard = float(np.linalg.norm(obs[0:3] - target))
        if d_guard <= D_GUARD:
            self.n_mlp += 1
            return self._ff(obs)
        self.n_guard += 1
        return self.analytic_forward(obs)

    def analytic_forward(self, obs):
        """解析比例律 (2026-09-04 前的 forward, 保留: 权重缺失回退 / 标定层写回对象 /
        与蒸馏 MLP 的对比诊断基准)。实际工程已由 MLP 蒸馏承担 (tools/align_ff_kp.py
        2026-09-04 校验: 蒸馏 MAE 0.0009, Kp 等效 1.227 vs 1.2)。"""
        obs = np.asarray(obs, dtype=float)
        pos = obs[0:3]
        target = obs[36:39] if obs.shape[-1] >= 39 else pos
        Kp = 1.2                                   # 比例增益 (等效训练后增益; 2026-09-04 tools/align_ff_kp.py 反推: 全样本 1.227, 远/中层 1.18-1.19, z 维全程≈1.19 → 校验通过)
        u_xy = np.clip(Kp * (target - pos), -0.5, 0.5)
        dist_h = float(np.linalg.norm(pos[:2] - target[:2]))
        if dist_h < 0.03 and dist_h > 1e-6:
            dir_vec = (target - pos) / dist_h          # 最小推力方向 (对孔)
            u_xy[:2] = np.clip(u_xy[:2] + 0.03 * dir_vec[:2], -0.5, 0.5)
        gripper_cmd = 1.0 if dist_h < 0.03 else 0.0   # 近距闭合夹爪
        return np.concatenate([u_xy, [gripper_cmd]])


class AdaptiveStateEstimator:
    """🔮 自适应状态估计器 — 慢路径: obs → 潜状态 (递归 + 卡尔曼校正)

    卡尔曼组件对照:
      状态转移 A      ≈ GRU 循环权重 W_hh      (世界动力学)
      控制输入 B      ≈ action 输入             (动作如何改变世界)
      先验估计        ≈ (h_{t-1}, obs, action)  (猜下一步)
      卡尔曼增益 K    ≈ 更新门 + 重置门          (信预测 vs 信观测)
    """

    def __init__(self, A=0.95, K=0.5, B=1.0):
        self.A = A  # 预测强度 (状态转移)
        self.K = K  # 更新增益 (等效卡尔曼增益)
        self.B = B  # 控制输入增益 (action 如何改变状态; 速度指令时 = dt 积分)

    def predict(self, latent, action):
        """先验: x̂ₖ₋ = A·x̂ₖ₋₁ + B·uₖ (B=dt 时 = 位置 + 速度指令积分, 物理自洽)"""
        return self.A * latent + self.B * action

    def update(self, latent_pred, z_k):
        """后验: x̂ₖ = x̂ₖ₋ + K·(z_k − x̂ₖ₋)  (残差加权)"""
        return latent_pred + self.K * (z_k - latent_pred)
