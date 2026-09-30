#!/usr/bin/env python3
"""cerebellum_calib.py — 左脑·小脑的标定参数设计 (2026-08-16 老倪)

工程标定 ≠ 调权重: 左脑是固定 .pt 权重文件, 工程师用三个「数据/执行」旋钮标定:

  Step1 感知零偏标定 (归一化参数): 静止记录 obs → 新 x_mean; 满行程记录 → x_std
        物理含义: 校准零点 — 光模块换位置不改权重, 只更新 x_mean 参考坐标 → 输出整体平移
  Step2 执行力标定 (状态机限幅/偏置): act[:3] = act*act_gain + clip(delta*err_gain)
        act_gain = 肌肉记忆占比 (MLP 主导作用), err_gain = 误差纠正力度
        物理含义: 限位器 — 重物体调小 err_gain 防过冲 / 调大 act_gain 让 MLP 主导
  Step3 现场微调 (Fine-tune): 采集 20-30 条示教 → 4090 微调 5 分钟 → 热加载 .pt
        工程类比: 小脑急性手术, 换新肌肉记忆模板

生物标定 (攀缘纤维→LTD→gate):
  平行纤维(上下文) = 左脑 MLP 输出
  攀缘纤维(误差信号) = 右脑 contact + 实际力传感器对比 (大误差=复杂脉冲)
  长时程抑制 LTD = 状态机 gate 系数 (1.0/0.1/0.01): 左脑不准 → 瞬间降 gate 压制
  恢复期 = 状态机切阶段, gate 恢复, 左脑继续主导

用法 (gui-venv 跑, 需 numpy/matplotlib):
    python3 tools/cerebellum_calib.py              # 三件套 + gate 仿真 + 图
    python3 tools/cerebellum_calib.py --stage bias  # 单跑一步
产物: reports/cerebellum_calib.json + reports/cerebellum_gate.png
"""
import argparse
import json
import os
import sys

import numpy as np

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
REPORTS = os.path.join(REPO, "reports")
os.makedirs(REPORTS, exist_ok=True)

# 默认左脑标定参数 (与 modeling_left_right.py _act_state_machine 一致)
DEFAULTS = {
    "act_gain": 0.3,    # 肌肉记忆占比 (MLP 主导作用) — act[:3]*0.3
    "err_gain": 2.0,    # 误差纠正力度 — clip(delta*2.0, -1, 1)
    "gate": 1.0,        # 突触抑制系数 (LTD): 1.0 全开 / 0.1 压制 / 0.01 移交传感器
    "gate_th": 2.0,     # 接触力误差阈值 (N) — 超过即触发 gate 降低
    "gate_min": 0.1,    # gate 最低值 (最大抑制)
    "x_mean": 0.0,      # 感知零偏 (归一化均值)
    "x_std": 1.0,       # 感知尺度 (归一化标准差)
}


def calib_bias(seed=1, n=500, shift=0.05):
    """Step1 感知零偏标定: 机器人静止在标准位, 记录 obs → 新 x_mean (校准零点).
    新场景光模块位置偏移 → 只更新 x_mean 参考坐标, 不碰权重.
    返回: 旧/新 x_mean, 输出平移量 (应 ≈ 位置偏移).
    """
    rng = np.random.default_rng(seed)
    obs_std = rng.normal(0, 0.01, size=n)          # 标准位静止观测
    x_mean_new = float(np.mean(obs_std))           # 新零点
    # 位置偏移 shift 后, 输出应整体平移 ≈ shift
    out_shift = float(shift)                       # 理想: 平移量 = 位置偏移
    return {"x_mean_old": 0.0, "x_mean_new": round(x_mean_new, 4),
            "position_shift": shift, "out_shift": out_shift,
            "verdict": f"更新 x_mean={x_mean_new:.4f} → 输出平移 {out_shift:.3f} (等效重标定, 不重训)"}


def calib_exec(seed=1, overshoot_true=0.25):
    """Step2 执行力标定: 扫描 (act_gain, err_gain) 网格 → 过冲率/收敛步数.
    重物体 → 调小 err_gain 防过冲; 要 MLP 主导 → 调大 act_gain.
    返回: 推荐参数 + 网格 (供 Lissajous 式可视化).
    """
    rng = np.random.default_rng(seed)
    grid = []
    for ag in (0.1, 0.3, 0.5, 0.8):
        for eg in (0.5, 1.0, 2.0, 3.0):
            # 简化二阶响应: 过冲随 err_gain 增大而增大, 收敛随 act_gain 增大而变快
            overshoot = overshoot_true * (eg / 2.0) * (1.0 - 0.3 * ag)
            converge = max(5, int(60 / (0.5 + ag) - 15 * eg * 0.05))
            grid.append({"act_gain": ag, "err_gain": eg,
                         "overshoot": round(float(overshoot), 3),
                         "converge_steps": max(5, int(converge))})
    # 推荐: 过冲 < 0.2 且收敛最快
    ok = [g for g in grid if g["overshoot"] < 0.2]
    best = min(ok, key=lambda g: g["converge_steps"]) if ok else min(grid, key=lambda g: g["overshoot"])
    return {"grid": grid, "recommend": best,
            "verdict": f"推荐 act_gain={best['act_gain']} err_gain={best['err_gain']} (过冲{best['overshoot']:.2f} 收敛{best['converge_steps']}步)"}


def calib_gate(seed=1):
    """Step3 gate (LTD) 仿真: 接触力误差 → gate 响应.
    平行纤维=MLP输出, 攀缘纤维=力传感器误差, LTD=gate 降低.
    误差超 gate_th → gate 从 1.0 降到 gate_min (0.1), 控制权移交传感器.
    恢复: 误差回落 → 阶段切换 → gate 恢复 1.0.
    """
    rng = np.random.default_rng(seed)
    t = np.linspace(0, 6.0, 300)
    force_err = 0.5 + 4.0 * np.exp(-((t - 3.0) ** 2) / 0.4)  # 3s 处接触力误差尖峰
    gate = np.ones_like(t)
    th, gmin = DEFAULTS["gate_th"], DEFAULTS["gate_min"]
    for i, e in enumerate(force_err):
        if e > th:
            gate[i] = gmin                       # LTD: 误差超阈值 → 瞬间压制
        else:
            gate[i] = 1.0                        # 恢复期: 误差回落 → gate 恢复
    # 平滑过渡 (实际状态机是离散切换, 这里取每步稳态)
    n_ltd = int(np.sum(force_err > th))
    return {"gate_th": th, "gate_min": gmin, "ltd_triggers": n_ltd,
            "peak_err": round(float(force_err.max()), 2),
            "verdict": f"接触力误差峰值 {force_err.max():.1f}N > 阈值 {th}N → gate 压至 {gmin} ({n_ltd} 步抑制, 控制权移交传感器)"}


def plot_gate(out_png, seed=1):
    """gate (LTD) 响应图: 上=接触力误差, 下=gate 系数 (误差尖峰→gate 骤降→恢复)"""
    rng = np.random.default_rng(seed)
    t = np.linspace(0, 6.0, 300)
    force_err = 0.5 + 4.0 * np.exp(-((t - 3.0) ** 2) / 0.4)
    th, gmin = DEFAULTS["gate_th"], DEFAULTS["gate_min"]
    gate = np.where(force_err > th, gmin, 1.0)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import font_manager as _fm
        try:
            _fm.fontManager.addfont("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc")
        except Exception:
            try:
                _fm.addfont("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc")
            except Exception:
                pass
        plt.rcParams["font.sans-serif"] = ["WenQuanYi Micro Hei", "Noto Sans CJK SC", "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 6), sharex=True)
        ax1.plot(t, force_err, color="#f85149", lw=2)
        ax1.axhline(th, color="#d29922", ls="--", lw=1, label=f"误差阈值 {th}N")
        ax1.set_ylabel("接触力误差 (N)")
        ax1.set_title("攀缘纤维 · 误差信号 → 长时程抑制 (LTD)", fontsize=11)
        ax1.legend(); ax1.grid(alpha=0.3)
        ax2.plot(t, gate, color="#3fb950", lw=2)
        ax2.axhline(gmin, color="#d29922", ls="--", lw=1, label=f"gate_min {gmin}")
        ax2.set_ylabel("gate 系数 (LTD)")
        ax2.set_xlabel("时间 (s)")
        ax2.set_ylim(-0.1, 1.2)
        ax2.legend(); ax2.grid(alpha=0.3)
        plt.tight_layout()
        plt.savefig(out_png, dpi=110)
        plt.close()
        return os.path.basename(out_png)
    except Exception as e:
        return f"plot skipped: {e}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["bias", "exec", "gate", "plot", "all"], default="all")
    args = ap.parse_args()
    out = {"defaults": DEFAULTS}
    if args.stage in ("bias", "all"):
        out["calib_bias"] = calib_bias()
        print(f"[零偏] {out['calib_bias']['verdict']}")
    if args.stage in ("exec", "all"):
        out["calib_exec"] = calib_exec()
        print(f"[执行力] {out['calib_exec']['verdict']}")
    if args.stage in ("gate", "all"):
        out["calib_gate"] = calib_gate()
        print(f"[gate/LTD] {out['calib_gate']['verdict']}")
    if args.stage in ("plot", "all"):
        out["gate_plot"] = plot_gate(os.path.join(REPORTS, "cerebellum_gate.png"))
        print(f"[图] {out['gate_plot']}")
    jpath = os.path.join(REPORTS, "cerebellum_calib.json")
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"✅ 报告: {jpath}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
