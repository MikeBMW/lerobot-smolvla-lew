# -*- coding: utf-8 -*-
"""🔬 diag_slip_cause.py — 抓取滑移的机理取证 (2026-09-15, class-B)

已证: seed2/4/5 反复"滑移 15/16/18mm → 滑脱(19mm) → 回退重抓" (同一处再夹必再滑)。
本脚本逐帧记录: 真实头(site) vs 推断头(x+off0+head_off) 的偏差向量、阶段、杆与治具的接触对、
抬起高度/夹爪开度 → 定位滑移是"被治具蹭到"还是"夹持本身不牢"。
用法: MUJOCO_GL=egl gui-venv311/bin/python tools/diag_slip_cause.py --seeds 5,2,0
"""
from __future__ import annotations

import argparse
import os
import sys
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
for k, v in (("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache"),
             ("LOCAL_DATASET_DIR", "/home/ubuntu/stable-wm-cache"),
             ("INTACT_RUNTIME", "root"), ("INTACT_POLICY", "intact_l4_current"),
             ("OMP_NUM_THREADS", "6")):
    os.environ.setdefault(k, v)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="5,2,0")
    ap.add_argument("--steps", type=int, default=900)
    a = ap.parse_args()
    for sd in [int(x) for x in a.seeds.split(",") if x.strip()]:
        os.environ["SS_MUSCLE_PATH"] = f"/tmp/slip_mem_{os.getpid()}_{sd}.json"
        from state_space_sim_real import RealStateSpaceSim
        logs: list = []
        sim = RealStateSpaceSim(seed=sd, vision=False, mode="insert",
                                log=lambda *x: logs.append(" ".join(map(str, x))))
        env = sim.env
        m, d = env.model, env.data
        gn = {gid: m.body(int(m.geom_bodyid[gid])).name or "(box)" for gid in range(m.ngeom)}
        rec = {"real": [], "inf": [], "stg": [], "jig": [], "z": [], "grip": []}
        _ostep = env.step

        def wstep(act, _o=_ostep, _r=rec, _d=d, _s=sim):
            r = _o(act)
            _r["real"].append(np.asarray(_d.site_xpos[_s._site_ph], float).copy())
            if getattr(_s, "_grasp_off0", None) is not None:
                _inf = np.asarray(_s.x, float) + np.asarray(_s._grasp_off0, float) \
                    + np.asarray(_s.geom.get("head_off", np.zeros(3)), float)
            else:
                _inf = np.full(3, np.nan)
            _r["inf"].append(_inf)
            _r["z"].append(float(_s.x[2]))
            _r["grip"].append(float(_s.gripper))
            _jig = 0
            for ci in range(int(_d.ncon)):
                c = _d.contact[ci]
                n1, n2 = gn.get(int(c.geom1), "?"), gn.get(int(c.geom2), "?")
                if "peg" in (n1, n2) and "box" in (n1, n2):
                    _jig += 1
            _r["jig"].append(_jig)
            return r
        env.step = wstep
        tr = sim.run(max_steps=a.steps)
        stg = [str(x).replace("阶段 ", "") for x in (tr.get("stage") or [])]
        real = np.asarray(rec["real"], float); inf = np.asarray(rec["inf"], float)
        n = min(len(stg), len(real))
        dev = np.linalg.norm(real[:n] - inf[:n], axis=1)
        jig = np.asarray(rec["jig"], float)[:n]
        print(f"\n=== seed{sd} === done={tr.get('done',[False])[-1]} 帧{n}")
        print(f"  真实头↔推断头 偏差: 均值 {np.nanmean(dev)*1000:.1f}mm 最大 {np.nanmax(dev)*1000:.1f}mm"
              f" · 首次 >5mm 帧 {int(np.argmax(dev>0.005)) if np.any(dev>0.005) else -1}")
        print(f"  杆↔治具 接触帧数: {int((jig>0).sum())} / {n} · 阶段分布={dict(Counter(stg[i] for i in range(n) if jig[i]>0).most_common(4))}")
        slips = [l for l in logs if ("滑移" in l or "滑脱" in l)]
        print(f"  滑移/滑脱日志 {len(slips)} 条; 首条前 3 阶段: "
              f"{[l[:28] for l in slips[:3]]}")
        # 滑移发生时是否伴随治具接触
        if np.any(dev > 0.005):
            i0 = int(np.argmax(dev > 0.005))
            w0, w1 = max(0, i0 - 20), min(n, i0 + 20)
            print(f"  首次大偏差前后(帧{w0}-{w1}): 该窗口内 杆↔治具接触帧 {int((jig[w0:w1]>0).sum())}"
                  f" / {w1-w0} · 阶段={sorted(set(stg[w0:w1]))}")
            print(f"  偏差向量 (首次大偏差帧): {(real[i0]-inf[i0])*1000:.2f}mm")
    return 0


if __name__ == "__main__":
    sys.exit(main())
