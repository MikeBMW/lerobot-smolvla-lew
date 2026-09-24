#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧮 manifold_engine_bench.py — 流形引擎**实测**基准 (规格书 vs 真数字)

真数据: 真跑引擎 → 用同一段轨迹喂引擎 (编码→投影→梯度→导航→反馈), 逐帧记延迟;
精度: 测地线端点误差 / 约束违例 / 解码器 R² (标定值) / 反馈限幅是否生效。
**只报实测, 不抄规格书数字** (规格书目标单独列一栏做对照)。

用法: MUJOCO_GL=egl ./gui-venv311/bin/python tools/manifold_engine_bench.py
"""
from __future__ import annotations

import json
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "src"), os.path.join(ROOT, "tools"), os.path.join(ROOT, "tools", "gui")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache")
os.environ.setdefault("LOCAL_DATASET_DIR", "/home/ubuntu/stable-wm-cache")
os.environ.setdefault("INTACT_RUNTIME", "root")

CKPT = os.path.join(ROOT, "models", "manifold_engine.npz")


def main() -> int:
    from lerobot.manifold.manifold_engine import ManifoldEngine, MANIFOLD_REGISTRY
    import state_space_sim_real as SSR

    sim = SSR.RealStateSpaceSim(seed=104, vision=False, mode="insert", log=lambda *x: None)
    tr = sim.run(max_steps=160)
    O = np.asarray(tr["obs"], float)[:, :43]
    stages = [str(s).split("·")[0].strip() for s in (tr.get("stage") or [])]
    print(f"引擎真跑: {len(O)} 帧 (obs43) · 加载标定 {os.path.exists(CKPT)}")

    eng = ManifoldEngine(manifold_type="su2", latent_dim=16, state_dim=43, action_dim=4)
    loaded = eng.load(CKPT) if os.path.exists(CKPT) else False
    if not loaded:
        eng.fit(O, np.asarray(tr["u_exec_vec"], float)[:len(O), :4])

    # 逐帧真跑 (与引擎同节拍: 每帧 encode→project→gradient→navigate step→feedback)
    # 🐛 2026-09-24: 目标必须取**收敛态** (末帧投影), 不能取当前点 —— 否则 Φ≡0, 测地线长 0 (自欺)
    goal = eng.project(O[-1])["p"]
    t_all = []
    anom = 0
    conf, drift, resid, phi = [], [], [], []
    phi_dec = 0
    phi_prev = None
    for i in range(1, len(O)):
        t0 = time.perf_counter()
        r = eng.project(O[i])
        if eng.goal_point is None:
            eng.goal_point = goal
        gf = eng.gradient_flow()
        if phi_prev is not None and gf["phi"] <= phi_prev + 1e-12:
            phi_dec += 1
        phi_prev = gf["phi"]
        eng.navigator.step(r["p"], gf["descent"], dt=0.01)
        fb = eng.feedback_update(O[i][:r["p"].size] - O[i - 1][:r["p"].size])   # 真残差 (相邻帧差)
        t_all.append((time.perf_counter() - t0) * 1e3)
        conf.append(r["confidence"])
        drift.append(r["drift"])
        resid.append(r["residual"])
        phi.append(gf["phi"])
        anom += int(r["anomaly"])

    t_all = np.asarray(t_all)
    # 测地线: 必须从**起始态**走到收敛态 (从当前点走 = 长度 0, 自欺)
    p_start = eng.project(O[1])["p"]
    eng.current_manifold_point = p_start
    nav = eng.navigate(goal, T=16)                     # 真目标 = 末帧收敛态
    # 解码器质量: 现算 (用已载入的 readout 对同一段真轨迹求 R²), 不引用标定时数字
    U = np.asarray(tr["u_exec_vec"], float)[:len(O), :4]
    if eng.readout is not None:
        P = np.asarray([eng.project(O[i])["p"] for i in range(len(O))], float)
        pred = P @ eng.readout + eng.readout_b
        if eng.action_lo is not None:                    # 解码必须带标定界 (未限幅会外推发散)
            pred = np.clip(pred, eng.action_lo, eng.action_hi)
        cut = int(eng.encoder.n_fit)                     # 标定用过的帧 = 训练段, 其余 = 未见过
        cut = max(8, min(cut, len(U) - 8))

        def _r2(u, p):
            return round(1.0 - float(((u - p) ** 2).sum() / max(((u - u.mean(0)) ** 2).sum(), 1e-12)), 4)

        corr = [round(float(np.corrcoef(U[:cut, i], pred[:cut, i])[0, 1]), 3)
                for i in range(U.shape[1]) if U[:cut, i].std() > 1e-9]
        dec = {"readout_r2_训练段": _r2(U[:cut], pred[:cut]),
               "readout_r2_未见段": _r2(U[cut:], pred[cut:]),
               "readout_r2_全段": _r2(U, pred),
               "逐维相关_训练段": corr,
               "幅度比_全段(中位)": round(float(np.median(np.abs(pred).sum(1) /
                                                         np.maximum(np.abs(U).sum(1), 1e-9))), 3),
               "预测最大幅值": round(float(np.abs(pred).max()), 3),
               "真值最大幅值": round(float(np.abs(U).max()), 3),
               "n_训练/未见": [int(cut), int(len(U) - cut)], "src": eng.__dict__.get("_dec_src", "ridge 拟合解码器 (带动作界限幅)")}
    else:
        dec = {"readout_r2_训练段": None, "src": "未标定"}
    lat = eng.latency_report()
    spec = eng.spec_check()
    out = {
        "数据源": "真跑引擎 seed104 160 步 (obs43 真实轨迹)",
        "流形": eng.manifold_type, "标定": {"loaded": loaded, "n_fit": eng.encoder.n_fit,
          "latent_dim": eng.encoder.latent_dim, **dec},
        "实测_单帧端到端": {"n": int(t_all.size), "mean_ms": round(float(t_all.mean()), 4),
                            "p50_ms": round(float(np.percentile(t_all, 50)), 4),
                            "p95_ms": round(float(np.percentile(t_all, 95)), 4)},
        "实测_分阶段延迟": lat,
        "实测_约束违例_max": float(np.max(resid)),
        "实测_投影改动量(均值)": round(float(np.mean(drift)), 4),
        "实测_投影改动量分位": {"p50": round(float(np.percentile(drift, 50)), 4),
                                "p95": round(float(np.percentile(drift, 95)), 4),
                                "max": round(float(np.max(drift)), 4)},
        "实测_置信度(均值/最小)": [round(float(np.mean(conf)), 4), round(float(np.min(conf)), 4)],
        "实测_异常帧数": int(anom),
        "实测_异常率": round(anom / max(len(t_all), 1), 4),
        "实测_势能下降帧占比": round(phi_dec / max(len(t_all) - 1, 1), 4),
        "实测_势能Φ(首/末)": [round(float(phi[0]), 5), round(float(phi[-1]), 5)],
        "测地线": {"T": nav["n"], "length": nav["length"], "end_error": nav["end_error"],
                   "kind": nav["geodesic_kind"], "t_ms": nav.get("t_navigate_ms")},
        "规格对照": spec,
        "流形注册表": eng.registry_table(),
    }
    print(json.dumps(out, ensure_ascii=False, indent=1))
    p = os.path.join(ROOT, "reports", "manifold_engine_bench.json")
    json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"→ {p}")
    print("MANIFOLD_BENCH_DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
