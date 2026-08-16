#!/usr/bin/env python3
"""kalman_fusion.py — 右脑世界模型的「置信度旋钮」工程化 (2026-08-16 老倪)

思想: 右脑 GRU/WM 是非线性黑箱, 无法直接改 A 矩阵, 但在「预测值(GRU输出)」和
「观测值(真实传感器)」之间外挂一个可调谐的残差加权融合层:

    fused = (1 - α) · pred_state + α · measured_state     α ∈ [0,1]

α = 等效卡尔曼增益 (Kalman Gain Knob):
    α→0  完全信任世界模型 (预测) — 传感器噪声大/瞬态干扰时
    α→1  完全信任传感器 (观测) — 信号平滑准确时
α 按状态机阶段调度 (增益调度表 α(Stage)), 与状态机的宏观决策正交:
    状态机 = 宏观决策 (何时切换阶段)
    α      = 微观信号融合 (怎么相信传感器)

标定三件套 (像标定 PID 一样标定世界模型):
  Step1 静态噪声标定 R : 机器人静止, 记录 N 次传感器读数 → std = σ_sensor
  Step2 开环漂移标定 Q : 空载快速动作, 右脑只预测(开环)持续推演 → 漂移误差 → σ_model
  Step3 α 扫描 + Lissajous: 正弦激励, 横轴=实测, 纵轴=预测, 调 α 使椭圆最扁
        (细长椭圆≈直线 = 预测与观测完美对齐 = 最优 α)

用法 (.venv 跑, 需 torch):
    python3 tools/kalman_fusion.py                # 全部三步 + 报告
    python3 tools/kalman_fusion.py --stage R      # 单跑一步
产物: reports/kalman_fusion.json + reports/kalman_lissajous.png
"""
import argparse
import json
import os
import sys

import numpy as np

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
REPORTS = os.path.join(REPO, "reports")
os.makedirs(REPORTS, exist_ok=True)

# 状态机 6 阶段 → 推荐 α 调度表 (2026-08-16 老倪: 接近低增益/插入高增益)
ALPHA_SCHEDULE = {
    "approach": 0.3,   # 接近: 主要靠模型快速驱动, 传感器反而不稳 (信任视觉引导但不过度响应噪声)
    "grasp":    0.5,   # 抓取: 平衡 (模型+传感器各半)
    "lift":     0.5,   # 抬起: 平衡, 平滑过渡
    "transfer": 0.7,   # 转移: 偏传感器 (位置对齐关键)
    "insert":   0.9,   # 插入: 绝对依赖实时力觉/位置反馈, 避免模型累积误差 (绝不能靠"想象")
    "done":     0.5,   # 完成: 平衡
}

# 标定默认参数
N_STATIC = 1000       # 静态噪声标定采样数
DRIFT_SEC = 2.0       # 开环漂移推演时长 (s)
DT = 0.01             # 控制周期 (s)


def kalman_fusion(pred_state, measured_state, alpha):
    """残差加权融合层 (等效卡尔曼增益):
    fused = (1-α)·pred + α·meas — 预测与观测的凸组合, α 由调度表按阶段给出
    """
    pred_state = np.asarray(pred_state, dtype=float)
    measured_state = np.asarray(measured_state, dtype=float)
    return (1.0 - alpha) * pred_state + alpha * measured_state


def stage_alpha(stage):
    """按状态机阶段取 α (增益调度表); 未知阶段默认 0.5"""
    return ALPHA_SCHEDULE.get(stage, 0.5)


# ════════════════════════════════════════════════════════════════
# Step 1: 静态噪声标定 R (传感器可信度)
# ════════════════════════════════════════════════════════════════
def calibrate_R(seed=1, n=N_STATIC, sigma_true=0.01):
    """机器人停在固定位置, 连续记录 n 次 3D 视觉/力觉读数 → 标准差 σ_sensor.
    返回: R = σ_sensor (越小传感器越准, α 应偏大更信传感器).
    ⚠️ 真实部署: 读实际传感器 1000 次; 这里用仿真数据演示标定流程.
    """
    rng = np.random.default_rng(seed)
    readings = rng.normal(0.0, sigma_true, size=(n, 3))  # 3D 位置噪声
    sigma_sensor = float(np.std(readings, axis=0).mean())
    return {"sigma_sensor": sigma_sensor, "n": n, "R": sigma_sensor ** 2,
            "verdict": "传感器可信 (α 偏大)" if sigma_sensor < 0.02 else "传感器噪声大 (α 偏小)"}


# ════════════════════════════════════════════════════════════════
# Step 2: 开环漂移标定 Q (世界模型可信度)
# ════════════════════════════════════════════════════════════════
def calibrate_Q(seed=1, drift_sec=DRIFT_SEC, dt=DT, sigma_model=0.03):
    """空载快速动作 (如抬升 5cm), 右脑只做预测 (开环, 无传感器反馈) 持续推演.
    对比 GRU 预测位置 vs 2 秒后实际位置 → 漂移误差 → σ_model.
    返回: Q = σ_model² (漂移越大模型越不可靠, α 应偏大降低预测权重).
    """
    rng = np.random.default_rng(seed)
    steps = int(drift_sec / dt)
    pred_pos = np.zeros(steps)          # 模型预测轨迹 (理想线性)
    drift = rng.normal(0.0, sigma_model, size=steps).cumsum()  # 累积漂移 (随机游走)
    actual_pos = pred_pos + drift       # 实际位置 = 预测 + 漂移
    drift_err = float(np.abs(actual_pos[-1] - pred_pos[-1]))
    sigma_model = float(np.std(actual_pos - pred_pos))
    return {"drift_err_m": drift_err, "sigma_model": sigma_model, "Q": sigma_model ** 2,
            "verdict": "模型漂移小 (可信, α 可偏小)" if drift_err < 0.02 else "模型漂移大 (α 应偏大靠传感器)"}


# ════════════════════════════════════════════════════════════════
# Step 3: α 扫描 + Lissajous 图形法 (终极标定)
# ════════════════════════════════════════════════════════════════
def scan_alpha(seed=1, phase_lag=0.35, meas_noise=0.01):
    """正弦激励: 末端执行器正弦波, 右脑模型执行相同动作.
    横轴=实测位置, 纵轴=模型预测 → Lissajous 图.
    α 偏信模型 → 圆 (相位滞后); α 偏信传感器 → 混乱噪点;
    细长椭圆≈直线 = 预测与观测完美对齐 = 最优 α.
    返回: 每 α 的拟合残差 (残差最小 = 椭圆最扁 = 最优).
    """
    rng = np.random.default_rng(seed)
    t = np.linspace(0, 2 * np.pi, 200)
    measured = np.sin(t) + rng.normal(0, meas_noise, size=len(t))
    pred = np.sin(t - phase_lag)          # 模型有相位滞后 → 圆
    results = []
    for alpha in np.arange(0.0, 1.01, 0.1):
        fused = kalman_fusion(pred, measured, alpha)
        # 拟合残差: fused 与 measured 的偏差 (α 越大越贴传感器, 但失去模型平滑)
        resid = float(np.std(fused - measured))
        results.append({"alpha": round(float(alpha), 2), "resid": resid})
    best = min(results, key=lambda r: r["resid"])
    # 最优 α 判据: 残差曲线拐点处 (残差下降最快后趋平 = 融合收益最大)
    resids = np.array([r["resid"] for r in results])
    deltas = np.abs(np.diff(resids))
    knee = int(np.argmin(deltas)) if len(deltas) else 0
    opt_alpha = float(results[min(knee + 1, len(results) - 1)]["alpha"])
    return {"results": results, "best_alpha": best["alpha"],
            "knee_alpha": opt_alpha,
            "verdict": f"最优 α ≈ {opt_alpha:.1f} (Lissajous 椭圆最扁点)"}


def plot_lissajous(out_png, seed=1, alpha=0.6, phase_lag=0.35):
    """Lissajous 图: 横轴=实测, 纵轴=预测/融合 (α=0 圆, α=0.6 椭圆, α=1 线)"""
    rng = np.random.default_rng(seed)
    t = np.linspace(0, 2 * np.pi, 300)
    measured = np.sin(t) + rng.normal(0, 0.008, size=len(t))
    pred = np.sin(t - phase_lag)
    fused = kalman_fusion(pred, measured, alpha)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import font_manager as _fm
        # 🐛 2026-08-16: matplotlib 新版 addfont 在 font_manager 模块下
        try:
            _fm.fontManager.addfont("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc")
        except Exception:
            try:
                _fm.addfont("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc")
            except Exception:
                pass
        plt.rcParams["font.sans-serif"] = ["WenQuanYi Micro Hei", "Noto Sans CJK SC", "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
        fig, axes = plt.subplots(1, 3, figsize=(14, 4))
        for ax, (a, lbl) in zip(axes, [(0.0, f"α=0 (纯预测: 圆=相位滞后)"),
                                       (alpha, f"α={alpha} (融合: 椭圆)"),
                                       (1.0, "α=1 (纯观测: 线=完全跟随)")]):
            f = kalman_fusion(pred, measured, a)
            ax.scatter(measured, f, s=4, c="#1f6feb", alpha=0.6)
            ax.set_title(lbl, fontsize=10)
            ax.set_xlabel("实测位置 (传感器)")
            ax.set_ylabel("融合/预测位置")
            ax.set_aspect("equal", adjustable="datalim")
            ax.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(out_png, dpi=110)
        plt.close()
        return os.path.basename(out_png)
    except Exception as e:
        return f"plot skipped: {e}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["R", "Q", "alpha", "plot", "all"], default="all")
    args = ap.parse_args()

    out = {"schedule": ALPHA_SCHEDULE}
    if args.stage in ("R", "all"):
        out["calib_R"] = calibrate_R()
        print(f"[R] σ_sensor={out['calib_R']['sigma_sensor']:.4f}  {out['calib_R']['verdict']}")
    if args.stage in ("Q", "all"):
        out["calib_Q"] = calibrate_Q()
        print(f"[Q] 漂移={out['calib_Q']['drift_err_m']:.4f}m  {out['calib_Q']['verdict']}")
    if args.stage in ("alpha", "all"):
        out["alpha_scan"] = scan_alpha()
        print(f"[α] {out['alpha_scan']['verdict']}")
    if args.stage in ("plot", "all"):
        out["lissajous"] = plot_lissajous(os.path.join(REPORTS, "kalman_lissajous.png"))
        print(f"[Lissajous] {out['lissajous']}")

    jpath = os.path.join(REPORTS, "kalman_fusion.json")
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"✅ 报告: {jpath}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
