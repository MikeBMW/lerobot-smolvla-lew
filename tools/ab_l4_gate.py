# -*- coding: utf-8 -*-
"""🧪 ab_l4_gate.py — L2 收口闸 A/B (直驱档 u 越界否决, 2026-09-15)

背景 (实测): 直驱档 (SS_L4_INTACT=1) 的 u 在 y 轴恒定撞限幅、|u| 是解析链 2.3×、
60 帧末端飞 243mm 朝错方向 → 600 帧永不离开"接近"阶段, 从没到过下降/插入。
本 A/B: 同 seed 同权重, 只切 SS_L4_INTACT_GATE (1=闸生效 / 0=旧行为), 指标=是否推进阶段 +
末端插入距离 + 否决计数。
用法: MUJOCO_GL=egl gui-venv311/bin/python tools/ab_l4_gate.py --seeds 0,1,2 --steps 600
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
# 🧪 2026-09-15: "l4_attach_only" = 挂上 L4 但把阶段白名单清空 → L4 块根本不进 (用于隔离
#   "L4 推理本身是否改变了执行": 若 attach_only == analytic 而 gate_on != analytic, 则 L4 推理
#   路径存在对解析链的隐性耦合 (必须查, 否则"闸后结果变好"的归因是错的)。
ARMS = {"analytic": None, "gate_on": "1", "gate_off": "0", "gate_on_line": "1w",
        "l4_attach_only": "1empty"}


def run_one(seed: int, arm: str, steps: int, line: bool) -> dict:
    g = ARMS[arm]
    if g is None:
        os.environ.pop("SS_L4_INTACT", None)
        os.environ.pop("SS_L4_INTACT_GATE", None)
        os.environ.pop("SS_L4_INTACT_STAGES", None)
    else:
        os.environ["SS_L4_INTACT"] = "1"
        os.environ["SS_L4_INTACT_GATE"] = "1" if g.startswith("1") else "0"
        if g.endswith("empty"):
            os.environ["SS_L4_INTACT_STAGES"] = ""      # 空白名单 → L4 块永不进入
        else:
            os.environ.pop("SS_L4_INTACT_STAGES", None)
    line = line or g == "1w"
    if line:
        os.environ["SS_L4_INTENT_LINE"] = "1"
        os.environ["SS_L4_INTENT_LINE_W"] = "1"
    else:
        os.environ.pop("SS_L4_INTENT_LINE", None)
        os.environ.pop("SS_L4_INTENT_LINE_W", None)
    from state_space_sim_real import RealStateSpaceSim
    from lerobot.manifold.intact_node import IntactNode, IntactRuntime
    t0 = time.time()
    sim = RealStateSpaceSim(seed=seed, vision=False, mode="insert", log=lambda *x: None)
    sim.attach_intact(IntactNode(horizon=8, runtime=IntactRuntime(task="pusht", device="cpu")))
    tr = sim.run(max_steps=steps)
    dist = np.asarray(tr.get("dist") or [], float)
    stg = [str(s).replace("阶段 ", "") for s in (tr.get("stage") or [])]
    l4s = sim.l4_intact_summary()
    return {"seed": seed, "arm": arm, "line": line, "steps": len(stg),
            "done": bool(tr.get("done", [False])[-1]),
            "stage_counts": dict(Counter(stg)),
            "reached": {k: next((i for i, s in enumerate(stg) if s.startswith(k)), -1)
                        for k in ("对位", "下降", "抓取", "转移", "插入")},
            "insert_mm_end": round(float(dist[-1]) * 1000, 1) if dist.size else None,
            "insert_mm_min": round(float(dist.min()) * 1000, 1) if dist.size else None,
            "l4": {k: l4s.get(k) for k in ("calls", "blend", "w_zero", "refused", "w", "u_ff_src",
                                           "l2_veto", "l2_veto_dir", "l2_veto_mag", "gate_pass")},
            "il": {k: sim.l4_intent_line_summary().get(k) for k in ("ran", "applied", "w_last")},
            "sec": round(time.time() - t0, 1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="0,1,2")
    ap.add_argument("--steps", type=int, default=600)
    ap.add_argument("--line", type=int, default=0)
    ap.add_argument("--arms", default="analytic,gate_off,gate_on,gate_on_line")
    a = ap.parse_args()
    ts = time.strftime("%Y%m%d_%H%M%S")
    out = os.path.join(ROOT, "reports", f"ab_l4_gate_{ts}.json")
    rows = []
    for sd in [int(x) for x in a.seeds.split(",") if x.strip()]:
        for arm in [x.strip() for x in a.arms.split(",") if x.strip()]:
            try:
                r = run_one(sd, arm, a.steps, bool(a.line))
            except Exception as e:                                              # noqa: BLE001
                r = {"seed": sd, "arm": arm, "error": f"{type(e).__name__}: {e}"}
            rows.append(r)
            json.dump({"ts": ts, "policy": os.environ.get("INTACT_POLICY"), "rows": rows},
                      open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            rc = r.get("stage_counts") or {}
            print(f"[seed{sd} {arm:9s}] done={r.get('done')} 阶段={rc} 首达={r.get('reached')} "
                  f"插入末端={r.get('insert_mm_end')}mm 最小={r.get('insert_mm_min')}mm · "
                  f"否决={r.get('l4',{}).get('l2_veto')}(向{r.get('l4',{}).get('l2_veto_dir')}/"
                  f"幅{r.get('l4',{}).get('l2_veto_mag')}) 通过={r.get('l4',{}).get('gate_pass')} "
                  f"· {r.get('sec')}s {r.get('error','')}", flush=True)
    print(f"\n→ {os.path.relpath(out, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
