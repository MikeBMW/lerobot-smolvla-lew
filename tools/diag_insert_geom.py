# -*- coding: utf-8 -*-
"""🔬 diag_insert_geom.py — 插入卡死(27mm)的几何取证 (2026-09-15, 第1条)

已证: seed1/3/8/11 在 depth≈27mm 处顶住 (接触力 0.98), 螺旋+回退都不奏效; seed0/6/7/9 正常插到底。
本脚本逐帧记录插入段的几何量并对比两组:
  · 轴向深度 depth (光模块头到插入终点)      · 侧向偏差 d_perp (头↔孔轴)
  · 竖直偏差 dz (头 z − 孔 z)                · 杆轴 与 孔轴 的夹角 (姿态倾角)
  · 接触力 / |u_sat|                          · 杆体 qpos (自由关节)
用法: MUJOCO_GL=egl gui-venv311/bin/python tools/diag_insert_geom.py --seeds 0,1,3,6
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
    ap.add_argument("--seeds", default="0,1,3,6")
    ap.add_argument("--steps", type=int, default=900)
    a = ap.parse_args()
    for sd in [int(x) for x in a.seeds.split(",") if x.strip()]:
        os.environ["SS_MUSCLE_PATH"] = f"/tmp/geom_mem_{os.getpid()}_{sd}.json"
        from state_space_sim_real import RealStateSpaceSim
        sim = RealStateSpaceSim(seed=sd, vision=False, mode="insert", log=lambda *x: None)
        env = sim.env
        m, d = env.model, env.data
        adr = int(m.jnt_qposadr[int(m.body_jntadr[m.body("peg").id])])
        rec = {"q": [], "ph": [], "hole": [], "f": [], "us": [], "stg": []}
        _ostep = env.step

        def wstep(act, _o=_ostep, _r=rec, _d=d, _adr=adr, _s=sim):
            r = _o(act)
            _r["q"].append(np.asarray(_d.qpos[_adr:_adr + 7], float).copy())
            _r["ph"].append(np.asarray(_s.peg_head(), float).copy())
            _r["hole"].append(np.asarray(_s._hole_p(), float).copy())
            _r["f"].append(float(np.asarray(_s._f_max) if np.ndim(_s._f_max) == 0 else 0.0))
            _r["us"].append(float(np.linalg.norm(np.asarray(getattr(_s, "_u_vec",
                                                                   np.zeros(4)), float)[:3])))
            return r
        env.step = wstep
        # 逐帧深度 (wrap)
        dl: list = []
        _od = sim._insert_depth

        def wd(_o=_od, _l=dl):
            v = _o(); _l.append(None if v is None else float(v)); return v
        sim._insert_depth = wd
        tr = sim.run(max_steps=a.steps)
        stg = [str(x).replace("阶段 ", "") for x in (tr.get("stage") or [])]
        q = np.asarray(rec["q"], float); ph = np.asarray(rec["ph"], float)
        hole = np.asarray(rec["hole"], float)
        n = min(len(q), len(stg))
        ins = [i for i in range(n) if stg[i].startswith("插入")]
        done = bool(tr.get("done", [False])[-1])
        print(f"\n=== seed{sd} === done={done} 插入帧 {len(ins)}")
        if not ins:
            print("  未进入插入段")
            continue
        # 孔轴向: 引擎孔口几何 → 用 box 的 x 轴 (近水平). 用杆轴与 x 轴夹角做倾角代理
        dperp, dz, tilt = [], [], []
        for i in ins:
            # 侧向: 头↔孔 在垂直于孔轴(x)平面上的距离 (y,z)
            _dv = ph[i] - hole[i]
            dperp.append(float(np.linalg.norm(_dv[1:3])))
            dz.append(float(_dv[2]))
            _qw, _qx, _qy, _qz = q[i][3:7]
            # 杆轴 (body 局部 z 或 x?) — 用四元数旋转 (0,0,1) 与 (1,0,0) 都算, 取与 x 更近者
            def rot(v):
                _r = np.array([[1 - 2*(_qy**2+_qz**2), 2*(_qx*_qy-_qw*_qz), 2*(_qx*_qz+_qw*_qy)],
                               [2*(_qx*_qy+_qw*_qz), 1 - 2*(_qx**2+_qz**2), 2*(_qy*_qz-_qw*_qx)],
                               [2*(_qx*_qz-_qw*_qy), 2*(_qy*_qz+_qw*_qx), 1 - 2*(_qx**2+_qy**2)]])
                return _r @ np.asarray(v, float)
            ax = rot([0, 0, 1]); ax2 = rot([1, 0, 0])
            ax = ax if abs(ax[0]) > abs(ax2[0]) else ax2
            ax = ax / (np.linalg.norm(ax) + 1e-9)
            tilt.append(float(np.degrees(np.arccos(np.clip(abs(ax[0]), 0, 1)))))
        dep = np.asarray([dl[i] if i < len(dl) and dl[i] is not None else np.nan for i in ins], float)
        dperp = np.asarray(dperp); dz = np.asarray(dz); tilt = np.asarray(tilt)
        f = np.asarray(rec["f"], float)[:n][ins] if len(rec["f"]) >= n else np.zeros(len(ins))
        print(f"  depth: 起 {dep[0]*1000:.1f}mm 最小 {np.nanmin(dep)*1000:.1f}mm 末 {dep[-1]*1000:.1f}mm")
        print(f"  侧向 d_perp: 均值 {dperp.mean()*1000:.2f}mm 最小 {dperp.min()*1000:.2f}mm 末 {dperp[-1]*1000:.2f}mm")
        print(f"  竖直 dz   : 均值 {dz.mean()*1000:.2f}mm 最小 {dz.min()*1000:.2f}mm 末 {dz[-1]*1000:.2f}mm")
        print(f"  杆轴倾角   : 均值 {tilt.mean():.2f}° 最大 {tilt.max():.2f}° 末 {tilt[-1]:.2f}°")
        if f.size:
            print(f"  接触力    : 峰值 {f.max():.2f} 末 {f[-1]:.2f}")
        # 卡住点(深度最小处)的细节
        j = int(np.nanargmin(dep))
        print(f"  最深点 帧{ins[j]}: depth={dep[j]*1000:.1f}mm d_perp={dperp[j]*1000:.2f}mm "
              f"dz={dz[j]*1000:.2f}mm 倾角={tilt[j]:.2f}° 力={f[j] if f.size else float('nan'):.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
