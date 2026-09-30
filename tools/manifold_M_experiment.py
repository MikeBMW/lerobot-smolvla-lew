#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧮 manifold_M_experiment.py — 主标定参数 M 的数值小实验 (零回归 + 惯性真的生效)

老倪 2026-09-29 口径: 质量=结构的副产物/等效惯量; a = F/M ⇒ Δx = F·dt²/M 是有惯性的二阶形式;
M→0 或显式关闭惯性 ⇒ 必须退化回原来的**过阻尼(一阶梯度)**行为 (速度 ∝ 力)。

本实验 = 三件证据 (同一起点/同一场):
  ① **零回归**: inertia 关闭 (默认) 时, 引擎演化与**旧行为**(直接 navigator.step(p, −∇Φ, dt))
     逐位相同 (np.array_equal, 多步轨迹)。
  ② **惯性生效**: inertia=True 且 M>0 时 —— 首步位移 = |F|·dt²/M (二阶), 与一阶 |F|·dt 不同;
     **场反转后位置仍沿原方向继续走 (动量)** —— 一阶会立刻反向。
  ③ **默认不变**: 不传 M/inertia 构造的引擎 == 旧行为。

用法: ./gui-venv311/bin/python tools/manifold_M_experiment.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENG = os.path.join(ROOT, "src", "lerobot", "manifold", "manifold_engine.py")


def load_engine_mod():
    spec = importlib.util.spec_from_file_location("lerobot.manifold.manifold_engine", ENG)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main() -> int:
    m = load_engine_mod()
    ME = m.ManifoldEngine
    spec = m.manifold_M_spec()
    print("=" * 78)
    print("🧮 主标定参数 M 数值小实验 — 零回归 + 惯性生效 (同一起点/同一场)")
    print("=" * 78)
    print("  M 规格:", json.dumps({k: spec[k] for k in
                                ("default", "range", "unit", "overdamped", "zero_regression")},
                               ensure_ascii=False))
    ok_all = True

    # ── 单步: 一阶 vs 二阶 (首步位移 = |F|·dt²/M) ──────────────────────────────
    p0, F, dt = np.array([0.0, 0.0]), np.array([1.0, 0.0]), 0.01
    print("\n① 单步位移 (F=[1,0], dt=0.01, p0=[0,0]):")
    rows = []
    e_old = ME(manifold_type="euclidean", latent_dim=2, state_dim=2, action_dim=2)
    p_old = e_old._evolve(p0, F, dt)                       # inertia 默认关 → 旧行为
    ref = e_old.navigator.step(p0, F, dt)                  # 独立的“旧行为”参考 (未改的 navigator)
    same0 = np.array_equal(np.asarray(p_old), np.asarray(ref))
    ok_all &= bool(same0)
    print(f"   M=关 (inertia=False, 默认)  Δx={p_old}   旧行为参考 Δx={ref}  逐位相同={same0}")
    for M in (0.5, 1.0, 2.0, 4.0):
        e = ME(manifold_type="euclidean", latent_dim=2, state_dim=2, action_dim=2,
               manifold_M=M, inertia=True)
        pn = e._evolve(p0, F, dt)
        v = e.velocity
        rows.append((M, pn[0], float(np.linalg.norm(v))))
        print(f"   M={M:<3} (inertia=True)     Δx={np.round(pn,6)}  (期望 |F|·dt²/M="
              f"{1.0*dt*dt/M:.6f})  动量 v={np.round(v,6)}")
    # M→0 极限必须 = 过阻尼 (零回归)
    e0 = ME(manifold_type="euclidean", latent_dim=2, state_dim=2, action_dim=2,
            manifold_M=0.0, inertia=True)
    p_zero = e0._evolve(p0, F, dt)
    same_zero = np.array_equal(np.asarray(p_zero), np.asarray(ref))
    ok_all &= bool(same_zero)
    print(f"   M=0  (inertia=True, 无惯性极限)  Δx={p_zero}  与旧行为逐位相同={same_zero}")

    # ── 多步零回归: 引擎 step() 轨迹 vs 手写旧公式 ────────────────────────────
    def make_engine(mode):
        e = ME(manifold_type="euclidean", latent_dim=2, state_dim=2, action_dim=2,
               manifold_M=(1.0 if mode == "M1" else 0.0),
               inertia=(mode != "old"))
        e.fitted = True
        e.encoder.latent_dim = 2
        go = np.array([1.0, 0.0])
        e.goal_point = go
        e.current_manifold_point = np.zeros(2)
        return e, go

    def run_engine(mode, n=30):
        e, go = make_engine(mode)
        phi = lambda q: 0.5 * float(np.dot(np.asarray(q, float) - go, np.asarray(q, float) - go))
        p = np.zeros(2)
        traj = [p.copy()]
        for _ in range(n):
            g = e.metric.tangent_gradient(phi, p)
            p = e._evolve(p, -g, dt)
            traj.append(p.copy())
        return np.asarray(traj)

    # 手写旧公式 (一阶过阻尼): p ← p + (−∇Φ)·dt
    _e, _go = make_engine("old")
    phi = lambda q: 0.5 * float(np.dot(np.asarray(q, float) - _go, np.asarray(q, float) - _go))
    p = np.zeros(2)
    ref_traj = [p.copy()]
    for _ in range(30):
        g = _e.metric.tangent_gradient(phi, p)
        p = _e.navigator.step(p, -g, dt)
        ref_traj.append(p.copy())
    ref_traj = np.asarray(ref_traj)

    traj_old = run_engine("old")
    traj_M1 = run_engine("M1")
    reg = np.array_equal(traj_old, ref_traj)
    moved = float(np.linalg.norm(traj_M1[-1] - traj_old[-1]))
    diff_all = bool(not np.allclose(traj_M1, traj_old))
    ok_all &= bool(reg) and diff_all
    print("\n② 多步轨迹 (30 步, 同一势场 Φ=½‖p−goal‖²):")
    print(f"   零回归: inertia=关 轨迹 与 手写旧公式(一阶) 逐位相同 = {reg}")
    print(f"   惯性生效: M=1 轨迹 ≠ 关惯性轨迹  末端差 {moved:.6f} (≠0) = {diff_all}")

    # ── 动量: 场反转后仍沿原方向走 ────────────────────────────────────────────
    F1, F2, N = np.array([1.0, 0.0]), np.array([-1.0, 0.0]), 20
    def ramp(e):
        p = np.zeros(2)
        for _ in range(N):
            p = e._evolve(p, F1, dt)
        x_rev = float(p[0])
        for _ in range(3):
            p = e._evolve(p, F2, dt)
        return x_rev, float(p[0]), e.velocity

    e_off = ME(manifold_type="euclidean", latent_dim=2, state_dim=2, action_dim=2)
    e_on = ME(manifold_type="euclidean", latent_dim=2, state_dim=2, action_dim=2,
              manifold_M=1.0, inertia=True)
    x1_off, x2_off, v_off = ramp(e_off)
    x1_on, x2_on, v_on = ramp(e_on)
    momentum = (x2_on > x1_on) and (x2_off < x1_off)
    ok_all &= bool(momentum)
    print("\n③ 动量 (20 步 +F 后, 再 3 步 −F):")
    print(f"   过阻尼 (M=关): 反转点 x={x1_off:.6f} → 反转后 x={x2_off:.6f} (立刻反向, "
          f"Δ={x2_off - x1_off:+.2e})")
    print(f"   有惯性 M=1  : 反转点 x={x1_on:.6f} → 反转后 x={x2_on:.6f} (仍沿原方向, "
          f"Δ={x2_on - x1_on:+.2e} · 动量 v={np.round(v_on,6)})")
    print(f"   动量判定 (惯性仍向前 & 过阻尼已反向) = {momentum}")

    print("\n" + "=" * 78)
    print("结论:", "全部通过 ✅" if ok_all else "有失败 ❌")
    print("MANIFOLD_M_EXPERIMENT_DONE")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
