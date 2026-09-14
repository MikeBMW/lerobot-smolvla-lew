# -*- coding: utf-8 -*-
"""🔬 diag_peg_geom.py — peg 几何/质心 vs 抓取点 (解释 seed2 抓不稳) 2026-09-15

已证: 抓取目标用的是 obs[4:7] = peg **body 原点** (`_stage_target`: pg = self._peg_cur),
而 seed2 反复滑移 16~19mm、seed0/1 不滑。若 body 原点不在 peg 中段(可夹持最优位), 抓在端部
→ 力臂大 → 抬升即滑。本脚本直接读模型: peg 的 collision geom 在 body 系下的位置/尺寸、
质量与质心, 以及抓取锁存瞬间 手/peg头 相对 peg 几何区间的落点。
用法: MUJOCO_GL=egl gui-venv311/bin/python tools/diag_peg_geom.py --seeds 0,1,2
"""
from __future__ import annotations

import argparse
import os
import sys

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
    ap.add_argument("--seeds", default="0,1,2")
    ap.add_argument("--steps", type=int, default=900)
    a = ap.parse_args()
    from state_space_sim_real import RealStateSpaceSim
    sim = RealStateSpaceSim(seed=0, vision=False, mode="insert", log=lambda *x: None)
    m = sim.env.model
    # 找 peg body
    bi = next((i for i in range(m.nbody) if m.body(i).name == "peg"), None)
    print(f"peg body id = {bi}")
    if bi is not None:
        print(f"  mass={float(m.body_mass[bi]):.4f} kg · ipos(质心在 body 系)={np.round(m.body_ipos[bi],5).tolist()}")
        for gid in range(m.ngeom):
            if int(m.geom_bodyid[gid]) == bi:
                print(f"  geom[{gid}] {m.geom(gid).name or '(无名)'} type={int(m.geom_type[gid])} "
                      f"pos={np.round(m.geom_pos[gid],5).tolist()} size={np.round(m.geom_size[gid],5).tolist()}")
    # 关节端点 (若有 free joint 外的)
    for j in range(m.njnt):
        if int(m.jnt_bodyid[j]) == bi:
            print(f"  jnt[{j}] {m.jnt(j).name} type={int(m.jnt_type[j])} "
                  f"pos={np.round(m.jnt_pos[j],5).tolist()}")
    print()
    for sd in [int(x) for x in ap.parse_args().seeds.split(",")]:
        logs: list = []
        sim = RealStateSpaceSim(seed=sd, vision=False, mode="insert",
                                log=lambda *x: logs.append(" ".join(map(str, x))))
        rec = {}
        _o = sim._reset

        def w_reset(seed, _o=_o, _r=rec, _s=sim):
            _o(seed)
            m2, d2 = _s.env.model, _s.env.data
            j = m2.body_jntadr[m2.body("peg").id] if hasattr(m2.body("peg"), "id") else None
            adr = int(m2.jnt_qposadr[j])
            _r["peg_qpos"] = np.round(np.asarray(d2.qpos[adr:adr + 3]), 5).tolist()
        sim._reset = w_reset
        # 抓取锁存瞬间采样: wrap peg_head 与 x
        samples = []
        _ph = sim.peg_head

        def w_ph(_o=_ph, _l=samples, _s=sim):
            v = _o()
            try:
                _l.append((np.asarray(_s.x, float).copy(), np.asarray(v, float).copy()))
            except Exception:
                pass
            return v
        sim.peg_head = w_ph
        tr = sim.run(max_steps=a.steps)
        stg = [str(s).replace("阶段 ", "") for s in (tr.get("stage") or [])]
        gr = np.asarray(tr.get("grasped") or [], float)
        gi = next((i for i, x in enumerate(gr) if x > 0), -1)
        print(f"=== seed{sd} === peg 初始 = {rec.get('peg_qpos')} · 首次 grasped 帧 {gi} "
              f"(阶段 {stg[gi] if 0 <= gi < len(stg) else '?'}) · done={tr.get('done',[False])[-1]}")
        if gi >= 0 and gi < len(samples):
            x, ph = samples[gi]
            print(f"  锁存瞬间 手={np.round(x,5).tolist()} peg头={np.round(ph,5).tolist()} "
                  f"· 头−手={np.round(ph - x,5).tolist()}")
        slips = sum(1 for l in logs if "滑移" in l or "滑脱" in l)
        print(f"  滑移/滑脱事件 {slips} 次")
    return 0


if __name__ == "__main__":
    sys.exit(main())
