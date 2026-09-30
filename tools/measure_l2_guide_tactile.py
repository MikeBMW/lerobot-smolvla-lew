#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔬 measure_l2_guide_tactile.py — 为 L2「3D视觉引导 / 触觉反馈闭环」测试用例**先量真实数字**

纪律: 测试用例的阈值必须来自实测 (不是先写阈值再凑), 本脚本给:
  ① 3D 视觉引导: 引导方向(目标−销头) 与 末端速度 的方向一致性 cos, 横向偏差 e⊥ 收敛, 位姿来源
  ② 触觉反馈闭环: tactile4 与 gripper/grasped 一致, contact_p 接触段水平, 力-接触相关性, 力上界
用法: MUJOCO_GL=egl ./gui-venv311/bin/python tools/measure_l2_guide_tactile.py [--steps 400]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

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


def med(a):
    return round(float(np.median(a)), 4) if len(a) else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=400)
    a = ap.parse_args()
    import state_space_sim_real as SSR
    sim = SSR.RealStateSpaceSim(seed=104, vision=False, mode="insert", log=lambda *x: None)
    tr = sim.run(max_steps=a.steps)
    n = len(tr["t"])
    stage = [str(s).replace("阶段 ", "").split("·")[0].strip() for s in tr["stage"]]
    O = np.asarray(tr["obs"], float)
    peg = np.asarray(tr["peg_head"], float)
    tgt = np.asarray(tr["target"], float)
    v = np.asarray(tr["v_vec"], float)
    cp = np.asarray(tr["contact_p"], float)
    fx = np.asarray(tr["force"], float).reshape(-1)
    out = {"steps": n, "stages": {s: stage.count(s) for s in sorted(set(stage))}}

    # ── ① 3D 视觉引导 ──
    g = tgt - peg                                              # 引导向量 (指向目标)
    gn = np.linalg.norm(g, axis=1)
    vn = np.linalg.norm(v, axis=1)
    m = (gn > 1e-6) & (vn > 1e-4)
    cos = (g[m] * v[m]).sum(1) / (gn[m] * vn[m])
    serv = [s for s in ("接近", "对位", "下降", "转移") if s in stage]
    mask = np.array([s in serv for s in stage]) & m
    cos_serv = (g[mask] * v[mask]).sum(1) / (gn[mask] * vn[mask])
    dperp = np.asarray(tr.get("mani_dperp") or [], float)
    lateral = gn[m] * np.sqrt(np.clip(1 - cos ** 2, 0, 1)) if len(cos) else np.array([])
    third = max(len(lateral) // 3, 1)
    out["3d_guide"] = {
        "引导向量范数_中位_mm": round(float(np.median(gn)) * 1000, 2),
        "cos(引导,速度)_训练段_中位": med(cos_serv),
        "cos(引导,速度)_全体_中位": med(cos),
        "朝向目标帧占比(cos>0.3)": round(float((cos_serv > 0.3).mean()), 4) if len(cos_serv) else None,
        "横向偏差_前1/3_中位_mm": round(float(np.median(lateral[:third])) * 1000, 2) if len(lateral) else None,
        "横向偏差_后1/3_中位_mm": round(float(np.median(lateral[-third:])) * 1000, 2) if len(lateral) else None,
        "mani_dperp_首末_mm": [round(float(dperp[0]) * 1000, 2), round(float(dperp[-1]) * 1000, 2)] if len(dperp) else None,
        "servo_stages": serv,
    }

    # ── ② 触觉反馈闭环 ──
    tac = O[:, 39:43] if O.shape[1] >= 43 else np.zeros((n, 4))
    grip = np.asarray(tr["gripper"], float)
    grasped = np.asarray(tr["grasped"], bool)
    out["tactile"] = {
        "tactile4_通道0==gripper_一致率": round(float(np.mean(np.isclose(tac[:, 0], grip, atol=1e-6))), 4),
        "tactile4_通道1==grasped_一致率": round(float(np.mean(tac[:, 1] == grasped.astype(float))), 4),
        "tactile4_通道2/3_非零帧数": [int(np.count_nonzero(tac[:, 2])), int(np.count_nonzero(tac[:, 3]))],
        "力_范围_N": [round(float(np.min(fx)), 4), round(float(np.max(fx)), 4)],
        "力_上界_实测": round(float(np.max(np.abs(fx))), 4),
        "contact_p_全体_中位": med(cp),
        "contact_p_插入段_中位": med(cp[[i for i, s in enumerate(stage) if s == "插入"]]) if "插入" in stage else None,
        "contact_p_接触段占比(>0.6)": round(float((cp > 0.6).mean()), 4) if len(cp) else None,
        "corr(contact_p, 力)": round(float(np.corrcoef(cp, np.abs(fx))[0, 1]), 4) if fx.std() > 1e-9 else None,
        "grasped_帧数": int(grasped.sum()),
    }
    print(json.dumps(out, ensure_ascii=False, indent=1))
    p = os.path.join(ROOT, "reports", "l2_guide_tactile_measured.json")
    json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"→ {p}")
    print("L2_MEASURE_DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
