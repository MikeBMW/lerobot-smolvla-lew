#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🎯 L4 INTACT 单臂运行器 (给 tools/l4_intact_ab.py 逐臂子进程调用)。

真实链路: 六层引擎 RealStateSpaceSim (metaworld 真物理) 每步渲染帧 → INTACT 节点真推理
→ 意图解码器 → u_ff 槽位 (SS_L4_INTACT 门控) → 状态机 → env.step。
输出: 一行 JSON 到 stdout (含 done/dist/steps + l4_intact_summary)。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("INTACT_DEVICE", "cpu")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--max-steps", type=int, default=700)
    ap.add_argument("--cap", default="l4")
    a = ap.parse_args()
    os.chdir(ROOT)
    from state_space_sim_real import RealStateSpaceSim          # noqa: PLC0415

    sim = RealStateSpaceSim(seed=a.seed, vision=False, mode="full", log=lambda *x: None)
    l4_on = os.environ.get("SS_L4_INTACT") == "1"
    if l4_on:
        from lerobot.policies.intact.runtime import IntactNode, IntactRuntime   # noqa: PLC0415
        node = IntactNode(horizon=8, action_dim=4, runtime=IntactRuntime(
            repo=None, policy=os.environ.get("INTACT_RUNTIME", "root"),
            ckpt=os.environ.get("INTACT_POLICY") or None,
            device=os.environ.get("INTACT_DEVICE", "cpu")))
        sim.attach_intact(node)                       # 引擎的 L4 挂载点 (node 自持动作历史)
    tr = sim.run(max_steps=a.max_steps, cap=(None if a.cap in ("none", "0", "") else a.cap))
    out = {"seed": a.seed, "arm_l4": l4_on, "shadow": os.environ.get("SS_L4_INTACT_SHADOW") == "1",
           "done": bool(tr["done"][-1]), "steps": len(tr["t"]),
           "dist_final": round(float(tr["dist"][-1]), 4),
           "stage_end": str(tr["stage"][-1]),
           "l4": (sim.l4_intact_summary() if hasattr(sim, "l4_intact_summary") else None)}
    print(json.dumps(out, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
