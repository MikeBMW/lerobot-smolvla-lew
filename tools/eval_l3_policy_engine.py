#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval_l3_policy_engine.py — t21: state_space 策略**真实**成功率 (在引擎闭环里测, 口径同源)

背景 (会话十定论): 独立 harness `rollout_peg_check.py` 直接喂裸 obs → 模型首层收到 43 维 (期望 39)
  ⇒ 与训练口径不同源 ⇒ 那个 0% 是**假0%**。正确做法 = 用**引擎自己的 L3 闭环**:
      batch = visual39(引擎自建) + _l3_pre(训练期预处理器) + 128×128 图 + task 串  (state_space_sim_real.py:1249-1272)
      SS_L3=1 时 xyz 由模型出, gripper 仍由状态机管 (引擎既有约定)

方法: 同一 harness 跑两档, **带正对照**证明 harness 本身有效
  档 A(正对照) = 引擎默认 L3 ckpt (文档称"已实测验证过接管全链: insert 341 步") → 期望不 0%
  档 B(候选)   = outputs/train/state_space_mw5w/checkpoints/030000 (会话十被假0%误判的那颗头)
指标 (与 moe_engine_bypass 完全一致): done / 末端 mm / 最小 mm / 步数 / 到过的阶段
用法: gui-venv311/bin/python tools/eval_l3_policy_engine.py [--seeds 2] [--steps 260]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

R = "/home/ubuntu/zmax_rel"
sys.path.insert(0, os.path.join(R, "tools"))
sys.path.insert(0, os.path.join(R, "tools/gui"))
sys.path.insert(0, os.path.join(R, "src"))
os.chdir(R)

CK_DEFAULT = "outputs/train/smolvla_lew_v10_1h/checkpoints/004000/pretrained_model"   # 正对照 (文档已验证)
CK_CAND = "outputs/train/state_space_mw5w/checkpoints/030000/pretrained_model"        # 候选 (被假0%误判)


def clean_stage(s):
    t = str(s).strip()
    for pre in ("阶段 ", "阶段"):
        if t.startswith(pre):
            t = t[len(pre):].strip()
    return t


def run_one(ck, seed, steps, mode="insert", task=None):
    from state_space_sim_real import RealStateSpaceSim
    if task:
        os.environ["SS_L3_TASK"] = task
    logs = []
    sim = RealStateSpaceSim(seed=seed, vision=False, mode=mode, log=lambda *x: logs.append(" ".join(str(i) for i in x)))
    t0 = time.time()
    tr = sim.run(max_steps=steps)
    dist = np.asarray(tr.get("dist") or [], float)
    st = [clean_stage(s) for s in (tr.get("stage") or [])]
    ck_line = next((l for l in logs if "模型 ckpt" in l or "L3" in l and "接入" in l), "")
    return {
        "engine_says": ck_line[-160:],
        "seed": seed, "steps": len(tr.get("t", [])), "wall_s": round(time.time() - t0, 1),
        "done": bool((tr.get("done") or [False])[-1]),
        "insert_mm_end": round(float(dist[-1]) * 1000, 1) if dist.size else None,
        "insert_mm_min": round(float(dist.min()) * 1000, 1) if dist.size else None,
        "stages_seen": list(dict.fromkeys(st))[-6:],
        "reached_insert": any(s in ("插入", "完成") for s in st),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=2)
    ap.add_argument("--steps", type=int, default=260)
    ap.add_argument("--mode", default="insert")
    ap.add_argument("--task", default=None, help="语言串 (缺省=引擎默认, 与训练同源)")
    a = ap.parse_args()

    print("═" * 80)
    print("🎯 t21 · L3 策略真实成功率 (引擎闭环口径: visual39 + _l3_pre + 128 图 + task 串)")
    print("═" * 80)
    res = {}
    for tag, ck in (("A 正对照(默认 v10_1h)", CK_DEFAULT), ("B 候选(state_space_mw5w)", CK_CAND)):
        p = os.path.join(R, ck)
        exists = os.path.isdir(p)
        print("\n▶ %s\n   ckpt=%s (%s)" % (tag, ck, "存在" if exists else "❌ 不存在"), flush=True)
        if not exists:
            res[tag] = {"error": "ckpt 不存在"}
            continue
        os.environ["SS_L3"] = "1"
        os.environ["SS_L3_CK"] = ck
        os.environ["SS_L3_FORCE_RETRY"] = "1"
        # 换 ckpt 必须清类级缓存 (否则沿用上一档模型 = 假结果)
        try:
            from state_space_sim_real import RealStateSpaceSim as _S
            _S._L3_CACHE = None
            _S._L3_FAILED = None
        except Exception:                                                     # noqa: BLE001
            pass
        rows = []
        for sd in range(a.seeds):
            try:
                r = run_one(ck, sd, a.steps, a.mode, a.task)
            except Exception as e:                                            # noqa: BLE001
                r = {"seed": sd, "error": "%s: %s" % (type(e).__name__, str(e)[:120])}
            rows.append(r)
            print("   seed%d: %s" % (sd, json.dumps(r, ensure_ascii=False)[:180]), flush=True)
        ok = [r for r in rows if r.get("done")]
        res[tag] = {"ckpt": ck, "n": len(rows), "success": len(ok),
                    "rate": round(len(ok) / max(len(rows), 1), 3), "rows": rows}
    print("\n" + "═" * 80)
    for tag, v in res.items():
        if "error" in v:
            print("  %-26s ❌ %s" % (tag, v["error"]))
        else:
            mms = [r.get("insert_mm_min") for r in v["rows"] if isinstance(r.get("insert_mm_min"), (int, float))]
            print("  %-26s 成功率 %d/%d (%.0f%%) · 最小末端 %s mm" %
                  (tag, v["success"], v["n"], v["rate"] * 100,
                   round(float(np.mean(mms)), 1) if mms else "—"))
    pa = res.get("A 正对照(默认 v10_1h)", {})
    pb = res.get("B 候选(state_space_mw5w)", {})
    print("\n判读:")
    if isinstance(pa.get("rate"), float) and pa["rate"] > 0:
        print("  ✅ harness 有效 (正对照 %d/%d 成功)" % (pa["success"], pa["n"]))
        if isinstance(pb.get("rate"), float):
            print("  → 候选 state_space 策略真实成功率 = %d/%d (%.0f%%) — **这是有效口径下的数字**"
                  % (pb["success"], pb["n"], pb["rate"] * 100))
    else:
        print("  ⚠️ 正对照也 0 成功 → harness 口径仍不对, 候选的 0%% 依旧不可信 (需继续对口径)")
    dst = os.path.join(R, "reports", "l3_policy_eval_engine_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    json.dump({"ts": time.strftime("%F %T"), "seeds": a.seeds, "steps": a.steps, "result": res},
              open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n取证: %s" % dst)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
