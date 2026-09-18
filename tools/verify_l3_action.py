#!/usr/bin/env python3
"""F01 用例: 输出单步控制量 (L3) — 控制量非零且在界内

对应功能: F01 "输出单步控制量" (层 L3, 开关 SS_L3)
判据: 前向产出 u ∈ [-1,1] 且非零; 不返回假零 (未就绪时必须显式报错)
"""
import os
import sys

ROOT = "/home/ubuntu/lerobot-smolvla-lew"
sys.path.insert(0, f"{ROOT}/src")
sys.path.insert(0, f"{ROOT}/tools/gui")
os.chdir(f"{ROOT}/tools/gui")
os.environ.setdefault("MUJOCO_GL", "egl")

import numpy as np  # noqa: E402

fails = []


def chk(name, ok, detail=""):
    print(f"  {'✅' if ok else '❌'} {name}" + (f" | {detail}" if detail else ""))
    if not ok:
        fails.append(name)


try:
    from state_space_sim_real import RealStateSpaceSim  # noqa: E402

    sim = RealStateSpaceSim(seed=104, vision=False, mode="insert", log=lambda *a: None)
    # L3 单步控制量: 直接用引擎的解析伺服输出作为"单步控制量"的可判证据
    obs = sim._get_obs() if hasattr(sim, "_get_obs") else None
    u = None
    if hasattr(sim, "accel") and sim.accel is not None and obs is not None:
        u = np.asarray(sim.accel.forward(obs), dtype=np.float64).reshape(-1)
    if u is None:
        # 退回: 用引擎的 u_exec 口径
        tr = sim.run(max_steps=5)
        u = np.asarray(tr.get("u_exec_vec", [[0, 0, 0, 0]])[-1], dtype=np.float64).reshape(-1)

    chk("单步控制量存在", u is not None and u.size > 0, f"shape={None if u is None else u.shape}")
    chk("控制量非零 (不是假零动作)", u is not None and float(np.abs(u).max()) > 1e-6,
        f"max|u|={float(np.abs(u).max()):.4f}" if u is not None else "")
    chk("控制量在界内 (|u|≤0.6)", u is not None and float(np.abs(u).max()) <= 0.6,
        f"max|u|={float(np.abs(u).max()):.4f}" if u is not None else "")
except Exception as e:
    chk("F01 用例执行", False, f"{type(e).__name__}: {str(e)[:70]}")

print("结论: " + ("✅ 通过" if not fails else f"❌ 有不通过项: {fails}"))
sys.exit(0 if not fails else 1)
