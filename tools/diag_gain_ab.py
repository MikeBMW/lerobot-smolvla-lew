#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🎚 自适应增益 A/B — base (固定 w=0.3) vs gain (卡尔曼式自适应增益)

每臂独立进程 (老倪纪律: 每臂独立进程 + 同 seed 同场景同起点), 逐 10 步打印进度与步率,
结果落 reports/ab_gain_<arm>_s<seed>.json。

用法:
  SS_PROBE_SEED=0 python tools/diag_gain_ab.py base 60
  SS_PROBE_SEED=0 python tools/diag_gain_ab.py gain 60
先跑 base 再跑 gain (同一 seed 才是同口径对照)。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "src"), os.path.join(ROOT, "tools"),
                os.path.join(ROOT, "tools", "gui")]

ARM = sys.argv[1] if len(sys.argv) > 1 else "base"
STEPS = int(sys.argv[2]) if len(sys.argv) > 2 else 60
SEED = int(os.environ.get("SS_PROBE_SEED", "0"))
OUT = os.environ.get("SS_AB_OUT") or os.path.join(ROOT, "reports", f"ab_gain_{ARM}_s{SEED}.json")


def main() -> int:
    os.environ.setdefault("SS_L4_INTACT", "1")          # L4 意图解码器在链上
    os.environ.setdefault("SS_L4_INTENT_LINE", "1")     # 直连线 (本增益层的上游)
    if ARM == "gain":
        os.environ["SS_ADAPT_GAIN"] = "1"
    else:
        os.environ.pop("SS_ADAPT_GAIN", None)
    print(f"臂={ARM} seed={SEED} steps={STEPS} · SS_ADAPT_GAIN={os.environ.get('SS_ADAPT_GAIN')!r} "
          f"· SS_L4_DIT={os.environ.get('SS_L4_DIT')!r} · SS_MUSCLE={os.environ.get('SS_MUSCLE')!r} "
          f"· SS_MUSCLE_PATH={os.environ.get('SS_MUSCLE_PATH')!r}", flush=True)

    from state_space_sim_real import RealStateSpaceSim
    import probe_l4_callchain as P

    # ⚠️ probe 模块 import 时会 pop/覆盖一批开关 (模块级隔离): SS_L4_INTACT/SS_L3/SS_INTACT
    #    被 pop, SS_MUSCLE/SS_OBSERVE 被写 0 → 必须在 import 之后**重新校准**(否则肌肉记忆被静默关掉)。
    os.environ["SS_L4_INTACT"] = "1"
    os.environ["SS_L4_INTENT_LINE"] = "1"
    os.environ.setdefault("SS_INTACT_EVERY", "1")      # 每步真推理 (L4 路帧数密, A/B 更可比)
    os.environ.pop("SS_MUSCLE", None)                  # ← 肌肉记忆 (L2) 本 A/B 的主角之一
    if ARM == "gain":
        os.environ["SS_ADAPT_GAIN"] = "1"
    else:
        os.environ.pop("SS_ADAPT_GAIN", None)
    print(f"env 校准后: SS_L4_INTACT={os.environ.get('SS_L4_INTACT')!r} "
          f"SS_L4_INTENT_LINE={os.environ.get('SS_L4_INTENT_LINE')!r} "
          f"SS_ADAPT_GAIN={os.environ.get('SS_ADAPT_GAIN')!r} "
          f"SS_INTACT_EVERY={os.environ.get('SS_INTACT_EVERY')!r} "
          f"SS_MUSCLE={os.environ.get('SS_MUSCLE')!r}", flush=True)

    logs: list[str] = []
    sim = RealStateSpaceSim(seed=SEED, vision=False, mode="insert",
                            log=lambda *a: logs.append(" ".join(str(x) for x in a)))
    nd, _stf = P.build_intact_node()
    sim.attach_intact(nd, None)

    # 逐帧进度与势函数 (包 sched.decide: 每步恰好一次)
    #   ⚠️ sched 在 _reset() 里才建 (run() 开头调) → 必须挂在 _reset 之后
    st = {"n": 0, "t0": time.time(), "dist": [], "wrapped": False, "uff": [], "stages": []}

    def _wrap_decide():
        if st["wrapped"]:
            return
        orig = sim.sched.decide

        def dec(u_ff, u_fb, contact_p, r_scalar):
            st["n"] += 1
            if st["n"] == 1 and os.environ.get("SS_AB_DEBUG") == "1":
                print(f"  [DBG] SS_L4_INTACT={os.environ.get('SS_L4_INTACT')!r} · "
                      f"node={getattr(sim, '_intact_node', 'NA') is not None} · "
                      f"stages={getattr(sim, '_l4_stages', None)} · "
                      f"stage()={sim.sched.stage()!r} · in={sim.sched.stage() in (getattr(sim, '_l4_stages', []) or [])} · "
                      f"vision={getattr(sim, 'vision', None)} · mm_on={getattr(sim, '_mm_on', None)} · "
                      f"muscle={getattr(sim, 'muscle', 'NA') is not None} · SS_MUSCLE={os.environ.get('SS_MUSCLE')!r}",
                      flush=True)
            try:
                h = sim.env.data.site_xpos[sim._site_hole]
                st["dist"].append(float(np.linalg.norm(np.asarray(sim.peg_head(), float)[:3]
                                                       - np.asarray(h, float)[:3])))
            except Exception:                                             # noqa: BLE001
                pass
            try:                                   # 🧾 前馈参考逐帧 (被增益改动的就是它)
                st["uff"].append(np.asarray(u_ff, float).ravel()[:3].copy())
                st["stages"].append(str(sim.sched.stage()))
            except Exception:                                             # noqa: BLE001
                pass
            if st["n"] % 10 == 0:
                el = time.time() - st["t0"]
                d = st["dist"][-1] * 1000.0 if st["dist"] else float("nan")
                print(f"  step {st['n']:4d} · {el:6.1f}s · {el / max(1, st['n']):.2f}s/步 · "
                      f"|peg−hole|={d:6.1f}mm", flush=True)
            return orig(u_ff, u_fb, contact_p, r_scalar)

        sim.sched.decide = dec
        st["wrapped"] = True

    _orig_reset = sim._reset

    def _reset_probe(*a, **k):
        r = _orig_reset(*a, **k)
        _wrap_decide()
        return r

    sim._reset = _reset_probe
    t0 = time.time()
    tr = sim.run(max_steps=STEPS)
    dt = time.time() - t0
    n = len(tr.get("stage", []))
    _done = tr.get("done") or []
    out = {
        "arm": ARM, "seed": SEED, "steps": n, "dt": round(dt, 2),
        "s_per_step": round(dt / max(1, n), 3),
        "done": (bool(_done[-1]) if len(_done) else None),
        "stage_dist": {str(s): list(map(str, tr.get("stage", []))).count(str(s))
                       for s in sorted(set(map(str, tr.get("stage", []))))},
        "dist_first_mm": (round(st["dist"][0] * 1000, 2) if st["dist"] else None),
        "dist_min_mm": (round(min(st["dist"]) * 1000, 2) if st["dist"] else None),
        "dist_final_mm": (round(st["dist"][-1] * 1000, 2) if st["dist"] else None),
        "mm_hits": int((tr.get("_meta") or {}).get("mm_hits", 0)),
        "mm_on": bool(getattr(sim, "_mm_on", False)),
        "mm_champ_loaded": bool(getattr(sim, "_mm_u", None) is not None),
        "il": (tr.get("_meta") or {}).get("il_summary") or sim.l4_intent_line_summary(),
        "gain": sim.gain_summary(),
        "gain_log": [x for x in logs if "增益" in x][:4],
        "mm_log": [x for x in logs if "肌肉记忆" in x][:3],
        "l4_stats": {k: (v if not isinstance(v, list) else (round(float(np.mean(v)), 5) if v else None))
                     for k, v in (getattr(sim, "_l4_stats", {}) or {}).items() if k != "shift"},
        "intact_stats": {k: (v if not isinstance(v, list) else (round(float(np.mean(v)), 5) if v else None))
                         for k, v in (getattr(sim, "_intact_stats", {}) or {}).items()},
        "logs": logs[-14:],
    }
    # 🧾 前馈参考统计 (增益实际改动的东西) + 逐位 hash (臂间比对的仪器)
    try:
        _u = np.asarray(st["uff"], float)
        if _u.size:
            out["uff_mean_norm"] = round(float(np.mean(np.linalg.norm(_u, axis=1))), 5)
            out["uff_last"] = [round(float(v), 5) for v in _u[-1]]
            out["uff_hash"] = hashlib.sha256(np.ascontiguousarray(_u, np.float64).tobytes()).hexdigest()[:16]
            _byst: dict = {}
            for _s, _vv in zip(st["stages"], _u):
                _byst.setdefault(_s, []).append(_vv)
            out["uff_stage_mean_norm"] = {k: round(float(np.mean(np.linalg.norm(np.asarray(v), axis=1))), 5)
                                          for k, v in _byst.items()}
            out["uff_nonzero_frames"] = int(np.sum(np.linalg.norm(_u, axis=1) > 1e-9))
    except Exception as _e:                                                   # noqa: BLE001
        out["uff_err"] = f"{type(_e).__name__}: {_e}"
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({k: out[k] for k in ("arm", "seed", "steps", "dt", "s_per_step", "done",
                                          "dist_first_mm", "dist_min_mm", "dist_final_mm",
                                          "mm_hits", "stage_dist")}, ensure_ascii=False), flush=True)
    print("gain_summary: " + json.dumps(out["gain"], ensure_ascii=False), flush=True)
    _il = out["il"] or {}
    print("il: " + json.dumps({k: _il.get(k) for k in ("enabled", "frames", "ran", "applied",
                                                       "w_zero", "refused", "ready", "w_last",
                                                       "by_stage")}, ensure_ascii=False), flush=True)
    print(f"落盘 {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
