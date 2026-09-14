# -*- coding: utf-8 -*-
"""🔬 diag_insert_contact.py — 卡死点到底被谁挡住 (读 mj 接触对) (2026-09-15)

已证: 卡死 seed 在 depth≈27mm 处 头(−14mm 半径 15mm) 停在孔轴上方 11~17mm、接触力 0.98;
成功 seed 同深度偏差仅 0.14mm。本脚本在插入段读 `env.data.contact` 真接触对 (geom 名/法向力),
把"被谁挡住"从推测变成实测。
用法: MUJOCO_GL=egl gui-venv311/bin/python tools/diag_insert_contact.py --seeds 0,1,3
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
    ap.add_argument("--seeds", default="0,1,3")
    ap.add_argument("--steps", type=int, default=900)
    a = ap.parse_args()
    for sd in [int(x) for x in a.seeds.split(",") if x.strip()]:
        os.environ["SS_MUSCLE_PATH"] = f"/tmp/ct_mem_{os.getpid()}_{sd}.json"
        from state_space_sim_real import RealStateSpaceSim
        sim = RealStateSpaceSim(seed=sd, vision=False, mode="insert", log=lambda *x: None)
        env = sim.env
        m, d = env.model, env.data
        gname = {}
        for gid in range(m.ngeom):
            bn = m.body(int(m.geom_bodyid[gid])).name or "(无名box)"
            gname[gid] = f"{bn}#{gid}"
        rec = {"pairs": [], "depth": [], "stg": [], "phz": [], "holez": []}
        _ostep = env.step

        def wstep(act, _o=_ostep, _r=rec, _d=d, _s=sim, _m=m):
            r = _o(act)
            prs = []
            for ci in range(int(_d.ncon)):
                c = _d.contact[ci]
                g1, g2 = int(c.geom1), int(c.geom2)
                try:
                    f = float(np.linalg.norm(_d.efc_force[_d.efc_address[ci]]
                                             if False else 0.0))       # 力需另算, 这里先记接触对
                except Exception:
                    f = 0.0
                prs.append((min(g1, g2), max(g1, g2)))
            _r["pairs"].append(prs)
            _r["phz"].append(float(_s.peg_head()[2]))
            _r["holez"].append(float(_s._hole_p()[2]))
            return r
        env.step = wstep
        dl: list = []
        _od = sim._insert_depth

        def wd(_o=_od, _l=dl):
            v = _o(); _l.append(None if v is None else float(v)); return v
        sim._insert_depth = wd
        tr = sim.run(max_steps=a.steps)
        stg = [str(x).replace("阶段 ", "") for x in (tr.get("stage") or [])]
        n = min(len(stg), len(rec["pairs"]))
        ins = [i for i in range(n) if stg[i].startswith("插入")]
        print(f"\n=== seed{sd} === done={tr.get('done',[False])[-1]} 插入帧 {len(ins)}")
        if not ins:
            print("  未进入插入段"); continue
        cnt = Counter()
        for i in ins:
            for p in rec["pairs"][i]:
                cnt[(gname.get(p[0], str(p[0])), gname.get(p[1], str(p[1])))] += 1
        print("  插入段接触对 (按帧数):")
        for (g1, g2), c in cnt.most_common(10):
            print(f"    {c:5d} 帧 · {g1} ↔ {g2}")
        j = int(np.nanargmin([dl[i] if i < len(dl) and dl[i] is not None else np.nan for i in ins]))
        ji = ins[j]
        print(f"  最深点 帧{ji}: depth={dl[ji]*1000:.1f}mm 头z={rec['phz'][ji]:.4f} 孔z={rec['holez'][ji]:.4f} "
              f"Δz={(rec['phz'][ji]-rec['holez'][ji])*1000:+.2f}mm")
        print(f"    该帧接触对: {[ (gname.get(p[0]), gname.get(p[1])) for p in rec['pairs'][ji] ]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
