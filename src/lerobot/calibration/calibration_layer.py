# -*- coding: utf-8 -*-
"""calibration_layer.py — 🧮 标定层: 引力/斥力二分超参数 + 平衡点

第一性原理 (2026-09-02 老倪, 参考 Drifting Models arXiv:2602.04770):
  把状态空间引擎的全部超参数按作用方向二分:
    引力 (Attraction) = 快速动作 — 把末端拉向目标 (Kp·(target−pos) + 阶段速度上限/下限)
    斥力 (Repulsion)  = 状态预测 — 把状态估计拉回与预测一致 (卡尔曼校正/残差EMA/接触判定)
  两者平衡点 = 系统无漂移 (V≈0, 对应论文 q=p 平衡; 反称场 Vp,q(x) = −Vq,p(x) ⇒ q=p ⇒ V=0)。

标定量: 状态/阶段是明确的标定量 — 每个阶段的 STAGE_V_CAP 是该阶段的速度标定,
        每个估计增益 (K_kalman/EMA/接触增益/否决阈值) 是状态预测的标定。

定位 (2026-09-03 v3.4.5 升级): 标定层是引擎标定的**真源** — apply_to_engine() 把
      标定值精确写回引擎源码字面量 (parallel.py Kp/u_clip、cognition.py STAGE_V_CAP/
      STAGE_V_MIN/veto_th/k_fb、state_space_sim.py 校正K/EMA/接触增益/安全限幅/先验A)。
      引擎 (tools/gui/state_space_sim.py) 每次 ▶运行 importlib 重新 exec 六层源码文件 →
      **表格保存后下一次运行即用新标定值, 无需重启 GUI**。VSCode 断点仍可进 (源码真实)。

数据同源: 标定表默认值 = 引擎当前源码真值 (曾错: prior_A 写 parallel.py 默认 0.95,
          引擎 AdaptiveStateEstimator/PriorDynamicsPredictor 显式 A=1.0 — 已校准为 1.0)。
"""
import json
import os
import re
import time

STAGES = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"]

# ── 引力标定 (快速动作) — 与 parallel.py FeedforwardAccelerator / cognition.py 同源 ──
ATTRACTION_CALIB = {
    "Kp": 1.2,                # 比例引导增益 (前馈加速器 Kp·(target−pos) 限幅 ±0.5)
    "u_clip": 0.5,            # 前馈限幅
    "safety_limit": 0.6,      # 安全执行边界 saturate 限幅
    "stage_v_cap": {          # 各阶段速度上限 (明确标定量: 每阶段一个速度标定)
        "接近": 0.35, "对位": 0.12, "下降": 0.09, "抓取": 0.04,
        "抬起": 0.30, "转移": 0.35, "插入": 0.07, "完成": 0.02},
    "stage_v_min": {          # 最小趋近速度 (证据未达标时别在末端磨)
        "接近": 0.12, "对位": 0.04, "抬起": 0.10, "转移": 0.12},
}

# ── 斥力标定 (状态预测) — 与 state_space_sim.py 卡尔曼/滤波/接触判定同源 ──
REPULSION_CALIB = {
    "K_kalman": 0.5,          # 状态校正增益 (state_space_sim.run L274 state_correction K=0.5)
    "res_ema": 0.15,          # 残差 EMA 滤波系数 (run L286 α=0.15, 系数对 0.85/0.15 同步写)
    "contact_gain": 8,      # 接触概率增益 (run L280 contact_probability gain=8.0)
    "veto_th": 2,           # 否决阈值 (cognition.py ActionModulator.__init__ 默认 veto_th=2.0)
    "k_fb": 1,              # 反馈增益 (cognition.py decide 相加 k_fb, 默认 1.0)
    "prior_A": 1,           # 先验动力学状态转移 (run L123 PriorDynamicsPredictor(A=1.0) — 引擎真值)
}

# 平衡判定阈值 (|引力势−斥力势| < 此值 = 平衡)
EQ_BAND = 0.15


class CalibrationLayer:
    """标定层 — 引力/斥力标定参数 + 平衡点计算 (纯数据/计算, 不参与引擎推理)"""

    def __init__(self, attraction=None, repulsion=None):
        self.attr = dict(ATTRACTION_CALIB)
        if attraction:
            self.attr.update(attraction)
        self.rep = dict(REPULSION_CALIB)
        if repulsion:
            self.rep.update(repulsion)

    # ── 引力势: 当前速度贴阶段上限的程度 (1.0=满速贴上限, <1=有余量) ──
    def attraction_potential(self, stage, speed):
        cap = float(self.attr["stage_v_cap"].get(stage, 0.1))
        return float(min(1.0, abs(speed) / max(cap, 1e-6)))

    # ── 斥力势: 状态预测的不确定性 (残差贴否决阈值的程度 + 接触概率) ──
    def repulsion_potential(self, residual, contact_p):
        r = float(min(1.0, abs(residual) / max(self.rep["veto_th"], 1e-6)))
        return float(0.7 * r + 0.3 * (1.0 - float(contact_p)))

    # ── 平衡偏差: 引力势 − 斥力势; |gap|→0 表示引力斥力平衡 (V≈0, 无漂移) ──
    def equilibrium_gap(self, stage, speed, residual, contact_p):
        return self.attraction_potential(stage, speed) - self.repulsion_potential(residual, contact_p)

    def equilibrium_state(self, gap):
        if abs(gap) < EQ_BAND:
            return "⚖ 平衡"
        return "引力↑ 动作偏快" if gap > 0 else "斥力↑ 状态修正偏强"

    # ── 一行可读摘要 (画布日志用) ──
    def summarize(self, stage, speed, residual, contact_p):
        a = self.attraction_potential(stage, speed)
        r = self.repulsion_potential(residual, contact_p)
        g = a - r
        return (f"标定层 · {stage}: 引力势 {a:.2f} vs 斥力势 {r:.2f} · "
                f"平衡偏差 {g:+.2f} → {self.equilibrium_state(g)}")

    # ── 标定表导出 (落盘 json 快照) ──
    def export(self, path=None):
        if path is None:
            path = os.path.join("reports", f"calibration_{time.strftime('%Y%m%d_%H%M%S')}.json")
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"attraction": self.attr, "repulsion": self.rep,
                       "eq_band": EQ_BAND}, f, ensure_ascii=False, indent=1)
        return path

    # ── 🎯 应用标定 (2026-09-03 v3.4.5 闭环): 写回引擎源码 + 自身镜像 ──
    def apply_to_engine(self, src_root=None):
        """把当前 attr/rep 标定值精确写回引擎源码字面量 (三文件), 返回写回明细。"""
        return apply_calib_to_engine(self, src_root)

    def apply_to_file(self, calib_path):
        """写回 calibration_layer.py 常量 dict (下次打开表格的默认值源)。"""
        return apply_calib_to_file(self, calib_path)


# ════════════════════════════════════════════════════════════════════
# 🎯 引擎写回 (2026-09-03 v3.4.5 老倪: 标定闭环 — 表格改完 → 引擎真生效)
# 每个标定参数 → 引擎源码文件里的精确代码锚点 (值无关正则, 只认代码上下文)。
# 引擎 tools/gui/state_space_sim.py 每次 ▶运行 importlib 重新 exec 六层源码文件,
# 故写回引擎文件后**下一次运行即生效**, 无需重启 GUI。
# 锚点命中数 != 预期 → 抛 ValueError (不静默失败 — 引擎源码若被改动会立刻暴露)。
# ════════════════════════════════════════════════════════════════════

# 引擎文件相对仓库根的路径
ENGINE_PARALLEL = os.path.join("src", "lerobot", "policies", "left_right", "state_space", "parallel.py")
ENGINE_COGNITION = os.path.join("src", "lerobot", "policies", "left_right", "state_space", "cognition.py")
ENGINE_SIM = os.path.join("tools", "gui", "state_space_sim.py")


def _num(v):
    """数值字面量格式: 去尾零但整数保留 .0 (引擎源码风格 2.0/1.0/8.0)"""
    s = f"{float(v):.6g}"
    return s if "." in s else s + ".0"


def _sub_n(src, pattern, value, fmt=None):
    """前缀锚点替换: pattern 捕获「代码前缀」, 后面跟任意数值 → 换成新值。
    fmt: 数值格式 (None = _num 自适应; ".2f" = 固定两位小数带尾零 — 引擎 stage dict 风格)。
    返回 (新源码, 命中数)。命中数必须 >=1, 由调用方断言。"""
    pat = re.compile(rf"{pattern}[\d.]+")
    n = len(pat.findall(src))

    def _repl(m):
        return m.group(1) + (f"{float(value):{fmt}}" if fmt else _num(value))
    return pat.sub(_repl, src), n


def _repo_root(start=None):
    """从本文件上溯定位仓库根 (src/lerobot/calibration → 上溯 3 级)"""
    d = os.path.dirname(os.path.abspath(start or __file__))
    for _ in range(3):
        d = os.path.dirname(d)
    return d


def _read(path):
    return open(path, encoding="utf-8").read()


def _write(path, src):
    open(path, "w", encoding="utf-8").write(src)


def apply_calib_to_engine(calib, src_root=None):
    """把标定表写回引擎源码 — 每个参数落到真实引擎字面量。

    calib: CalibrationLayer 实例 (取 .attr/.rep)。
    返回: {引擎文件名: [已写参数...]} 供 UI 展示。
    锚点未命中 → ValueError (参数/文件/说明) — 绝不静默。
    """
    src_root = src_root or _repo_root()
    layer = calib if isinstance(calib, CalibrationLayer) else None
    attr = layer.attr if layer else calib[0]
    rep = layer.rep if layer else calib[1]
    done = {}

    def _touch(fname, *params):
        done.setdefault(fname, []).extend(params)

    # ── ① parallel.py: Kp ──
    p_par = os.path.join(src_root, ENGINE_PARALLEL)
    s = _read(p_par)
    s, n = _sub_n(s, r"(Kp = )", attr["Kp"])
    if n != 1:
        raise ValueError(f"Kp 锚点命中 {n} 次 (期望 1) — {ENGINE_PARALLEL}")
    # ② parallel.py: u_clip — 前馈两处限幅 (-u_clip, u_clip), 值无关锚点
    uc = float(attr["u_clip"])
    pat_lo = re.compile(r"(u_xy = np\.clip\(Kp \* \(target - pos\), -)[\d.]+(, )[\d.]+(\))")
    s2, n_lo = pat_lo.subn(lambda m: f"{m.group(1)}{_num(uc)}{m.group(2)}{_num(uc)}{m.group(3)}", s)
    pat_hi = re.compile(r"(u_xy\[:2\] = np\.clip\(u_xy\[:2\] \+ 0\.03 \* dir_vec\[:2\], -)[\d.]+(, )[\d.]+(\))")
    s2, n_hi = pat_hi.subn(lambda m: f"{m.group(1)}{_num(uc)}{m.group(2)}{_num(uc)}{m.group(3)}", s2)
    if n_lo != 1 or n_hi != 1:
        raise ValueError(f"u_clip 限幅锚点命中 lo={n_lo}/hi={n_hi} (期望 1/1) — {ENGINE_PARALLEL}")
    _write(p_par, s2)
    _touch(ENGINE_PARALLEL, "Kp", "u_clip")

    # ── ③ cognition.py: veto_th / k_fb (ActionModulator.__init__ 默认, 引擎无参实例化吃默认) ──
    p_cog = os.path.join(src_root, ENGINE_COGNITION)
    s = _read(p_cog)
    for param, key in (("veto_th", "veto_th"), ("k_fb", "k_fb")):
        s, n = _sub_n(s, rf"({key}=)", rep[param])
        if n != 1:
            raise ValueError(f"{param} 锚点命中 {n} 次 (期望 1) — {ENGINE_COGNITION}")
    # ④ cognition.py: STAGE_V_CAP / STAGE_V_MIN 类常量 dict (整块内逐 key, 避免两 dict 交叉)
    for dname, mapping in (("STAGE_V_CAP", attr["stage_v_cap"]),
                           ("STAGE_V_MIN", attr["stage_v_min"])):
        m = re.search(rf"({dname} = \{{)(.*?)(\}})", s, re.S)
        if not m:
            raise ValueError(f"{dname} 块未找到 — {ENGINE_COGNITION}")
        block = m.group(2)
        missing = []
        for k, v in mapping.items():
            kb, nk = _sub_n(block, rf'("{k}": )', v, fmt=".2f")
            if nk != 1:
                missing.append(k)
            block = kb
        if missing:
            raise ValueError(f"{dname} 锚点未命中: {missing} — {ENGINE_COGNITION}")
        s = s[:m.start(2)] + block + s[m.end(2):]
    _write(p_cog, s)
    _touch(ENGINE_COGNITION, "veto_th", "k_fb", "stage_v_cap", "stage_v_min")

    # ── ⑤ state_space_sim.py: K_kalman / contact_gain / safety_limit / prior_A ──
    p_sim = os.path.join(src_root, ENGINE_SIM)
    s = _read(p_sim)
    for param, prefix in (("K_kalman", r"(state_correction\(prior, z_k, K=)"),
                          ("contact_gain", r"(contact_probability\(r_scalar, gain=)"),
                          ("safety_limit", r"(saturate\(u, limit=)"),
                          ("prior_A", r"(PriorDynamicsPredictor\(A=)")):
        val = attr[param] if param in attr else rep[param]
        s, n = _sub_n(s, prefix, val)
        if n != 1:
            raise ValueError(f"{param} 锚点命中 {n} 次 (期望 1) — {ENGINE_SIM}")
    # ⑥ state_space_sim.py: res_ema — 系数对 (1−α, α) 同步写
    alpha = float(rep["res_ema"])
    pat_ema = re.compile(r"(\(0\.\d+ \* self\.res_ema \+ )0\.\d+( \* np\.asarray)")
    s, n_ema = pat_ema.subn(lambda m: f"({_num(1 - alpha)} * self.res_ema + {_num(alpha)}{m.group(2)}", s)
    if n_ema != 1:
        raise ValueError(f"res_ema 系数对锚点命中 {n_ema} 次 (期望 1) — {ENGINE_SIM}")
    _write(p_sim, s)
    _touch(ENGINE_SIM, "K_kalman", "contact_gain", "safety_limit", "prior_A", "res_ema")

    return done


def apply_calib_to_file(calib, calib_path):
    """写回 calibration_layer.py 自身常量 dict (镜像 — 下次打开表格的默认值源)。

    🐛 2026-09-03: 裸 key 正则会把 stage_v_min 的 key (接近/对位/抬起/转移) 串写到
    更靠前的 stage_v_cap 块 — 子 dict 必须**块内**替换 (与引擎写回同策略)。"""
    src = _read(calib_path)
    layer = calib if isinstance(calib, CalibrationLayer) else None
    attr = layer.attr if layer else calib[0]
    rep = layer.rep if layer else calib[1]
    # 顶层 scalar (Kp/u_clip/safety_limit + rep 6 项) — 全文件唯一, 直接替换
    for key, val in list(attr.items()) + list(rep.items()):
        if key in ("stage_v_cap", "stage_v_min"):
            continue
        src, n = _sub_n(src, rf'("{key}": )', val)
        if n != 1:
            raise ValueError(f"标定表镜像 {key} 锚点命中 {n} 次 (期望 1) — {calib_path}")
    # 子 dict 块内逐 key (避免跨块串写: V_MIN 的 key 在 V_CAP 也出现)
    for dname, mapping in (("stage_v_cap", attr["stage_v_cap"]),
                           ("stage_v_min", attr["stage_v_min"])):
        m = re.search(rf'"{dname}": \{{(.*?)\}}', src, re.S)
        if not m:
            raise ValueError(f"标定表镜像块 {dname} 未找到 — {calib_path}")
        block = m.group(1)
        missing = []
        for k, v in mapping.items():
            kb, nk = _sub_n(block, rf'("{k}": )', v, fmt=".2f")
            if nk != 1:
                missing.append(k)
            block = kb
        if missing:
            raise ValueError(f"标定表镜像 {dname} 锚点未命中: {missing} — {calib_path}")
        src = src[:m.start(1)] + block + src[m.end(1):]
    _write(calib_path, src)
    return calib_path
