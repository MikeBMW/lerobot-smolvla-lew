#!/usr/bin/env python3
"""📊 状态空间工程图生成 (2026-08-12 老倪) — matplotlib 三图:
图1 GRU 极点图 (Z 平面单位圆): 右脑潜状态特征值 → 收敛判定
图2 误差衰减曲线 (临界阻尼): 状态机误差 e(t) 多增益对比
图3 潜空间流形轨迹 (PCA 降维): 右脑预测链 2D 轨迹 + contact 着色

用法: BRAIN_CKPT=<dir> .venv/bin/python tools/plot_state_space.py
输出: reports/eval_gru_poles.png / eval_error_decay.png / eval_latent_traj.png
"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import numpy as np
import torch
import matplotlib
matplotlib.use("Agg")  # 无头模式
import matplotlib.pyplot as plt

from gen_insert_video import _load_brain
from train_full_pipeline import (make_env, get_obs, ST_APPROACH, ST_GRASP, ST_LIFT,
                                 ST_TRANSFER, ST_INSERT, ST_DONE, ST_NAMES)

# 🐛 2026-08-12 老倪: 图中文乱码 — matplotlib 未注册 WenQuanYi, 用已识别的 Noto Sans CJK SC
try:
    from matplotlib import font_manager as _fm
    _fm.addfont("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc")  # 优先 wqy (TrueType)
except Exception:
    pass
plt.rcParams["font.sans-serif"] = ["WenQuanYi Micro Hei", "Noto Sans CJK SC", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def plot_gru_poles(right, out_png):
    """图1: 潜状态特征值 Z 平面 (单位圆内 = 收敛稳定)
    🐛 2026-08-12: 右脑实际是 MLP (enc/pred_next/contact_head, 无 GRU 层)
    → 用 enc 隐层方阵 (256×256) 作为等效状态转移矩阵"""
    w_hh = None
    for name, m in right.named_modules():
        if hasattr(m, "weight") and m.weight is not None and m.weight.dim() == 2 \
                and m.weight.shape[0] == m.weight.shape[1]:
            w_hh = m.weight.detach().cpu().numpy()
            break
    if w_hh is None:
        mats = [mm.weight.detach().cpu().numpy() for mm in right.modules()
                if hasattr(mm, "weight") and mm.weight is not None and mm.weight.dim() == 2]
        w_hh = mats[0] if mats else np.eye(4)
    eig = np.linalg.eigvals(w_hh)
    fig, ax = plt.subplots(figsize=(5.2, 5.2))
    theta = np.linspace(0, 2 * np.pi, 200)
    ax.plot(np.cos(theta), np.sin(theta), "k--", lw=1, label="单位圆 (|λ|=1)")
    inside = np.abs(eig) < 1
    ax.scatter(eig[inside].real, eig[inside].imag, c="#3fb950", s=42, label="稳定极点 (|λ|<1)")
    ax.scatter(eig[~inside].real, eig[~inside].imag, c="#ff4444", s=60, marker="x",
               label="不稳定极点 (|λ|≥1)")
    ax.axhline(0, color="#9aa4b2", lw=0.5)
    ax.axvline(0, color="#9aa4b2", lw=0.5)
    ax.set_title(f"右脑 GRU 特征值分布 (Z 平面) · n={len(eig)} · ρ={np.max(np.abs(eig)):.4f}")
    ax.set_xlabel("Re")
    ax.set_ylabel("Im")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    ax.axis("equal")
    fig.tight_layout()
    fig.savefig(out_png, dpi=110)
    plt.close(fig)
    return float(np.max(np.abs(eig))), int(np.sum(inside)), len(eig)


def _rollout_error_curve(left, right, xm, xs, ym, ys, gain, seed=1, max_steps=200):
    """跑一次插拔, 记录接近阶段误差 e=||hand-光模块|| 序列 (状态机增益可调)"""
    dev = next(left.parameters()).device
    env = make_env(seed)
    o = get_obs(env)
    peg_z0 = env.data.site_xpos[env.model.site("pegGrasp").id][2]
    hole = env.data.site_xpos[env.model.site("hole").id]
    state = ST_APPROACH
    errs = []
    for step in range(max_steps):
        hand = env.data.site_xpos[env.model.site("endEffector").id]
        peg = env.data.site_xpos[env.model.site("pegGrasp").id]
        d_hp = float(np.linalg.norm(hand - peg))
        d_ph = float(np.linalg.norm(peg - hole))
        xin = torch.from_numpy((o - xm) / xs).float().to(dev)
        with torch.no_grad():
            pred = left(xin.unsqueeze(0)).squeeze(0).cpu().numpy()
        act = pred * ys + ym
        with torch.no_grad():
            _, pred_cont = right(xin.unsqueeze(0),
                                 torch.from_numpy(act).float().to(dev).unsqueeze(0))
        contact = pred_cont.item()
        if state == ST_APPROACH:
            if d_hp < 0.06 and contact > 0.5:
                state = ST_GRASP
        elif state == ST_GRASP:
            if peg[2] - peg_z0 > 0.02:
                state = ST_LIFT
        elif state == ST_LIFT:
            if peg[2] > peg_z0 + 0.08:
                state = ST_TRANSFER
        elif state == ST_TRANSFER:
            if abs(peg[0] - hole[0]) < 0.05 and abs(peg[1] - hole[1]) < 0.05:
                state = ST_INSERT
        elif state == ST_INSERT:
            if d_ph < 0.05:
                state = ST_DONE
        if state == ST_APPROACH:
            errs.append(d_hp)
            delta = peg - hand
            act[:3] = act[:3] * 0.3 + np.clip(delta * gain, -1, 1)
            act[3] = -1.0
        elif state == ST_GRASP:
            act[:3] = act[:3] * 0.1
            act[3] = 0.6
        elif state == ST_LIFT:
            act[:3] = [0, 0, 0.8]
            act[3] = 0.6
        elif state == ST_TRANSFER:
            d_xy = np.array([hole[0] - peg[0], hole[1] - peg[1]])
            if np.linalg.norm(d_xy) > 1e-4:
                act[:3] = np.clip((d_xy / np.linalg.norm(d_xy)) * 0.6, -1, 1).tolist() + [0.0]
            act[3] = 0.6
        elif state == ST_INSERT:
            act[:3] = [0, 0, np.clip((hole[2] - peg[2]) * 2.0, -0.6, 0.6)]
            act[3] = 0.6
        else:
            act[:3] = [0, 0, 0]
            act[3] = 0.6
        _mx = float(np.abs(act).max()) if len(act) else 1.0
        if _mx > 1.0:
            act = act / _mx
        try:
            env.step(np.clip(act, -1, 1))
            env.render()
        except Exception:
            break
        o = get_obs(env)
        if state != ST_APPROACH:
            break
    env.close()
    return np.asarray(errs)


def plot_error_decay(left, right, xm, xs, ym, ys, out_png):
    """图2: 状态机误差衰减曲线 (多增益对比 → 临界阻尼判定)"""
    fig, ax = plt.subplots(figsize=(7, 4.2))
    colors = {"0.5": "#58a6ff", "1.0": "#d29922", "2.0": "#3fb950", "3.0": "#ff4444"}
    for g in (0.5, 1.0, 2.0, 3.0):
        e = _rollout_error_curve(left, right, xm, xs, ym, ys, gain=g)
        if len(e) > 1:
            ax.plot(e, color=colors[str(g)], lw=1.8,
                    label=f"增益 K={g} (e0={e[0]:.3f}→e_end={e[-1]:.4f})")
    ax.axhline(0.06, color="#57606a", ls=":", lw=1, label="抓取阈值 0.06m")
    ax.set_title("状态机误差衰减 e(t)=||hand−peg|| (根轨迹等效图)")
    ax.set_xlabel("仿真步数 t")
    ax.set_ylabel("误差 e(t) [m]")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_png, dpi=110)
    plt.close(fig)


def plot_latent_trajectory(left, right, xm, xs, ym, ys, out_png, seed=1, n_steps=40):
    """图3: 潜空间流形轨迹 (右脑预测链 PCA 降维 2D + contact 着色)"""
    dev = next(left.parameters()).device
    env = make_env(seed)
    o = get_obs(env)
    obs_seq, con_seq = [], []
    for _ in range(n_steps):
        xin = torch.from_numpy((o - xm) / xs).float().to(dev)
        with torch.no_grad():
            a = left(xin.unsqueeze(0)).cpu().numpy()[0] * ys + ym
            nxt, cont = right(xin.unsqueeze(0),
                              torch.from_numpy(a).float().to(dev).unsqueeze(0))
        obs_seq.append((o - xm) / xs)
        con_seq.append(float(cont.cpu().numpy()[0][0] if hasattr(cont, "cpu") else cont.item()))
        o = nxt.cpu().numpy()[0]
    env.close()
    X = np.asarray(obs_seq)
    mu = X.mean(axis=0)
    Xc = X - mu
    cov = Xc.T @ Xc / len(X)
    evals, evecs = np.linalg.eigh(cov)
    W = evecs[:, -2:]  # 前 2 主成分
    P = Xc @ W
    fig, ax = plt.subplots(figsize=(6.4, 5))
    sc = ax.scatter(P[:, 0], P[:, 1], c=con_seq, cmap="RdYlGn", s=46,
                    edgecolors="#0a0e14", lw=0.6)
    ax.plot(P[:, 0], P[:, 1], color="#9aa4b2", lw=1, alpha=0.6)
    ax.scatter(P[0, 0], P[0, 1], marker="o", c="none", edgecolors="#58a6ff", s=140,
               label="起点 (obs_0)")
    ax.scatter(P[-1, 0], P[-1, 1], marker="*", c="#ffd700", s=160,
               label="终点 (pred_obs_n)")
    cb = fig.colorbar(sc, ax=ax)
    cb.set_label("contact 概率")
    ax.set_title(f"右脑潜空间流形轨迹 (PCA 2D, {n_steps} 步预测链)")
    ax.set_xlabel("PC1")
    ax.set_ylabel("PC2")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_png, dpi=110)
    plt.close(fig)


def main():
    left, right, xm, xs, ym, ys = _load_brain()
    out1 = os.path.join(ROOT, "reports", "eval_gru_poles.png")
    out2 = os.path.join(ROOT, "reports", "eval_error_decay.png")
    out3 = os.path.join(ROOT, "reports", "eval_latent_traj.png")
    print("📊 图1: GRU 极点图 (Z 平面)…", flush=True)
    rho, n_in, n = plot_gru_poles(right, out1)
    print(f"   ρ={rho:.4f} 圆内 {n_in}/{n} → {out1}", flush=True)
    print("📊 图2: 误差衰减曲线 (临界阻尼)…", flush=True)
    plot_error_decay(left, right, xm, xs, ym, ys, out2)
    print(f"   → {out2}", flush=True)
    print("📊 图3: 潜空间流形轨迹 (PCA)…", flush=True)
    plot_latent_trajectory(left, right, xm, xs, ym, ys, out3)
    print(f"   → {out3}", flush=True)
    print("✅ 三张工程图完成", flush=True)


if __name__ == "__main__":
    main()
