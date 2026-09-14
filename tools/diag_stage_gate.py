# -*- coding: utf-8 -*-
"""🔍 diag_stage_gate.py — 阶段推进闸门诊断 (2026-09-15)

背景 (实测, 不是推断): 闭环 A/B 里直驱/直连线两臂 stage_counts = {'接近':600} 或
{'接近':131,'对位':469} —— **从未到过"下降"更别说"插入"**。所以"插入段白名单解禁"是空操作
(direct vs direct_ins 数字完全一致, 已证)。真正要查的是: 哪个闸门没开。

本脚本: 同 seed 跑 analytic / direct / line_w1 三臂, 逐帧记录阶段 + 侧向误差 d_xy +
高度差 dh + 夹持/接触, 每 50 帧打一行 → 直接看"卡在哪个判据"。
用法: MUJOCO_GL=egl gui-venv311/bin/python tools/diag_stage_gate.py --seed 0 --steps 600
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np

os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("DISPLAY", ":0")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUI = os.path.join(ROOT, "tools", "gui")
for _p in (ROOT, os.path.join(ROOT, "src"), os.path.join(ROOT, "tools"), GUI):
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.chdir(GUI)
os.environ.setdefault("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache")
os.environ.setdefault("LOCAL_DATASET_DIR", "/home/ubuntu/stable-wm-cache")
os.environ.setdefault("INTACT_RUNTIME", "root")
os.environ.setdefault("INTACT_POLICY", "intact_l4_current")
os.environ.setdefault("OMP_NUM_THREADS", "6")
ARMS = {"analytic": (False, False), "direct": (True, False), "line_w1": (True, True)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--steps", type=int, default=600)
    a = ap.parse_args()
    for arm, (l4, line) in ARMS.items():
        os.environ.pop("SS_L4_INTACT", None)
        os.environ.pop("SS_L4_INTENT_LINE", None)
        os.environ.pop("SS_L4_INTACT_STAGES", None)
        if l4:
            os.environ["SS_L4_INTACT"] = "1"
        if line:
            os.environ["SS_L4_INTENT_LINE"] = "1"
            os.environ["SS_L4_INTENT_LINE_W"] = "1"
        from state_space_sim_real import RealStateSpaceSim
        from lerobot.manifold.intact_node import IntactNode, IntactRuntime
        sim = RealStateSpaceSim(seed=a.seed, vision=False, mode="insert", log=lambda *x: None)
        sim.attach_intact(IntactNode(horizon=8, runtime=IntactRuntime(task="pusht", device="cpu")))
        tr = sim.run(max_steps=a.steps)
        ph = np.asarray(tr.get("peg_head") or [], float).reshape(-1, 3)
        tg = np.asarray(tr.get("target") or [], float)
        if tg.ndim == 2:
            tg = tg[:len(ph)]
        else:
            tg = np.repeat(tg.reshape(1, 3), len(ph), axis=0)
        stg = [str(s).replace("阶段 ", "") for s in (tr.get("stage") or [])]
        dxy = np.linalg.norm(ph[:, :2] - tg[:, :2], axis=1) if len(ph) else np.zeros(0)
        dh = ph[:, 2] - tg[:, 2] if len(ph) else np.zeros(0)
        gr = np.asarray(tr.get("grasped") or [], float)
        print(f"\n=== {arm} (seed{a.seed}) 步数={len(stg)} done={tr.get('done',[False])[-1]} "
              f"阶段序列={sorted(set(stg))} ===")
        print("  帧   阶段    d_xy(mm)   dh(mm)   grasped")
        for i in range(0, len(stg), 50):
            print(f"  {i:4d}  {stg[i]:6s} {dxy[i]*1000:8.1f} {dh[i]*1000:8.1f}   "
                  f"{gr[i] if i < len(gr) else float('nan'):.0f}")
        if len(dxy):
            print(f"  → d_xy 最小 {dxy.min()*1000:.1f}mm (第 {int(dxy.argmin())} 帧) · "
                  f"dh 最小 {dh.min()*1000:.1f}mm · 首达 对位 {next((i for i,s in enumerate(stg) if s=='对位'), -1)} · "
                  f"首达 下降 {next((i for i,s in enumerate(stg) if s=='下降'), -1)} · "
                  f"首达 插入 {next((i for i,s in enumerate(stg) if s=='插入'), -1)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
