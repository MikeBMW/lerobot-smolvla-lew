# -*- coding: utf-8 -*-
"""🔬 diag_grasp_seed.py — seed2 抓取滑移取证 (2026-09-15)

已证: 解析链 900 步下 seed0/seed1 完成, **seed2 唯一失败** —— 滑移 16~19mm/滑脱 10 次,
插入段仅 9 帧、螺旋 0 次 (从未真插)。夹持闭合量加大反而更差 ⇒ 疑"抓取点/初始位姿差"。
本脚本对 3 个 seed 记录: ①reset 后 peg 初始位姿(位置+四元数→等效 yaw) ②抓取锁存偏移
_grasp_off0 ③抓取时夹爪开度 ④滑移事件首次发生阶段/帧 ⑤插入段 depth 轨迹最小。
用法: MUJOCO_GL=egl gui-venv311/bin/python tools/diag_grasp_seed.py --seeds 0,1,2 --steps 900
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
os.environ.pop("SS_L4_INTACT", None)
os.environ.pop("SS_L4_INTENT_LINE", None)


def free_joint_qpos(env):
    m, d = env.model, env.data
    for i in range(m.nbody):
        j = m.body_jntadr[i]
        if j >= 0 and m.jnt_type[j] == 0:
            a = m.jnt_qposadr[j]
            return np.asarray(d.qpos[a:a + 7], float).copy(), m.body(i).name
    return None, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="0,1,2")
    ap.add_argument("--steps", type=int, default=900)
    a = ap.parse_args()
    for sd in [int(x) for x in a.seeds.split(",") if x.strip()]:
        from state_space_sim_real import RealStateSpaceSim
        logs: list = []
        sim = RealStateSpaceSim(seed=sd, vision=False, mode="insert",
                               log=lambda *x: logs.append(" ".join(map(str, x))))
        rec = {}
        _o_reset = sim._reset

        def w_reset(seed, _o=_o_reset, _r=rec, _s=sim):
            _o(seed)
            q, nm = free_joint_qpos(_s.env)
            if q is not None:
                qw, qz = float(q[3]), float(q[6])
                yaw = 2.0 * np.arctan2(qz, qw)
                _r["peg0"] = np.round(q[:3], 5).tolist()
                _r["peg0_yaw_deg"] = round(float(np.degrees(yaw)), 2)
                _r["peg_body"] = nm
        sim._reset = w_reset
        _o_depth = sim._insert_depth
        dl: list = []

        def w_depth(_o=_o_depth, _l=dl):
            v = _o()
            _l.append(None if v is None else float(v))
            return v
        sim._insert_depth = w_depth
        tr = sim.run(max_steps=a.steps)
        stg = [str(s).replace("阶段 ", "") for s in (tr.get("stage") or [])]
        arr = np.asarray([np.nan if x is None else x for x in dl], float) if dl else np.zeros(0)
        slip_logs = [l for l in logs if ("滑移" in l or "滑脱" in l or "感知偏差" in l)]
        first_slip_stage = stg[0] if not stg else "?"
        # 找首个滑移事件发生时的阶段 (按日志顺序近似: 用阶段区间中点)
        gr = np.asarray(tr.get("grasped") or [], float)
        print(f"\n=== seed{sd} === done={tr.get('done',[False])[-1]} 步数={len(stg)}")
        print(f"  peg 初始位姿 = {rec.get('peg0')} · 等效 yaw = {rec.get('peg0_yaw_deg')}° "
              f"(body={rec.get('peg_body')})")
        print(f"  夹持锁存偏移 _grasp_off0 = "
              f"{None if sim._grasp_off0 is None else np.round(sim._grasp_off0, 5).tolist()}")
        print(f"  抓取后夹爪开度范围 = [{float(np.min(gr)):.2f}, {float(np.max(gr)):.2f}] "
              f"(峰值{f'={GRASP_SAT}' if False else ''}) · grasped 帧数={int(np.sum(gr > 0))}")
        print(f"  插入 depth 最小 = {np.nanmin(arr)*1000:.2f}mm · 末值 {np.nanmax(arr[[-1]])*1000:.2f}mm")
        print(f"  滑移/滑脱/偏差日志 {len(slip_logs)} 条:")
        for l in slip_logs[:8]:
            print(f"    · {l[:130]}")
        # 滑移发生帧估算: 从 "滑移" 日志出现顺序对应 grasped 起
        gi = next((i for i, x in enumerate(gr) if x > 0), -1)
        print(f"  首次 grasped 帧 = {gi} · 该帧阶段 = {stg[gi] if 0 <= gi < len(stg) else '?'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
