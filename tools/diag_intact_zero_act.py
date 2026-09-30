# -*- coding: utf-8 -*-
"""🔬 微诊断: INTACT 直驱为何下发全 0 动作 (12 步, 逐项打印模型内部产物)

  INTACT_RUNTIME=root INTACT_POLICY=intact_l4_current INTACT_DEVICE=cpu \
    gui-venv311/bin/python tools/diag_intact_zero_act.py
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("INTACT_RUNTIME", "root")
os.environ.setdefault("INTACT_POLICY", "intact_l4_current")
os.environ.setdefault("INTACT_DEVICE", "cpu")

import intact_direct_rollout as idr  # noqa: E402
from lerobot.manifold.intact_node import IntactNode, IntactRuntime  # noqa: E402
from state_space_sim_real import RealStateSpaceSim  # noqa: E402

STEPS = int(os.environ.get("MICRO_STEPS", "12"))

print("═══ 环境 ═══")
print("  INTACT_RUNTIME =", os.environ.get("INTACT_RUNTIME"),
      "| INTACT_POLICY =", os.environ.get("INTACT_POLICY"),
      "| device =", os.environ.get("INTACT_DEVICE"))
print("  STABLEWM_HOME =", os.environ.get("STABLEWM_HOME"))

rt = IntactRuntime(task="pusht", device=os.environ["INTACT_DEVICE"])
node = IntactNode(horizon=8, runtime=rt)
print("  trained =", rt.trained, "| reason =", getattr(rt, "reason", None),
      "| policy_name =", getattr(rt, "policy_name", None))
print("  action_dim =", node.action_dim, "| hist_size =", node.hist_size)
sys.stdout.flush()

sstf = os.path.join(ROOT, "reports", "zmax_action_stats.json")
am, asd, smeta = idr.load_stats(sstf)
print("═══ 反归一化统计 ═══")
print("  file:", sstf)
print("  source:", smeta.get("source"), "| n:", smeta.get("n_finite"), "| action_space:", smeta.get("action_space"))
print("  mean:", np.round(am, 4).tolist())
print("  std :", np.round(asd, 4).tolist())
sys.stdout.flush()

goal = np.load(os.path.join(ROOT, "reports", "intact_goal_frame.npy"))
print("  goal frame:", goal.shape, goal.dtype, "mean/std:", round(float(goal.mean()), 3),
      round(float(goal.std()), 3))
node.set_goal(goal)

sim = RealStateSpaceSim(seed=104, vision=False, mode="full", log=lambda *a: None)
rec = {"act": [], "raw": [], "stage": [], "chunk_norm": []}
state = {"n": 0, "calls": 0, "err": None, "verbose_log": print}
idr.install_direct_act(sim, node, am, asd, infer_every=1, rec=rec, state=state)

tr = sim.run(max_steps=STEPS, cap="l4")

print("\n═══ 结果 ═══")
print("  model_calls =", state["calls"], "| err =", state["err"])
print("  rec keys =", {k: type(v).__name__ for k, v in rec.items()})
for k, v in rec.items():
    try:
        arr = np.asarray(v, float)
        print(f"  rec[{k}]: shape={arr.shape} mean={np.round(arr.mean(0), 4) if arr.ndim > 1 else round(float(arr.mean()), 4)}")
    except Exception as e:
        print(f"  rec[{k}]: {type(v).__name__} → {str(v)[:200]} | {e}")
print("  decoder:", json.dumps(state.get("decoder"), ensure_ascii=False, default=str)[:600])
print("  u_ff:", state.get("u_ff"), "| u_ff_source:", state.get("u_ff_source"))
print("  l3_cond:", state.get("l3_cond_ready"), state.get("l3_cond_source"))
print("  skill_ctx_dim:", state.get("skill_ctx_dim"), "| nonzero:", state.get("skill_ctx_nonzero"),
      "| head:", state.get("skill_ctx_head"))
print("  l2_ready:", state.get("l2_ready"), "| l2_err:", state.get("l2_err"))
print("  evidence:", state.get("evidence"))
print("  report_keys:", state.get("report_keys"))
print("  _direct_act:", getattr(sim, "_direct_act", None))
print("  stages:", {s: rec["stage"].count(s) for s in sorted(set(rec["stage"]))} if rec.get("stage") else {})
