# -*- coding: utf-8 -*-
"""🌌 collect_mani_geo_data.py — 流形专家预测器的**几何同帧**训练数据 (engine 真跑)

为什么换路线 (2026-09-14 夜 实证):
  · z_t(192)+δ → 流形 6 维: LOSO R² 全负 (不可辨识, 两次独立复现) ⇒ 直连线输入不能用 INTACT 潜空间;
  · 几何 9 维 → 流形 6 维: 4/6 维 R² 强正 (progress 0.61 / V 0.51 / rem 0.96 / dperp 0.92) ⇒ **几何路线成立**;
  ⇒ 本采集器按引擎自有口径取同帧 (z7, 动作, 流形真值, 阶段, 几何) —— z7 本来就是"供 predictor 训练同构采集"的通道。

每帧存 (全部来自 **同一帧**, 口径同源):
  z7      : 几何潜空间 R7 (夹持后 x→光模块头)                [tr["z7_vec"]]
  a       : 本帧真实下发的执行动作 4 维 (专家动作)            [tr["u_exec_vec"]]
  mani6   : 流形真值 [progress, risk, V, eta, rem, dperp]    [tr mani_*]
  peg/tgt : 光模块头位置 + 阶段目标点 (几何意图监督用)         [tr["peg_head"], tr["target"]]
  stage   : 阶段名 · split: clean/jitter · seed: 回合组标识

产物: data/manifold_geo_v1.npz  (含 split/seed/stage, 供 LOSO 按回合组留出)
用法: MUJOCO_GL=egl gui-venv311/bin/python tools/collect_mani_geo_data.py [--clean 4] [--jitter 2]
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import numpy as np

os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("DISPLAY", ":0")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_GUI = os.path.join(ROOT, "tools", "gui")
for _p in (ROOT, os.path.join(ROOT, "src"), os.path.join(ROOT, "tools"), _GUI):
    if _p not in sys.path:
        sys.path.insert(0, _p)

KEYS6 = ["mani_progress", "mani_risk", "mani_V", "mani_eta", "mani_rem", "mani_dperp"]
JIT = [{"dx": -0.035, "dy": 0.02, "dz": 0.005, "yaw": np.deg2rad(10)},
       {"dx": 0.03, "dy": -0.025, "dz": 0.0, "yaw": np.deg2rad(-12)},
       {"dx": 0.025, "dy": 0.03, "dz": 0.008, "yaw": np.deg2rad(6)},
       {"dx": -0.02, "dy": -0.035, "dz": 0.002, "yaw": np.deg2rad(-9)}]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean", type=int, default=4, help="干净布局跑几个 seed")
    ap.add_argument("--jitter", type=int, default=2, help="干扰布局跑几个 seed (每 seed 4 档扰动)")
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "manifold_geo_v1.npz"))
    a = ap.parse_args()
    os.chdir(_GUI)                                  # 引擎按相对路径加载六层模块
    from state_space_sim_real import RealStateSpaceSim   # noqa: PLC0415

    Z, A, M, P, T, ST, SP, SD = [], [], [], [], [], [], [], []

    def grab(sim, tr, split, tag):
        n = len(tr["t"])
        z7 = [np.asarray(v, float).ravel() for v in tr.get("z7_vec", [])]
        u = tr.get("u_exec_vec", [])
        if len(z7) < n or len(u) < n:
            print(f"  ⚠️ {tag}: z7/u 长度不足 ({len(z7)}/{len(u)} < {n}) → 跳过", flush=True)
            return 0
        got = 0
        for i in range(n - 1):
            m6 = np.array([tr[k][i] for k in KEYS6], float)
            if not np.isfinite(m6).all() or np.abs(m6).max() < 1e-6:
                continue
            Z.append(z7[i][:7]); A.append(np.asarray(u[i], float).ravel()[:4]); M.append(m6)
            P.append(np.asarray(tr.get("peg_head", [np.zeros(3)] * n)[i], float).ravel()[:3])
            T.append(np.asarray(tr.get("target", [np.zeros(3)] * n)[i], float).ravel()[:3])
            ST.append(str(tr["stage"][i]).replace("阶段 ", "").split("·")[0].strip())
            SP.append(split); SD.append(tag)
            got += 1
        done = bool(tr.get("done", [False])[-1]) if tr.get("done") else False
        print(f"  {tag}: {n} 步 → 有效帧 {got} · done={done}", flush=True)
        return got

    t0 = time.time()
    for s in range(int(a.clean)):
        try:
            sim = RealStateSpaceSim(seed=s, vision=False, mode="insert", log=lambda *x: None)
            grab(sim, sim.run(cap="L4"), "clean", f"clean_s{s}")
        except Exception as e:                                              # noqa: BLE001
            print(f"  ❌ clean_s{s} 失败: {type(e).__name__}: {e}", flush=True)
        np.savez_compressed(a.out, z=np.asarray(Z, float), a=np.asarray(A, float),
                            m=np.asarray(M, float), peg=np.asarray(P, float),
                            target=np.asarray(T, float), stage=np.array(ST, object),
                            split=np.array(SP, object), seed=np.array(SD, object))
    for s in range(int(a.jitter)):
        for k, ov in enumerate(JIT):
            try:
                sim = RealStateSpaceSim(seed=s, vision=False, mode="insert", log=lambda *x: None)
                sim._jitter_override = ov
                sim._jitter_round = 900 + k
                grab(sim, sim.run(cap="L4"), "jitter", f"jit_s{s}_{k}")
            except Exception as e:                                          # noqa: BLE001
                print(f"  ❌ jit_s{s}_{k} 失败: {type(e).__name__}: {e}", flush=True)
        np.savez_compressed(a.out, z=np.asarray(Z, float), a=np.asarray(A, float),
                            m=np.asarray(M, float), peg=np.asarray(P, float),
                            target=np.asarray(T, float), stage=np.array(ST, object),
                            split=np.array(SP, object), seed=np.array(SD, object))
    n = len(Z)
    if n:
        sp = np.array(SP); m6 = np.asarray(M, float)
        print(f"\n✅ 落盘 {os.path.relpath(a.out, ROOT)} · {n} 帧 · {len(set(SD))} 组 · "
              f"clean {int((sp=='clean').sum())} / jitter {int((sp=='jitter').sum())} · "
              f"用时 {(time.time()-t0)/60:.1f} 分钟")
        print(f"   mani6 逐维 |均值| {np.round(np.abs(m6).mean(0), 5).tolist()} · "
              f"|max| {np.round(np.abs(m6).max(0), 4).tolist()}")
    else:
        print("❌ 没采到有效帧")
    return 0


if __name__ == "__main__":
    sys.exit(main())
