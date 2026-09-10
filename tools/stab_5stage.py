#!/usr/bin/env python3
"""stab_5stage.py — 5 阶段增益调度的根轨迹图 (2026-08-16 老倪)

画布上 5 阶段 (接近/抓取/抬起/转移/插入) 各有 Kp/Kd → 状态机切换阶段 = 切换增益
= 切换闭环特征根位置。本脚本在 7 轴冗余臂上算每阶段的 14 个根 (7对), 画:
  图1 s平面根分布: 5 阶段 × 14 根 (阶段切换 = 根的位置切换)
  图2 肩关节 j1 根轨迹: Kp 扫描 (增益调度怎么挪根)
  图3 5 阶段 j1 收敛时间常数 τ 对比

增益映射 (画布玩具 ×100 → 7轴臂): 接近(2.0,0.3)→(200,30) 抓取(0.1,0)→(10,0)
抬起(0.8,0)→(80,0) 转移(0.6,0)→(60,0) 插入(2.0,0)→(200,0)
关节固有阻尼 damping=2 (对应 b=2.0) — Kd=0 阶段靠它稳住

用法: /root/gui-venv/bin/python tools/stab_5stage.py
产物: reports/stab_5stage.png + reports/stab_5stage.json
"""
import json
import os
import sys

import numpy as np
import mujoco

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
REPORTS = os.path.join(REPO, "reports")
os.makedirs(REPORTS, exist_ok=True)
XML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seven_dof_arm.xml")

# 5 阶段增益 (画布值 ×100 映射到 7 轴臂; Kd 0 阶段靠关节固有阻尼 b=2 稳住)
STAGES = [
    ("接近", 200.0, 30.0),
    ("抓取", 10.0, 0.0),
    ("抬起", 80.0, 0.0),
    ("转移", 60.0, 0.0),
    ("插入", 200.0, 0.0),
]


def closed_loop_roots(m, d, Kp, Kd, arm_idx=None):
    """闭环线性化特征根: det(M·s² + (Kd)·s + (Kp+Kg)) = 0 → companion 矩阵特征值
    含重力刚度 Kg = ∂G/∂q (有限差分) — 重力会把根往右推 (倒立摆效应)"""
    if arm_idx is None:
        arm_idx = list(range(7))
    d.qvel[:] = 0.0
    mujoco.mj_forward(m, d)
    Mfull = np.zeros((m.nv, m.nv)); mujoco.mj_fullM(m, Mfull, d.qM)
    M = Mfull[np.ix_(arm_idx, arm_idx)]
    # 重力刚度 Kg (有限差分)
    eps = 1e-6
    Kg = np.zeros((7, 7))
    for j in range(7):
        d2 = mujoco.MjData(m); d2.qpos[:] = d.qpos
        d2.qpos[j] += eps; mujoco.mj_forward(m, d2); d2.qvel[:] = 0
        Mj = np.zeros((m.nv, m.nv)); mujoco.mj_fullM(m, Mj, d2.qM)
        G2 = Mj[np.ix_(arm_idx, arm_idx)] @ d2.qacc[arm_idx]
        d2.qpos[j] -= 2 * eps; mujoco.mj_forward(m, d2); d2.qvel[:] = 0
        Mj = np.zeros((m.nv, m.nv)); mujoco.mj_fullM(m, Mj, d2.qM)
        G1 = Mj[np.ix_(arm_idx, arm_idx)] @ d2.qacc[arm_idx]
        Kg[:, j] = (G2 - G1) / (2 * eps)
    Kp_m = np.eye(7) * Kp
    Kd_m = np.eye(7) * Kd + np.diag(m.dof_damping[arm_idx])  # 关节固有阻尼
    A = np.block([[np.zeros((7, 7)), np.eye(7)],
                  [-np.linalg.solve(M, Kp_m + Kg), -np.linalg.solve(M, Kd_m)]])
    return np.linalg.eigvals(A), M, Kg


def main():
    m = mujoco.MjModel.from_xml_path(XML)
    d = mujoco.MjData(m)
    arm_idx = list(range(7))
    colors = ["#b70032", "#6e7681", "#333333", "#9aa4b2", "#000000"]
    markers = ["o", "s", "^", "D", "v"]

    results = {}
    all_roots = {}
    for (name, Kp, Kd), c, mk in zip(STAGES, colors, markers):
        ev, M, Kg = closed_loop_roots(m, d, Kp, Kd, arm_idx)
        all_roots[name] = {"re": ev.real.tolist(), "im": ev.imag.tolist()}
        # 最慢根 (实部最大) = 瓶颈模态
        slowest = ev[np.argmax(ev.real)]
        tau = 1.0 / abs(slowest.real)
        wn = abs(slowest); zeta = -slowest.real / wn
        results[name] = {"Kp": Kp, "Kd": Kd, "slowest_re": float(slowest.real),
                         "slowest_im": float(slowest.imag), "tau_s": float(tau),
                         "zeta": float(zeta), "stable": bool(np.all(ev.real < 0))}
        print(f"{name}: Kp={Kp:5.1f} Kd={Kd:4.1f} | 最慢根 {slowest.real:+.2f}{slowest.imag:+.2f}j"
              f" | τ={tau:.3f}s ζ={zeta:.2f} | {'✅' if results[name]['stable'] else '❌'}")

    # ═══ 绘图 ═══
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager as _fm
    try:
        _fm.fontManager.addfont("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc")
    except Exception:
        pass
    plt.rcParams["font.sans-serif"] = ["WenQuanYi Micro Hei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    fig = plt.figure(figsize=(14, 9))
    gs = fig.add_gridspec(2, 2, width_ratios=[1.4, 1])

    # ── 图1: s 平面根分布 (5 阶段 × 14 根) ──
    ax1 = fig.add_subplot(gs[:, 0])
    for (name, _, _), c, mk in zip(STAGES, colors, markers):
        r = all_roots[name]
        ax1.scatter(r["re"], r["im"], s=28, c=c, marker=mk, label=f"{name}", alpha=0.85, zorder=3)
        ax1.scatter(r["re"], [-x for x in r["im"]], s=28, c=c, marker=mk, alpha=0.35, zorder=2)
    ax1.axvline(0, color="#b70032", ls="--", lw=1)
    ax1.axhline(0, color="#333333", lw=0.6)
    ax1.set_xlabel("实部 σ (rad/s) — 负 = 衰减, 越左越快")
    ax1.set_ylabel("虚部 jω (rad/s) — 非零 = 振荡")
    ax1.set_title("5 阶段增益调度 · 7轴冗余臂 14 个闭环特征根 (s 平面)")
    ax1.legend(fontsize=9, loc="upper right")
    ax1.set_xlim(-50, 5)
    ax1.grid(alpha=0.3, zorder=0)
    # 标注最慢根
    for (name, _, _), c in zip(STAGES, colors):
        r = all_roots[name]
        i = int(np.argmax(r["re"]))
        ax1.annotate(f"{name} 瓶颈 {r['re'][i]:.1f}", (r["re"][i], r["im"][i]),
                     textcoords="offset points", xytext=(6, 6), fontsize=8, color=c)

    # ── 图2: 肩关节 j1 根轨迹 (Kp 扫描) ──
    ax2 = fig.add_subplot(gs[0, 1])
    Kp_scan = np.linspace(20, 500, 30)
    loci = []
    for Kp in Kp_scan:
        ev, _, _ = closed_loop_roots(m, d, Kp, 40.0, arm_idx)
        loci.append(ev)
    loci = np.array(loci)  # (30, 14)
    # 追踪最慢共轭对
    slow_idx = np.argmax(loci[0].real)
    ax2.plot(loci[:, slow_idx].real, loci[:, slow_idx].imag, "-", color="#6e7681", lw=1.5,
             label="j1 肩关节根轨迹 (Kp: 20→500)")
    ax2.plot(loci[:, slow_idx].real, -loci[:, slow_idx].imag, "-", color="#6e7681", lw=1.5)
    # 5 阶段 j1 根标记
    for (name, Kp, Kd), c, mk in zip(STAGES, colors, markers):
        ev, _, _ = closed_loop_roots(m, d, Kp, Kd, arm_idx)
        i = int(np.argmax(ev.real))
        ax2.scatter(ev.real[i], ev.imag[i], s=60, c=c, marker=mk, zorder=5)
        ax2.annotate(name, (ev.real[i], ev.imag[i]), textcoords="offset points",
                     xytext=(8, 6), fontsize=8, color=c)
    ax2.axvline(0, color="#b70032", ls="--", lw=1)
    ax2.axhline(0, color="#333333", lw=0.6)
    ax2.set_xlabel("实部 σ")
    ax2.set_ylabel("虚部 jω")
    ax2.set_title("肩关节 j1 根轨迹 · 增益调度 (Kp 20→500, Kd=40)")
    ax2.legend(fontsize=8)
    ax2.set_xlim(-30, 5)
    ax2.grid(alpha=0.3)

    # ── 图3: 5 阶段收敛时间 τ 对比 ──
    ax3 = fig.add_subplot(gs[1, 1])
    names = [n for n, _, _ in STAGES]
    taus = [results[n]["tau_s"] for n in names]
    cols = [c for c, _ in zip(colors, markers)]
    bars = ax3.bar(names, taus, color=cols, alpha=0.85)
    for b, t in zip(bars, taus):
        ax3.text(b.get_x() + b.get_width() / 2, t * 1.03, f"{t:.3f}s",
                 ha="center", fontsize=9)
    ax3.set_ylabel("瓶颈模态时间常数 τ (s) — 越小越快")
    ax3.set_title("5 阶段收敛速度 (最慢根决定)")
    ax3.grid(alpha=0.3, axis="y")

    plt.tight_layout()
    png = os.path.join(REPORTS, "stab_5stage.png")
    plt.savefig(png, dpi=110)
    print(f"\n✅ 图: {png}")

    with open(os.path.join(REPORTS, "stab_5stage.json"), "w", encoding="utf-8") as f:
        json.dump({"stages": results, "roots": all_roots}, f, ensure_ascii=False, indent=2)
    print(f"✅ 报告: {REPORTS}/stab_5stage.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
