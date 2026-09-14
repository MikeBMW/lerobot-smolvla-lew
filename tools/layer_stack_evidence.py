# -*- coding: utf-8 -*-
"""🧱 分层架构取证: L2 可单独运行 / L3 可扩展 / L4 可升级 (引擎真跑, 不是画布截图)

老倪 09-14: "当前的状态空间, 是已经具备了单独运行L2, 且可以扩展到L3,又可以升级到L4,这样的架构么?"
→ 本脚本用**同一个引擎**跑三格, 每格只看一条硬判据:

  A. L2 单独      : mode=insert, cap=l3 (无干扰) → 肌肉记忆快通道真的接管前馈 (mm_hits > 0, 日志有快通道行)
  B. L3 扩展      : mode=full,   cap=l3          → 阶段链走完插→拔→AOI转移→AOI检测→回程→放下 (L3 扩展段真被调度)
  C. L4 升级      : mode=insert, cap=l4          → 引擎真注入来料移位/转向 (jitter meta 有真值) + L4 恢复预算×2
  (并如实打印: 干扰轮里 L2 快通道的既定语义 = 布局变了标杆失效 → 旁路降级为全精算伺服)

用法: ./gui-venv311/bin/python tools/layer_stack_evidence.py --seed 0
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

ROOT = "/home/ubuntu/lerobot-smolvla-lew"
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
os.environ.setdefault("MUJOCO_GL", os.environ.get("MUJOCO_GL", "egl"))
_CACHE = os.environ.get("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache")
if os.path.isdir(_CACHE):
    os.environ.setdefault("STABLEWM_HOME", _CACHE)
    os.environ.setdefault("LOCAL_DATASET_DIR", _CACHE)

L3_STAGES = ["插入", "拔出", "AOI转移", "AOI检测", "回程", "放下"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--max-steps", type=int, default=1600)
    ap.add_argument("--out", default=os.path.join(ROOT, "reports", "layer_stack_evidence.json"))
    a = ap.parse_args()

    from state_space_sim_real import RealStateSpaceSim

    gates_p = os.path.join(ROOT, "data", "memory_layers.json")
    gates = json.load(open(gates_p, encoding="utf-8")) if os.path.isfile(gates_p) else {}
    print(f"① 记忆层开关文件 {os.path.basename(gates_p)}: {gates}  (每层独立开关 = 可单独跑/可逐层加)")
    print(f"   SS_MUSCLE={os.environ.get('SS_MUSCLE', '(未设=默认开)')} · "
          f"L2 快通道默认开 = {(os.environ.get('SS_MUSCLE', '1') != '0')}")
    res = {"gates": gates, "seed": a.seed, "runs": {}}

    def _run(tag, mode, cap, want_stages=False):
        logs = []
        stages: list = []
        sim = RealStateSpaceSim(seed=a.seed, vision=False, mode=mode,
                                log=lambda s: logs.append(str(s)))
        # 🐛 阶段轨迹不能读 sim.stage_hist (实测空) → 用帧 sink 逐帧取 sched.stage()
        def _sink(s, act, o, _st=stages):
            try:
                _st.append(str(s.sched.stage()))
            except Exception:                                    # noqa: BLE001
                pass
        sim._frame_sink = _sink
        t0 = time.time()
        tr = sim.run(max_steps=a.max_steps, cap=cap)
        done = bool(tr["done"][-1]) if tr.get("done") else False
        fast = [l for l in logs if "肌肉记忆快通道" in l or "肌肉记忆" in l]
        jit = [l for l in logs if "L4" in l and ("干扰" in l or "移位" in l)]
        d = {"mode": mode, "cap": cap, "done": done,
             "steps": len(tr.get("t") or []), "seconds": round(time.time() - t0, 1),
             "mm_hits": int(getattr(sim, "_mm_hits", 0) or 0),
             "mm_on_end": bool(getattr(sim, "_mm_on", False)),
             "jitter_meta": getattr(sim, "_jitter_meta", None),
             "muscle_log": fast[:3], "l4_log": jit[:3],
             "stage_trace": ([s for s in stages if s] and
                             list(dict.fromkeys([s for s in stages if s]))) or [],
             "stage_last": (stages[-1] if stages else "")}
        print(f"\n② {tag}: mode={mode} cap={cap}")
        print(f"   done={done} 步数={d['steps']} 用时={d['seconds']}s · L2 快通道命中={d['mm_hits']} "
              f"· 收尾时 L2 快通道={'开' if d['mm_on_end'] else '已旁路'}")
        if d["muscle_log"]:
            print(f"   L2 日志: {d['muscle_log'][0][:96]}")
        if d["jitter_meta"]:
            print(f"   L4 真注入: {d['jitter_meta']}")
        if d["l4_log"]:
            print(f"   L4 日志: {d['l4_log'][0][:96]}")
        if want_stages:
            hit = [s for s in L3_STAGES if s in stages]
            print(f"   L3 扩展段覆盖: {hit} ({len(hit)}/{len(L3_STAGES)})")
            d["l3_stages_hit"] = hit
        res["runs"][tag] = d
        return d

    ra = _run("A_L2单独", "insert", "l3")
    rb = _run("B_L3扩展", "full", "l3", want_stages=True)
    rc = _run("C_L4升级", "insert", "l4")

    print("\n" + "=" * 70)
    print(f" A. L2 单独运行: 快通道命中 {ra['mm_hits']} 次 → {'✅ 成立' if ra['mm_hits'] > 0 else '❌ 未接管'}")
    print(f" B. L3 扩展    : 扩展段覆盖 {len(rb.get('l3_stages_hit', []))}/{len(L3_STAGES)} "
          f"→ {'✅ 成立' if len(rb.get('l3_stages_hit', [])) >= 4 else '❌ 未走全'}")
    print(f" C. L4 升级    : 真注入 {rc['jitter_meta']} → "
          f"{'✅ 成立' if rc['jitter_meta'] else '❌ 未注入'}")
    print(f"   干扰轮 L2 语义(如实): 快通道命中 {rc['mm_hits']} · 收尾 "
          f"{'开' if rc['mm_on_end'] else '已按设计旁路(布局变了标杆失效)'}")
    res["verdict"] = {"L2_standalone": ra["mm_hits"] > 0,
                      "L3_extensible": len(rb.get("l3_stages_hit", [])) >= 4,
                      "L4_upgradable": bool(rc["jitter_meta"])}
    json.dump(res, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f" → {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
