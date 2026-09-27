#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三点刚体解: 仿真世界 → 机器人 base_link 的 R,t (老倪 2026-09-27 现场示教的三点)"""
import json, os, time, math
import numpy as np

SIM = {"pegGrasp": (0.0966, 0.5191, 0.0300), "hole": (-0.1685, 0.4623, 0.1309), "goal": (-0.2345, 0.4623, 0.1309)}
REAL_KEY = {"pegGrasp": "peg_head", "hole": "hole", "goal": "goal"}

g = json.load(open(os.path.expanduser("~/zmax_data/real_cell_geometry.json"), encoding="utf-8"))
keys = list(SIM)
S = np.array([SIM[k] for k in keys])
P = np.array([[g["points"][REAL_KEY[k]][c] for c in "xyz"] for k in keys])

sc, pc = S.mean(0), P.mean(0)
H = (S - sc).T @ (P - pc)
U, sv, Vt = np.linalg.svd(H)
d = np.sign(np.linalg.det(Vt.T @ U.T))
R = Vt.T @ np.diag([1, 1, d]) @ U.T
t = pc - R @ sc
pred = (R @ S.T).T + t
res = np.linalg.norm(pred - P, axis=1) * 1000
ang = math.degrees(math.acos(max(-1, min(1, (np.trace(R) - 1) / 2))))

print("--- 三点刚体解 (仿真 → base_link) ---")
print("  对应点: " + " · ".join("%s↔%s" % (REAL_KEY[k], k) for k in keys))
print("  R =")
for row in R:
    print("     [%+.4f %+.4f %+.4f]" % tuple(row))
print("  等效转角 %.1f°   t = (%+.4f, %+.4f, %+.4f) m" % (ang, t[0], t[1], t[2]))
for k, r_ in zip(keys, res):
    print("  残差 %-9s %5.1f mm" % (k, r_))
print("  最大残差 %.1f mm ⇒ %s" % (res.max(), "✅ 三点自洽, 锚定可信" if res.max() < 8 else "⚠️ 偏大: 某点口径不一致"))

out = os.path.expanduser("~/zmax_data/sim2base_anchor.json")
a = json.load(open(out, encoding="utf-8")) if os.path.exists(out) else {}
a.update({"sim_points": {k: list(SIM[k]) for k in keys},
          "real_points": {REAL_KEY[k]: list(P[i]) for i, k in enumerate(keys)},
          "R_sim_to_base": R.tolist(), "t_sim_to_base_m": [float(x) for x in t],
          "angle_deg": round(ang, 2), "residual_mm": [float(x) for x in res],
          "validated": bool(res.max() < 8), "frame": "base_link", "ts_str": time.strftime("%F %T")})
a.pop("undetermined", None)
json.dump(a, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("已写锚定:", out)
