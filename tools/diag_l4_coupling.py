# -*- coding: utf-8 -*-
"""🔬 diag_l4_coupling.py — 定位"L4 空转却改变执行"的隐性耦合 (2026-09-15)

实测 (冷记忆, 独立进程 ×2 可复现): seed1/2 上
  analytic = l4_attach_only = done False;  gate_on = done True
而 gate_on 的 gate_pass=0 (所有 L4 提案被闸否决) → u_ff 应等于解析链 → 结果不该变。
本脚本把某一臂的逐帧 x/阶段/u 存 npz, 供两臂 diff 找**首个分叉帧**。
用法: MUJOCO_GL=egl gui-venv311/bin/python tools/diag_l4_coupling.py --arm analytic --out /tmp/a.npz
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
os.environ.setdefault("SS_MUSCLE_PATH", "/tmp/ab_mem_diag_%d.json" % os.getpid())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", default="analytic")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--steps", type=int, default=900)
    ap.add_argument("--out", default="/tmp/trace.npz")
    a = ap.parse_args()
    if a.arm != "analytic":
        os.environ["SS_L4_INTACT"] = "1"
        os.environ["SS_L4_INTACT_GATE"] = "1"
    from state_space_sim_real import RealStateSpaceSim
    from lerobot.manifold.intact_node import IntactNode, IntactRuntime
    sim = RealStateSpaceSim(seed=a.seed, vision=False, mode="insert", log=lambda *x: None)
    sim.attach_intact(IntactNode(horizon=8, runtime=IntactRuntime(task="pusht", device="cpu")))
    # 记录 peg(qpos/qvel) 与 env.step 计数 (查两臂物理为何第1帧就分叉)
    _env = sim.env
    _m, _d = _env.model, _env.data
    _adr = int(_m.jnt_qposadr[int(_m.body_jntadr[_m.body("peg").id])])
    _vadr = int(_m.jnt_dofadr[int(_m.body_jntadr[_m.body("peg").id])])
    _rec = {"pegq": [], "pegv": [], "nstep": [0], "nsite": []}
    _ostep = _env.step

    def _wstep(act, _o=_ostep, _r=_rec, _d=_d, _a=_adr, _v=_vadr):
        _r.setdefault("acts", []).append(np.asarray(act, float).copy())
        _r.setdefault("qpos_all", []).append(np.asarray(_d.qpos, float).copy())
        r = _o(act)
        _r.setdefault("qpos_after", []).append(np.asarray(_d.qpos, float).copy())
        _r["nstep"][0] += 1
        _r["pegq"].append(np.asarray(_d.qpos[_a:_a + 3], float).copy())
        _r["pegv"].append(np.asarray(_d.qvel[_v:_v + 3], float).copy())
        _r["nsite"].append(np.asarray(_d.site_xpos[sim._site_ph], float).copy())
        return r
    _env.step = _wstep
    tr = sim.run(max_steps=a.steps)

    def arr(k, d=4):
        v = [x for x in tr.get(k) or [] if x is not None]
        return np.asarray(v, float).reshape(len(v), -1)[:, :d] if v else np.zeros((0, d))
    stg = np.asarray([str(s).replace("阶段 ", "") for s in (tr.get("stage") or [])])
    np.savez_compressed(
        a.out, x=np.asarray(tr.get("x") or [], float).reshape(-1, 3),
        peg_head=np.asarray(tr.get("peg_head") or [], float).reshape(-1, 3),
        u_ff=arr("u_ff_vec"), u_exec=arr("u_exec_vec"), stage=stg,
        u_sat=arr("u_sat_vec"), u_fuse=arr("u_fuse_vec"), u_fb=arr("u_fb_vec"),
        u_limit=arr("u_limit_vec"), resid=arr("residual"), cp=arr("contact_p", 1),
        grasped=arr("grasped", 1), force=arr("force", 1),
        gate=np.asarray([sim.l4_intact_summary().get("l2_veto") or 0,
                         sim.l4_intact_summary().get("gate_pass") or 0,
                         sim.l4_intact_summary().get("blend") or 0], float),
        done=np.asarray([bool(tr.get("done", [False])[-1])]),
        pegq=np.asarray(_rec["pegq"], float).reshape(-1, 3),
        pegv=np.asarray(_rec["pegv"], float).reshape(-1, 3),
        nsite=np.asarray(_rec["nsite"], float).reshape(-1, 3),
        nstep=np.asarray([_rec["nstep"][0]], float),
        acts=np.asarray(_rec.get("acts", []), float),
        qpos_pre=np.asarray(_rec.get("qpos_all", []), float),
        qpos_post=np.asarray(_rec.get("qpos_after", []), float))
    print(f"{a.arm}: 帧数={len(stg)} done={bool(tr.get('done',[False])[-1])} → {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
