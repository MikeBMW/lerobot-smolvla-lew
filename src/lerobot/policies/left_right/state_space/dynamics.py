"""dynamics.py — 先验动力学预测器 (状态空间模型画布)

预测 next state: x̂ₖ₋ = A·x̂ₖ₋₁ + B·uₖ  (先验 = 还没看传感器就先猜)
- 🧠 2026-09-06 老倪拍板: 主路径 = 训练右脑 WorldModel (RightBrainWM) 真权重
  (models/ss_right_brain.npz, tools/export_ss_right_brain.py 导出, 纯 numpy):
  obs(39 raw) + act(4 raw) → next_obs 预测 (含位置) + contact 判断 (抓取时机, acc 1.00)。
  线性 A·x + B·u 降级为: 无权重/无 obs/域外 的教学守卫回退 (同左脑 mlp_ff_forward 模式)。
- 域守卫: 右脑单布局训练 → 布局漂移 (真实化现场采样) 归一化通道超 DOMAIN_SIGMA → 线性
  (真实化 real sim 不传 obs 即恒线性, 同 accel 强制解析理由)。
- 输出 → 状态校正器作为残差基准 (z_k − ĥ(x̂ₖ₋)): 先验 vs 观测差 = 残差;
  残差大 = 世界出乎意料 → 接触/异常信号。
"""
import os

import numpy as np

# 仓库根 = dynamics.py 上溯 6 级 (文件→state_space→left_right→policies→lerobot→src→根)
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))))
NPZ_DEFAULT = os.path.join(_REPO_ROOT, "models", "ss_right_brain.npz")
DOMAIN_SIGMA = 4.0   # 逐通道训练域上限 (同 parallel.py 左脑守卫)


def rb_ff_forward(npz_path=None, probe=None):
    """右脑 WorldModel 纯 numpy 前向闭包: obs(39 raw) + act(4 raw) → (next_obs raw, contact)
    RightBrainWM (modeling_left_right.py): enc 2层 ReLU → pred_next + contact_head(sigmoid)。
    pred_next 输出为归一化空间 (导出时实测, next_raw=False) → 反归一化 *ss+sm 回 raw。
    """
    d = np.load(npz_path or NPZ_DEFAULT)
    W = {k: d[k] for k in ("W_e0", "b_e0", "W_e1", "b_e1", "W_p", "b_p", "W_c", "b_c")}
    sm = d["sm"] if "sm" in d else None
    ss = d["ss"] if "ss" in d else None
    next_raw = bool(d["next_raw"]) if "next_raw" in d else True

    def ff_forward(obs, act):
        o = np.asarray(obs, dtype=np.float32)
        a = np.asarray(act, dtype=np.float32)
        if o.ndim == 1:
            x = np.concatenate([o, a])
            h = np.maximum(0.0, W["W_e0"] @ x + W["b_e0"])
            h = np.maximum(0.0, W["W_e1"] @ h + W["b_e1"])
            nxt_n = W["W_p"] @ h + W["b_p"]
            nxt = nxt_n if next_raw else (nxt_n * ss + sm)
            c = (W["W_c"] @ h + W["b_c"]).reshape(-1)   # W_c (1,256) → (1,) → 标量
            contact = float(1.0 / (1.0 + np.exp(-c[0])))
            return nxt, contact
        # 批量 (n, 39)/(n, 4)
        x = np.concatenate([o, a], axis=-1)
        h = np.maximum(0.0, x @ W["W_e0"].T + W["b_e0"])
        h = np.maximum(0.0, h @ W["W_e1"].T + W["b_e1"])
        nxt_n = h @ W["W_p"].T + W["b_p"]
        nxt = nxt_n if next_raw else (nxt_n * ss + sm)
        contact = 1.0 / (1.0 + np.exp(-(h @ W["W_c"].T + W["b_c"])))
        return nxt, contact

    ff_forward.sm = sm
    ff_forward.ss = ss
    ff_forward.next_raw = next_raw
    return ff_forward


class PriorDynamicsPredictor:
    """📈 先验动力学预测器 — 潜状态/观测 → next 位置先验 (残差基准)

    predict(latent, action, obs=None): obs(39D raw) 传入且右脑权重就绪且通道域内 →
    右脑 WorldModel 预测 next_obs 位置作先验 (真权重主执行); 否则线性 A·latent + B·action。
    """

    def __init__(self, A=0.95, B=1.0, npz_path=None, use_wm=True):
        self.A = A  # 状态转移 (线性回退; 教学语义 ≈ GRU 循环权重)
        self.B = B  # 控制输入增益
        self.wm = None
        self.loaded = False
        self.n_wm = 0      # 真权重主执行计数
        self.n_linear = 0  # 线性回退计数
        if use_wm:
            try:
                self.wm = rb_ff_forward(npz_path)
                self.loaded = True
            except Exception as e:
                print(f"⚠️ PriorDynamicsPredictor: 右脑权重加载失败: {str(e)[:80]}"
                      f"\n   → 线性回退 A·x+B·u; 重新导出: ~/lerobot-venv/bin/python "
                      f"tools/export_ss_right_brain.py")
                self.wm = None

    def predict(self, latent, action, obs=None):
        """先验预测: 右脑 WorldModel (obs+act → next_obs 位置) 主执行; 线性守卫回退"""
        use_wm = self.wm is not None and obs is not None
        if use_wm and self.wm.sm is not None:
            o = np.asarray(obs, dtype=np.float32)[:39]
            sm, ss = self.wm.sm, self.wm.ss
            xn = (o - sm) / np.where(ss > 1e-4, ss, 1.0)
            if np.any(np.abs(np.where(ss > 1e-4, xn, np.float32(0.0))) > DOMAIN_SIGMA):
                use_wm = False
        if use_wm:
            try:
                nxt, contact = self.wm(np.asarray(obs, dtype=np.float32)[:39],
                                       np.asarray(action, dtype=np.float32))
                self.n_wm += 1
                lat = np.asarray(latent, dtype=float)
                return np.concatenate([nxt[:3], [self.A * float(lat[3]) if lat.size > 3 else 0.0]])
            except Exception:
                use_wm = False
        self.n_linear += 1
        return self.A * np.asarray(latent, dtype=float) + self.B * np.asarray(action, dtype=float)
