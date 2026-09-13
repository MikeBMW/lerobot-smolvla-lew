# -*- coding: utf-8 -*-
"""🧲 记忆势场单独驱动探针 (纯肌肉记忆, 不看模型) — 定位"场为什么推不到位"。

为什么需要它 (2026-09-14 阶梯增益调度的实测): 场权从 0.1 提到 0.75~0.81 后, 插入距离 649→431mm
(真的动了 220mm), 但离成功线 65mm 还差很远, 且 1000 步只走 220mm ⇒ 要分清是
  ① 场的方向/目标不对 ② 场的步长太小 (intent.step_m 语义) ③ 抓取/对位阶段没走通 (臂动=距离不变)
所以把模型摘掉: **每步直接 u = 场自己输出 (w=1.0)**, 每 50 步打印 现场几何 + 阶段 + 距离, 看到底卡在哪。

用法: gui-venv311/bin/python tools/mem_field_probe.py --seed 0 --steps 1000 [--disturb]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

ROOT = "/home/ubuntu/lerobot-smolvla-lew"
GATES = os.path.join(ROOT, "data", "memory_layers.json")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--steps", type=int, default=1000)
    ap.add_argument("--mode", default="insert")
    ap.add_argument("--disturb", action="store_true", help="开 = cap=l4 真注入干扰")
    ap.add_argument("--layers", default="L2", help="开哪几层 (逗号): L2,L3,L4,assembly")
    a = ap.parse_args()

    saved = json.load(open(GATES, encoding="utf-8")) if os.path.isfile(GATES) else {}
    on = {k.strip(): 1 for k in a.layers.split(",") if k.strip()}
    g = {"L2": 0, "L3": 0, "L4": 0, "assembly": 0}
    for k in on:
        g[k] = 1
    g["updated"] = time.strftime("%F %T")
    json.dump(g, open(GATES, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"记忆开关 → {g} (跑完还原 {saved})")

    sys.path.insert(0, os.path.join(ROOT, "src"))
    sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
    import numpy as np
    os.environ.setdefault("MUJOCO_GL", "egl")
    from state_space_sim_real import RealStateSpaceSim, K_ACT          # noqa: PLC0415
    from lerobot.memory.potential_field import MemoryLayerBridge      # noqa: PLC0415

    br = MemoryLayerBridge.from_real_data(ROOT)
    print(f"势场: 开关 {br.gates()} · 技能场 {[f.code for f in br.fields]} · {br.reason}")
    cap = "l4" if a.disturb else "l3"
    sim = RealStateSpaceSim(seed=a.seed, vision=False, mode=a.mode, log=lambda *x: None)
    rows = []
    step = [0]

    def _sink(s, act, o):
        # 纯场驱动: u = 场输出 (w=1.0) 直接下发
        # 与冠军轨迹同源的状态 = 引擎 self.x = obs[0:3] (夹爪真实位置)
        x = np.asarray(o, float).ravel()[:3]
        u = np.zeros(4, np.float64)
        u[3] = 0.0
        try:
            u2, info = br.blend_action(u, x, None, w_max=1.0, k_act=K_ACT, w_floor=1.0)
            s._direct_act = u2
            if step[0] == 0:
                try:
                    _acts = [f for f in br.fields]
                    _f = _acts[0] if _acts else None
                    if _f is not None:
                        print(f"   坐标系对照: 现场 peg_head={np.round(x, 4).tolist()} "
                              f"hole={np.round(np.asarray(s.geom['hole'], float)[:3], 4).tolist()} "
                              f"goal={np.round(np.asarray(s.geom['goal'], float)[:3], 4).tolist()}")
                        print(f"                场({_f.code}) P首={np.round(_f.P[0], 4).tolist()} "
                              f"P末={np.round(_f.P[-1], 4).tolist()} x_g={np.round(_f.x_g, 4).tolist()} "
                              f"sigma={_f.sigma:.4f} v_cap={_f.v_cap}")
                except Exception as _e:                                 # noqa: BLE001
                    print(f"   坐标系对照失败: {type(_e).__name__}: {_e}")
            if step[0] % 50 == 0 or step[0] < 3:
                d_hole = float(np.linalg.norm(x[:2] - np.asarray(s.geom["hole"], float)[:2]))
                d_goal = float(np.linalg.norm(x - np.asarray(s.geom["goal"], float)))
                _h = None
                try:                                                    # 手爪 (末端) 真位置
                    _h = [round(float(v), 4) for v in s.env.get_endeff_pos()[:3]]
                except Exception:                                       # noqa: BLE001
                    try:
                        _h = [round(float(v), 4) for v in s.env.data.site_xpos[s._site_hole][:3]]
                    except Exception:                                   # noqa: BLE001
                        _h = None
                rows.append({"step": step[0], "peg": [round(float(v), 4) for v in x], "ee": _h,
                             "d_hole_m": round(d_hole, 4), "d_goal_m": round(d_goal, 4),
                             "w": info.get("w"), "d_perp_m": info.get("d_perp_m"),
                             "skill": info.get("skill"), "u": [round(float(v), 4) for v in u2],
                             "u_field": info.get("u_field"), "stage": info.get("stage")})
        except Exception as e:                                          # noqa: BLE001
            rows.append({"step": step[0], "err": f"{type(e).__name__}: {e}"})
            s._direct_act = np.array([0.0, 0.0, 0.0, -1.0])
        step[0] += 1

    sim._frame_sink = _sink
    sim._direct_act = np.array([0.0, 0.0, 0.0, -1.0])
    t0 = time.time()
    tr = sim.run(max_steps=a.steps, cap=cap)
    _d = tr.get("done")
    done = bool(_d[-1]) if (_d is not None and len(_d)) else False
    ins = round(float(tr["dist"][-1]) * 1000, 2) if tr.get("dist") else None
    print(f"\n== 纯场驱动结果: done={done} 插入距离={ins}mm 步数={len(tr.get('t') or [])} "
          f"{round(time.time() - t0, 1)}s · cap={cap}")
    print(f"   sink 调用 {step[0]} 次 (步数={len(tr.get('t') or [])}) · tr keys={sorted(tr.keys())}")
    import numpy as _np
    for kk in ("peg", "x", "hand", "dist", "grip"):
        v = tr.get(kk)
        if v is None or not hasattr(v, "__len__") or len(v) == 0:
            continue
        try:
            _arr = _np.asarray(v, float)
            print(f"   tr[{kk}] shape={_arr.shape} 首={_np.round(_arr[0], 4).tolist()} "
                  f"末={_np.round(_arr[-1], 4).tolist()} 变化={float(_np.abs(_arr[-1] - _arr[0]).max()):.4f}")
        except Exception as e:                                        # noqa: BLE001
            print(f"   tr[{kk}] {type(v)} {str(v)[:80]}")
    print(f"{'step':>5}{'d_hole(m)':>11}{'d_goal(m)':>11}{'d_perp':>8}{'w':>7}  u_field / u_out / 技能")
    for r in rows:
        if r.get("err"):
            print(f"{r['step']:>5}  ERR {r['err']}")
            continue
        print(f"{r['step']:>5}{r['d_hole_m']:>11.4f}{r['d_goal_m']:>11.4f}"
              f"{str(r['d_perp_m']):>8}{str(r['w']):>7}  {r['u_field']} / {r['u']} / {r['skill']}")
    out = os.path.join(ROOT, "reports", f"mem_field_probe_s{a.seed}_{'disturb' if a.disturb else 'clean'}.json")
    json.dump({"seed": a.seed, "steps": a.steps, "cap": cap, "gates": g, "done": done, "insert_mm": ins,
               "trace": rows, "disturb": getattr(sim, "_jitter_meta", None),
               "ts": time.strftime("%F %T")}, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"→ {os.path.relpath(out, ROOT)}")
    if saved:
        json.dump(saved, open(GATES, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"记忆开关已还原 {saved}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
