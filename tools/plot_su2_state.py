#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""plot_su2_state.py — SU(2) 统一状态空间 工程图 (真实引擎轨迹数据, 无编造)

跑法: gui-venv311/bin/python tools/plot_su2_state.py
输入: reports/su2_state_report.json (由 tools/ss_su2_verify.py 生成)
输出 (reports/):
  su2_bloch.png        ① Bloch 球轨迹 (按阶段着色) + 末帧各层/场景态
  su2_converge.png     ② 收敛曲线 θ(t) / |w|(t) + 层 θ(t)
  su2_layers.png       ③ 末帧层贡献(反演剥离) + 层间不可交换性 + FS 距离矩阵
  su2_node_map.png     ④ 节点映射 (17 节点 θ/方向) 全景
"""
import json
import os

import matplotlib
matplotlib.use("Agg")
import numpy as np                                                     # noqa: E402
from matplotlib import font_manager as _fm                             # noqa: E402
import matplotlib.pyplot as plt                                        # noqa: E402

# 中文: matplotlib 字体缓存常缺 wqy → 显式 addfont (与既有工程图同源坑)
for _p in ("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
           "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"):
    try:
        _fm.fontManager.addfont(_p)
    except Exception:
        pass
matplotlib.rcParams["font.sans-serif"] = ["WenQuanYi Micro Hei", "Noto Sans CJK SC", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REP = os.path.join(REPO, "reports", "su2_state_report.json")
OUT = os.path.join(REPO, "reports")


def load():
    with open(REP, encoding="utf-8") as f:
        return json.load(f)


def fig_bloch(rep):
    """① Bloch 球: 群元素在 S² 上的轨迹 + 各层/场景当前点"""
    tr = rep["engine_trace"]["bloch_series"]
    tr = np.asarray([p for p in tr if p and len(p) == 3], dtype=float)
    und = rep.get("understand_last", {})
    lay = und.get("layer_peel", {})
    fig = plt.figure(figsize=(11, 5.2))
    for k, (elev, azim, ttl) in enumerate([(22, 35, "视角 A"), (-25, 125, "视角 B")]):
        ax = fig.add_subplot(1, 2, k + 1, projection="3d")
        u, v = np.mgrid[0:2 * np.pi:40j, 0:np.pi:20j]
        ax.plot_wireframe(np.cos(u) * np.sin(v), np.sin(u) * np.sin(v), np.cos(v),
                          color="#cfcfcf", linewidth=0.35, alpha=0.5)
        ax.plot([-1, 1], [0, 0], [0, 0], color="#999", lw=0.7)
        ax.plot([0, 0], [-1, 1], [0, 0], color="#999", lw=0.7)
        ax.plot([0, 0], [0, 0], [-1, 1], color="#999", lw=0.7)
        ax.plot(tr[:, 0], tr[:, 1], tr[:, 2], color="#2b6da3", lw=1.4,
                label="引擎轨迹 %d 帧" % len(tr))
        ax.scatter(tr[0, 0], tr[0, 1], tr[0, 2], color="#777", s=26, label="起始")
        ax.scatter(tr[-1, 0], tr[-1, 1], tr[-1, 2], color="#3fb950", s=46, label="末帧 U_scene")
        for name, d in (und.get("layer_peel") or {}).items():
            if name.startswith("_"):
                continue
            ax_ = d.get("layer_axis")
            th = d.get("layer_theta", 0.0)
            if not ax_ or th <= 1e-9:
                continue
            a = np.asarray(ax_, dtype=float)
            n = np.linalg.norm(a)
            if n < 1e-9:
                continue
            # 层元素在 Bloch 球上的像 (由轴角算 r = 像点)
            import math
            nx = a / n
            ct, st = math.cos(th / 2), math.sin(th / 2)
            w, x, y, z = ct, st * nx[0], st * nx[1], st * nx[2]
            r = np.array([2 * (w * y - z * x), 2 * (w * x + z * y), w * w + z * z - x * x - y * y])
            ax.scatter(r[0], r[1], r[2], s=34, label="%s θ=%.2f" % (name, th))
        ax.set_title("SU(2) 统一状态 Bloch 球 (%s)\n左乘逆元剥离=层贡献, 群恒等元⇔收敛(北极|0⟩)"
                     % ttl, fontsize=10)
        ax.set_xlabel("r_x"); ax.set_ylabel("r_y"); ax.set_zlabel("r_z")
        ax.legend(fontsize=8, loc="upper left")
        ax.view_init(elev=elev, azim=azim)
    p = os.path.join(OUT, "su2_bloch.png")
    fig.tight_layout(); fig.savefig(p, dpi=130); plt.close(fig)
    return p


def fig_converge(rep):
    """② 收敛曲线: θ(t) 与 |w|(t) (引擎逐帧真实值)"""
    tr = rep["engine_trace"]
    th = np.asarray(tr["theta_series"], dtype=float)
    # |w| = cos(θ/2) 由实测 θ 反算 (群几何关系, 二者严格一致)
    w = np.cos(th / 2)
    fig, ax = plt.subplots(1, 2, figsize=(11, 4))
    ax[0].plot(th, color="#2b6da3", lw=1.4)
    ax[0].set_title("偏离角 θ(t) — 场景态离参考态的角度\n末帧 θ=%.4f rad (%.1f°)"
                    % (th[-1], np.degrees(th[-1])), fontsize=10)
    ax[0].set_xlabel("引擎步"); ax[0].set_ylabel("θ (rad)"); ax[0].grid(alpha=0.3)
    ax[1].plot(w, color="#3fb950", lw=1.4)
    ax[1].set_title("收敛度 |w|(t) = cos(θ/2) — 1 ⇔ 群恒等元(任务完成)\n末帧 |w|=%.4f" % w[-1],
                    fontsize=10)
    ax[1].set_xlabel("引擎步"); ax[1].set_ylabel("|w|"); ax[1].set_ylim(0, 1.05); ax[1].grid(alpha=0.3)
    p = os.path.join(OUT, "su2_converge.png")
    fig.tight_layout(); fig.savefig(p, dpi=130); plt.close(fig)
    return p


def fig_layers(rep):
    """③ 层贡献(反演剥离) + 不可交换性 + FS 距离矩阵"""
    und = rep.get("understand_last", {})
    peel = und.get("layer_peel", {})
    ks = [k for k in ("L2", "L3", "L4", "L5") if k in peel]
    comm = und.get("noncommutativity", {})
    fs = und.get("layer_distance", {})
    fig = plt.figure(figsize=(12, 4.2))

    ax = fig.add_subplot(1, 3, 1)
    ax.bar(ks, [peel[k]["layer_theta"] for k in ks], color="#5b7fa6")
    ax2 = ax.twinx()
    ax2.plot(ks, [peel[k]["delta_theta"] for k in ks], "o-", color="#c0703c")
    ax2.set_ylabel("剥离后 Δθ (该层贡献)", fontsize=9)
    ax.set_title("层贡献: 层的 θ 与反演剥离 Δθ\n(全剥离残余 θ=%.2e)"
                 % peel.get("_residual", {}).get("theta", 0.0), fontsize=10)
    ax.set_ylabel("层的 θ (rad)", fontsize=9); ax.grid(alpha=0.3)

    ax = fig.add_subplot(1, 3, 2)
    M = np.array([[comm.get("%s|%s" % (a, b), 0.0) for b in ks] for a in ks])
    im = ax.imshow(M, cmap="Greys", vmin=0, vmax=max(1e-9, M.max()))
    ax.set_xticks(range(len(ks))); ax.set_xticklabels(ks)
    ax.set_yticks(range(len(ks))); ax.set_yticklabels(ks)
    for i in range(len(ks)):
        for j in range(len(ks)):
            ax.text(j, i, "%.3f" % M[i, j], ha="center", va="center", fontsize=8,
                    color="white" if M[i, j] > 0.6 * max(1e-9, M.max()) else "black")
    ax.set_title("层间不可交换性 ‖[U_i,U_j]‖₂\n(值大=两层强耦合, 群非阿贝尔)", fontsize=10)
    fig.colorbar(im, ax=ax, fraction=0.046)

    ax = fig.add_subplot(1, 3, 3)
    F = np.array([[fs.get("%s|%s" % (a, b), 0.0) for b in ks] for a in ks])
    im = ax.imshow(F, cmap="Blues", vmin=0, vmax=max(1e-9, F.max()))
    ax.set_xticks(range(len(ks))); ax.set_xticklabels(ks)
    ax.set_yticks(range(len(ks))); ax.set_yticklabels(ks)
    for i in range(len(ks)):
        for j in range(len(ks)):
            ax.text(j, i, "%.3f" % F[i, j], ha="center", va="center", fontsize=8,
                    color="white" if F[i, j] > 0.6 * max(1e-9, F.max()) else "black")
    ax.set_title("Fubini–Study 层间距离\narccos|⟨U_i,U_j⟩| (层几何关系)", fontsize=10)
    fig.colorbar(im, ax=ax, fraction=0.046)
    p = os.path.join(OUT, "su2_layers.png")
    fig.tight_layout(); fig.savefig(p, dpi=130); plt.close(fig)
    return p


def fig_node_map(rep):
    """④ 节点映射全景: 每个节点的数据 → 群元素 (θ 与方向分量)"""
    nm = rep.get("node_mapping", {})
    nodes = nm.get("nodes", {})
    names = list(nodes.keys())
    th = [nodes[k]["theta"] for k in names]
    ax_ = np.array([nodes[k]["axis"] for k in names], dtype=float)
    fig, ax = plt.subplots(figsize=(12, 4.6))
    idx = np.arange(len(names))
    ax.bar(idx - 0.22, th, width=0.22, label="θ (rad)", color="#5b7fa6")
    for j, lab in enumerate("xyz"):
        ax.bar(idx + 0.02 + j * 0.22, ax_[:, j] * 1.5, width=0.2,
               label="n̂_%s ×1.5" % lab, color=["#c0703c", "#7a9e6a", "#8a7fae"][j])
    ax.set_xticks(idx)
    ax.set_xticklabels([n.split(" ")[-1] if " " in n else n for n in names], rotation=32,
                       ha="right", fontsize=8)
    ax.set_ylabel("rad / 无量纲")
    ax.set_title("SU(2) 节点映射全景 — %d 个画布节点的数据各自映成群元素\n"
                 "(有界映射律 ω=π·tanh(g‖v‖)v̂: θ<π 不绕圈; 无数值输出者=单位元, 已在报告标注)"
                 % len(names), fontsize=10)
    ax.legend(fontsize=8); ax.grid(alpha=0.3, axis="y")
    p = os.path.join(OUT, "su2_node_map.png")
    fig.tight_layout(); fig.savefig(p, dpi=130); plt.close(fig)
    return p


def main():
    rep = load()
    for fn in (fig_bloch, fig_converge, fig_layers, fig_node_map):
        p = fn(rep)
        print("✅ %s (%d bytes)" % (p, os.path.getsize(p)))
    print("群公理 all_ok =", rep["group_axioms"]["all_ok"],
          "| 引擎步数 =", rep["engine_trace"]["n_steps"])


if __name__ == "__main__":
    main()
