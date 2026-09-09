#!/usr/bin/env python3
"""采集干扰布局轨迹 (L4 jitter 大扰动) → /tmp/mani_jitter.npz (训练 v3 用)"""
import sys, os
sys.path.insert(0, "/home/ubuntu/lerobot-smolvla-lew/tools/gui")
os.chdir("/home/ubuntu/lerobot-smolvla-lew/tools/gui")
import numpy as np

def collect_jitter(sim_seed, mode, overrides, tag0):
    from state_space_sim_real import RealStateSpaceSim
    Z, A, M, ZN, SEED = [], [], [], [], []
    for k, ov in enumerate(overrides):
        sim = RealStateSpaceSim(seed=sim_seed, vision=False, mode=mode, log=lambda *a: None)
        sim._jitter_override = ov
        sim._jitter_round = tag0 + k
        tr = sim.run(cap="L4")
        n = len(tr["t"])
        z7s = [np.asarray(v, float).ravel() for v in tr.get("z7_vec", [])]
        if len(z7s) < n:
            continue
        done = bool(tr["done"][-1]) if tr.get("done") else False
        for i in range(n - 1):
            m6 = np.array([tr["mani_progress"][i], tr["mani_risk"][i], tr["mani_V"][i],
                           tr["mani_eta"][i], tr["mani_rem"][i], tr["mani_dperp"][i]], float)
            if np.abs(m6).max() < 1e-6:
                continue
            a4 = np.asarray(tr["u_exec_vec"][i], float).ravel()[:4]
            Z.append(z7s[i]); A.append(a4 if a4.size == 4 else np.zeros(4))
            M.append(m6); ZN.append(z7s[i+1]); SEED.append(900 + tag0 + k)
        print(f"  jit-{tag0+k}: {mode} seed{sim_seed} Δ=({ov['dx']*100:.0f},{ov['dy']*100:.0f})cm "
              f"yaw={np.degrees(ov['yaw']):.0f}° → {n}步 done={done}", flush=True)
    return Z, A, M, ZN, SEED

import numpy as _np
ovs_full = [
    {"dx": -0.035, "dy": 0.02, "dz": 0.005, "yaw": _np.deg2rad(10)},
    {"dx": 0.03, "dy": -0.025, "dz": 0.0, "yaw": _np.deg2rad(-12)},
    {"dx": 0.025, "dy": 0.03, "dz": 0.008, "yaw": _np.deg2rad(6)},
    {"dx": -0.02, "dy": -0.035, "dz": 0.002, "yaw": _np.deg2rad(-9)},
    {"dx": 0.038, "dy": 0.01, "dz": 0.004, "yaw": _np.deg2rad(14)},
    {"dx": -0.012, "dy": 0.036, "dz": -0.002, "yaw": _np.deg2rad(-5)},
]
Z, A, M, ZN, SEED = [], [], [], [], []
z, a, m, zn, sd = collect_jitter(104, "full", ovs_full, 0); Z += z; A += a; M += m; ZN += zn; SEED += sd
z, a, m, zn, sd = collect_jitter(104, "insert", ovs_full[:3], 100); Z += z; A += a; M += m; ZN += zn; SEED += sd
Z, A, M, ZN, SEED = map(np.asarray, (Z, A, M, ZN, SEED))
np.savez("/tmp/mani_jitter.npz", z=Z, a=A, m=M, zn=ZN, seed=SEED)
print(f"\n干扰数据: {len(Z)} 帧 · done 轮次见上 · 各维: "
      + " ".join(f"{nm}[{np.asarray(M)[:,i].min():.2f},{np.asarray(M)[:,i].max():.2f}]"
                 for i, nm in enumerate(["p", "r", "V", "eta", "rem", "dp"])))
