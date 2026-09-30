# -*- coding: utf-8 -*-
"""🔬 diag_coupling_isolate.py — 定位"L4 推理污染引擎物理"的具体调用 (2026-09-15)

实测: 两臂 act 逐位相同、step 前状态逐位相同, 但 step 后状态不同 (arm B 的 peg 在 y 上瞬移
17mm、z 冻结) → 环境 data 被**外部调用**改过。候选: ①_render_frame ②_l4_skill_ctx
③_l4_l2_proc ④node.step(INTACT 真推理)。
本脚本在**同一次 reset 后逐个调用**并检查 peg qpos 是否被改。
用法: MUJOCO_GL=egl gui-venv311/bin/python tools/diag_coupling_isolate.py --seed 1
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
os.environ.setdefault("SS_MUSCLE_PATH", "/tmp/ab_mem_iso_%d.json" % os.getpid())


def snap(sim):
    m, d = sim.env.model, sim.env.data
    adr = int(m.jnt_qposadr[int(m.body_jntadr[m.body("peg").id])])
    return np.asarray(d.qpos.copy(), float), adr


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    from state_space_sim_real import RealStateSpaceSim
    from lerobot.manifold.intact_node import IntactNode, IntactRuntime
    sim = RealStateSpaceSim(seed=a.seed, vision=False, mode="insert", log=lambda *x: None)
    node = IntactNode(horizon=8, runtime=IntactRuntime(task="pusht", device="cpu"))
    sim.attach_intact(node)
    sim._reset(a.seed)
    q0, adr = snap(sim)
    print(f"reset 后 peg qpos = {q0[adr:adr+3].round(6).tolist()}")

    def chk(tag):
        q, _ = snap(sim)
        d = np.abs(q - q0).max()
        peg = q[adr:adr + 3] - q0[adr:adr + 3]
        print(f"  调用 {tag:24s} → qpos 最大变化 {d:.6f} · peg Δ={np.round(peg,6).tolist()}"
              f"{'  ← 污染!' if d > 1e-9 else ''}")
        return d

    import cv2
    fr = None
    try:
        _r = np.asarray(sim._render_frame())
        if _r.ndim == 3 and _r.shape[0] in (1, 3, 4) and _r.shape[-1] not in (3, 4):
            _r = _r.transpose(1, 2, 0)
        fr = cv2.resize(np.ascontiguousarray(_r.astype(np.float32)), (224, 224),
                        interpolation=cv2.INTER_AREA).transpose(2, 0, 1)
        chk("_render_frame+résize")
    except Exception as e:                                              # noqa: BLE001
        print(f"  渲染失败 {type(e).__name__}: {e}")
    try:
        sk = sim._l4_skill_ctx("接近")
        chk(f"_l4_skill_ctx(dim={np.asarray(sk).size})")
    except Exception as e:                                              # noqa: BLE001
        print(f"  skill_ctx 失败 {type(e).__name__}: {e}")
    try:
        sim._l4_l2_proc()
        chk("_l4_l2_proc")
    except Exception as e:                                              # noqa: BLE001
        print(f"  l2_proc 失败 {type(e).__name__}: {e}")
    if fr is not None:
        try:
            _sk = sim._l4_skill_ctx("接近")
            out = node.step(fr, obs_source="engine_render", skill_ctx=_sk)
            chk(f"node.step(INTACT 真推理) chunk={np.asarray(out.chunk).shape}")
            out2 = node.step(fr, obs_source="engine_render", skill_ctx=_sk)
            chk("node.step 第二次")
        except Exception as e:                                          # noqa: BLE001
            print(f"  node.step 失败 {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
