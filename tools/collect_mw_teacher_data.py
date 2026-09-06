#!/usr/bin/env python3
"""collect_mw_teacher_data.py — 解析教师多布局采集 → 真实 metaworld 43D 数据 (2026-09-06)

老倪大会战: 状态空间全部模型端到端真实化。蒸馏范式: 教师(解析律, 域外全局稳定)在
真实 metaworld 多 seed 布局跑完整插拔 → 采集 (43D obs, u_ff 教师建议, stage, force,
grasped, contact_p) → 学生(左脑 MLP / 右脑 WM)重训覆盖多布局域 → 解除 R0 强解析。

输出: data/ss_mw_raw/s{seed:03d}.npz — 每成功 seed 一个 (obs43/act4/力/阶段全量)
用法: MUJOCO_GL=egl gui-venv311/bin/python tools/collect_mw_teacher_data.py [n_seeds]
"""
import argparse
import importlib.util
import os
import sys
import time

os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("MUJOCO_EGL_DEVICE", "0")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))

import numpy as np  # noqa: E402

_gen_path = os.path.join(ROOT, "tools", "gen_ss_metaworld_episode.py")
spec = importlib.util.spec_from_file_location("gen_mw", _gen_path)
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)

OUT = os.path.join(ROOT, "data", "ss_mw_raw")
os.makedirs(OUT, exist_ok=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("n_seeds", type=int, nargs="?", default=24)
    ap.add_argument("--start", type=int, default=0)
    a = ap.parse_args()

    ok, fail = [], []
    for sd in range(a.start, a.start + a.n_seeds):
        t0 = time.time()
        try:
            tr, meta, _ = gen.run_episode(sd, want_video=False, analytic=True)
        except Exception as e:
            print(f"seed {sd:3d}: ❌ 异常 {str(e)[:100]}", flush=True)
            fail.append(sd)
            continue
        stages = [s.replace("阶段 ", "").split(" · ")[0] for s in tr["stage"]]
        chain = "→".join(dict.fromkeys(stages))
        if meta["success"]:
            arrs = {k: np.asarray(v, dtype=object if k == "stage" else float)
                    for k, v in tr.items() if k not in ("meta",)}
            np.savez_compressed(os.path.join(OUT, f"s{sd:03d}.npz"),
                                meta=np.array([meta], dtype=object), **arrs)
            ok.append(sd)
            print(f"seed {sd:3d}: ✅ {meta['steps']:>4d}步 {chain}  "
                  f"{time.time()-t0:>4.0f}s", flush=True)
        else:
            fail.append(sd)
            print(f"seed {sd:3d}: ❌ {meta['steps']:>4d}步 止于{meta['stage_final']} "
                  f"[{chain}]", flush=True)
    print(f"\n=== 采集完成: {len(ok)} 成功 / {len(ok)+len(fail)} · 成功 seed {ok} ===")
    print(f"数据目录: {OUT}")


if __name__ == "__main__":
    main()
