#!/usr/bin/env python3
"""collect_simreal_teacher_data.py — sim_real 固定布局教师轨迹采集 (2026-09-07 静静)

背景: 大会战学生 (mw3, 随机多布局蒸馏) 在 sim_real 固定布局下前段 0/8 全盲
(卡接近/对位, 技能坑6 实锤)。根治 = 把 sim_real 布局的成功教师轨迹并入训练集
融合重训, 学生覆盖固定布局域 → R0 前段 MLP 真实执行 (解除强解析)。

本脚本: RealStateSpaceSim(seed, 解析教师默认) 跑成功轮 → 存 raw npz
(字段对齐 collect_mw_teacher_data.py: obs43/u_ff_vec/u_exec_vec/stage/force/
grasped/contact_p + meta), 可直接落入 data/ss_mw_raw 走 convert/build 管道。

用法: MUJOCO_GL=egl gui-venv311/bin/python tools/collect_simreal_teacher_data.py 100 8
"""
import argparse
import os
import sys
import time

os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("MUJOCO_EGL_DEVICE", "0")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))

import numpy as np  # noqa: E402
from state_space_sim_real import RealStateSpaceSim  # noqa: E402

OUT = os.path.join(ROOT, "data", "ss_simreal_raw")
os.makedirs(OUT, exist_ok=True)


def _clean_stage(s):
    return str(s).replace("阶段 ", "").split(" · ")[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("seed_base", type=int, nargs="?", default=100)
    ap.add_argument("n", type=int, nargs="?", default=8)
    a = ap.parse_args()

    ok, fail = [], []
    for sd in range(a.seed_base, a.seed_base + a.n):
        t0 = time.time()
        sim = RealStateSpaceSim(seed=sd, vision=False, log=lambda *m: None)
        tr = sim.run()
        done = bool(tr["done"][-1])
        stages = [_clean_stage(s) for s in tr["stage"]]
        chain = "→".join(dict.fromkeys(stages))
        if done:
            meta = {"seed": sd, "success": True, "steps": len(tr["t"]),
                    "stage_final": stages[-1], "analytic": True}
            arrs = {
                "obs": np.asarray(tr["obs"], dtype=np.float32),
                "u_ff_vec": np.asarray(tr["u_ff_vec"], dtype=np.float32),
                "u_exec_vec": np.asarray(tr["u_exec_vec"], dtype=np.float32),
                "stage": np.asarray(stages, dtype=object),
                "force": np.asarray(tr["force"], dtype=np.float32),
                "grasped": np.asarray(tr["grasped"], dtype=bool),
                "contact_p": np.asarray(tr["contact_p"], dtype=np.float32),
                "u_sat_vec": np.asarray(tr["u_sat_vec"], dtype=np.float32),
            }
            np.savez_compressed(os.path.join(OUT, f"s{sd:03d}.npz"),
                                meta=np.array([meta], dtype=object), **arrs)
            ok.append(sd)
            print(f"seed {sd:3d}: ✅ {len(tr['t']):>4d}步 {chain}  {time.time()-t0:>4.0f}s", flush=True)
        else:
            fail.append(sd)
            print(f"seed {sd:3d}: ❌ {len(tr['t']):>4d}步 止于{stages[-1]} [{chain}]", flush=True)
    print(f"\n=== sim_real 教师采集: {len(ok)} 成功 / {len(ok)+len(fail)} · 成功 seed {ok}")
    print(f"数据目录: {OUT}  (下一步: 复制进 data/ss_mw_raw 融合或单独走 convert/build)")


if __name__ == "__main__":
    main()
