# -*- coding: utf-8 -*-
"""🧪 ab_live_goal.py — 活目标帧 × L2 收口闸 A/B (2026-09-15)

取证链条:
  · 训练: goal = 该回合**末帧像素** (INTACT-JEPA jepa.py:190 + train.py:87)
  · 运行时: 引擎从不 set_goal → 固定文件 intact_goal_frame_optical.npy (全 seed 共用一张)
  · 实测 diag_goal_match: 换活目标帧 → 提案 0% 逐位相同, 平均 |Δu|=0.115 (≈u 本身量级!),
    最小插入 47.6→25.3mm ⇒ 目标帧是提案跑偏的真因之一
本 A/B: 同 seed 同权重, 2×2 = {固定goal, 活goal} × {闸关, 闸开}
用法: MUJOCO_GL=egl gui-venv311/bin/python tools/ab_live_goal.py --seeds 0,1,2 --steps 600
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter

import numpy as np

os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("DISPLAY", ":0")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUI = os.path.join(ROOT, "tools", "gui")
for _p in (ROOT, os.path.join(ROOT, "src"), os.path.join(ROOT, "tools"), GUI):
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.chdir(GUI)
# 🧊 评估纪律 (2026-09-15 实证): 引擎肌肉记忆默认开且跨 run 持久化 (data/muscle_memory.json);
#   热记忆让同一 seed 结果随历史漂移 (seed0 从稳定成功→6/6 确定性失败; 冷/热 = 3/8 vs 4/8),
#   且热记忆下 30~65% 执行帧是记忆回放而非实时计算。A/B 默认隔离成空记忆 (冷口径),
#   AB_HOT_MEM=1 才用共享记忆。
if os.environ.get("AB_HOT_MEM") != "1":
    os.environ.setdefault("SS_MUSCLE_PATH", "/tmp/ab_mem_%d.json" % os.getpid())
for k, v in (("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache"),
             ("LOCAL_DATASET_DIR", "/home/ubuntu/stable-wm-cache"),
             ("INTACT_RUNTIME", "root"), ("INTACT_POLICY", "intact_l4_current"),
             ("OMP_NUM_THREADS", "6")):
    os.environ.setdefault(k, v)
# 臂: (闸, 活目标帧); "analytic" = 不设 SS_L4_INTACT (解析链锚), 特殊处理
ARMS = {"analytic": (None, False),
        "fixed_gate_off": ("0", False), "fixed_gate_on": ("1", False),
        "live_gate_off": ("0", True),  "live_gate_on": ("1", True)}


def _mk(seed):
    from state_space_sim_real import RealStateSpaceSim
    from lerobot.manifold.intact_node import IntactNode, IntactRuntime
    sim = RealStateSpaceSim(seed=seed, vision=False, mode="insert", log=lambda *x: None)
    node = IntactNode(horizon=8, runtime=IntactRuntime(task="pusht", device="cpu"))
    sim.attach_intact(node)
    return sim, node


def live_goal_frame(seed: int, steps: int):
    """解析链跑到底 → 终态帧 (与训练口径同构: goal = 回合末帧)"""
    import cv2
    os.environ.pop("SS_L4_INTACT", None)
    sim, _ = _mk(seed)
    sim.run(max_steps=steps)
    fr = np.asarray(sim._render_frame())
    if fr.ndim == 3 and fr.shape[0] in (1, 3, 4) and fr.shape[-1] not in (3, 4):
        fr = fr.transpose(1, 2, 0)
    return cv2.resize(np.ascontiguousarray(fr.astype(np.float32)), (224, 224),
                      interpolation=cv2.INTER_AREA).transpose(2, 0, 1)


def run_one(seed: int, arm: str, steps: int, goal_live) -> dict:
    gate, use_live = ARMS[arm]
    if gate is None:                     # 解析链锚: 不挂 L4
        os.environ.pop("SS_L4_INTACT", None)
        os.environ.pop("SS_L4_INTACT_GATE", None)
    else:
        os.environ["SS_L4_INTACT"] = "1"
        os.environ["SS_L4_INTACT_GATE"] = gate
    os.environ.pop("SS_L4_INTENT_LINE", None)
    t0 = time.time()
    sim, node = _mk(seed)
    if use_live:
        node.set_goal(goal_live)
    tr = sim.run(max_steps=steps)
    dist = np.asarray(tr.get("dist") or [], float)
    stg = [str(s).replace("阶段 ", "") for s in (tr.get("stage") or [])]
    l4s = sim.l4_intact_summary()
    return {"seed": seed, "arm": arm, "steps": len(stg),
            "done": bool(tr.get("done", [False])[-1]), "stage_counts": dict(Counter(stg)),
            "reached": {k: next((i for i, s in enumerate(stg) if s.startswith(k)), -1)
                        for k in ("对位", "下降", "抓取", "转移", "插入")},
            "insert_mm_end": round(float(dist[-1]) * 1000, 1) if dist.size else None,
            "insert_mm_min": round(float(dist.min()) * 1000, 1) if dist.size else None,
            "goal_src": getattr(node, "goal_src", "?"),
            "veto": l4s.get("l2_veto"), "veto_dir": l4s.get("l2_veto_dir"),
            "veto_mag": l4s.get("l2_veto_mag"), "pass": l4s.get("gate_pass"),
            "blend": l4s.get("blend"), "w": l4s.get("w"), "sec": round(time.time() - t0, 1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="0,1,2")
    ap.add_argument("--steps", type=int, default=600)
    ap.add_argument("--arms", default="fixed_gate_off,live_gate_off,fixed_gate_on,live_gate_on")
    a = ap.parse_args()
    ts = time.strftime("%Y%m%d_%H%M%S")
    jl = os.environ.get("AB_JSONL")            # 单臂独立进程模式: 追加到 JSONL (跨臂无进程内状态)
    rep = int(os.environ.get("AB_REP", "0"))
    out = jl or os.path.join(ROOT, "reports", f"ab_live_goal_{ts}.json")
    rows = []
    for sd in [int(x) for x in a.seeds.split(",") if x.strip()]:
        gl = live_goal_frame(sd, a.steps)
        print(f"—— seed{sd} 活目标帧 std={gl.std():.1f} ——", flush=True)
        for arm in [x.strip() for x in a.arms.split(",") if x.strip()]:
            try:
                r = run_one(sd, arm, a.steps, gl)
            except Exception as e:                                              # noqa: BLE001
                r = {"seed": sd, "arm": arm, "error": f"{type(e).__name__}: {e}"}
            r["rep"] = rep
            rows.append(r)
            if jl:
                with open(jl, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            else:
                json.dump({"ts": ts, "policy": os.environ.get("INTACT_POLICY"), "rows": rows},
                          open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print(f"[seed{sd} {arm:15s}] done={r.get('done')} 阶段={r.get('stage_counts')} "
                  f"末端={r.get('insert_mm_end')}mm 最小={r.get('insert_mm_min')}mm "
                  f"否决={r.get('veto')}(向{r.get('veto_dir')}/幅{r.get('veto_mag')}) "
                  f"通过={r.get('pass')} 融合={r.get('blend')} · {r.get('sec')}s {r.get('error','')}",
                  flush=True)
    print(f"\n→ {os.path.relpath(out, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
