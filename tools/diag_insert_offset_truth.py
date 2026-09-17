#!/usr/bin/env python3
"""插入几何诊断: 光模块最终到底进没进孔 (老倪: 「光模块最后没有插入槽内, 水平相差一段距离」)

测什么 (全部取**真值**, 不是引擎估计):
  插入结束时 光模块头 (site ph 真值) 相对 孔口/终点 (site hole/goal 真值) 的
  · 轴向深度 depth = (ph−hole)·axis      (axis = goal−hole 单位向量, 孔轴方向)
  · 水平横向偏差 lateral = |(ph−hole) − depth·axis|   ← 老倪说的"水平相差一段距离"
  · 是否 done / 结束阶段 / 遇阻·滑脱·重夹事件数 / 引擎自己的估计值 (对照)

用法: gui-venv311/bin/python tools/diag_insert_offset_truth.py --vision 0 --cap L2 --seed 104
      (--vision 1 = R1 真实视觉档, 每步 YOLO, 慢)
输出: 屏幕汇总 + /tmp/diag_insert_<vision>_<cap>_<seed>.csv 逐步轨迹
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
os.environ.setdefault("DISPLAY", ":0")
sys.path.insert(0, os.path.join(HERE, "gui"))

import numpy as np                                       # noqa: E402
import state_space_sim_real as ssr                       # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--vision", type=int, default=0)
ap.add_argument("--cap", default="L2")
ap.add_argument("--seed", type=int, default=104)
ap.add_argument("--budget", type=int, default=0, help="0=引擎默认")
ap.add_argument("--mode", default="insert")
a = ap.parse_args()

CSV = f"/tmp/diag_insert_{a.vision}_{a.cap}_{a.seed}.csv"
LOG = open(f"/tmp/diag_insert_{a.vision}_{a.cap}_{a.seed}.full.log", "w", encoding="utf-8")
KEY = ("遇阻", "滑脱", "重夹", "回退", "完成", "插入", "孔", "抓", "done", "成功", "失败", "✅", "❌", "⚠️")


def log(*args):
    s = " ".join(str(x) for x in args)
    LOG.write(s + "\n")
    LOG.flush()
    if any(k in s for k in KEY):
        print("   " + s, flush=True)


print(f"=== 诊断: vision={a.vision} cap={a.cap} seed={a.seed} mode={a.mode} ===", flush=True)
t0 = time.time()
sim = ssr.RealStateSpaceSim(log=log, seed=a.seed, vision=bool(a.vision), mode=a.mode)
print(f"引擎构造完成 ({time.time() - t0:.1f}s)", flush=True)

env = sim.env
d = env.data
tr = sim.run(max_steps=(a.budget or None), cap=a.cap)
dt = time.time() - t0

stages = tr.get("stage") or []
ph_list = tr.get("peg_head") or []
n = len(stages)
rows = []
for i in range(n):
    st = stages[i]
    ph = np.asarray(ph_list[i], float) if i < len(ph_list) else None
    if ph is None:
        continue
    g_hole, g_goal = sim.geom["hole"], sim.geom["goal"]
    ax = g_goal - g_hole
    ax = ax / (float(np.linalg.norm(ax)) or 1.0)
    dlt = ph - g_hole
    depth = float(np.dot(dlt, ax))
    lat = float(np.linalg.norm(dlt - depth * ax))
    rows.append((i, st, depth, lat))

with open(CSV, "w", encoding="utf-8") as f:
    f.write("step,stage,depth_m,lateral_m\n")
    for r in rows:
        f.write(f"{r[0]},{r[1]},{r[2]:.5f},{r[3]:.5f}\n")

# ── 终局真值 ──
ph_t = np.asarray(d.site_xpos[sim._site_ph], float).copy()
g_hole, g_goal = sim.geom["hole"].copy(), sim.geom["goal"].copy()
ax = (g_goal - g_hole)
ax = ax / (float(np.linalg.norm(ax)) or 1.0)
dlt = ph_t - g_hole
depth = float(np.dot(dlt, ax))
lat = float(np.linalg.norm(dlt - depth * ax))
need = float(np.linalg.norm(g_goal - g_hole))
done = bool(tr.get("done", [False])[-1]) if tr.get("done") else False
meta = tr.get("_meta") or {}

print("\n──────── 终局 (真值) ────────")
print(f"孔口 hole      = {np.round(g_hole, 4)}")
print(f"终点 goal      = {np.round(g_goal, 4)}   (孔深需 {need * 1000:.1f} mm)")
print(f"光模块头 ph    = {np.round(ph_t, 4)}")
print(f"→ 轴向深度 depth = {depth * 1000:+.1f} mm   (需 {need * 1000:.1f} mm, 正=已进孔)")
print(f"→ 水平横向 lateral = {lat * 1000:.1f} mm   ← 老倪说的'水平相差一段距离'")
print(f"→ 距终点 |ph−goal| = {float(np.linalg.norm(ph_t - g_goal)) * 1000:.1f} mm"
      f"   (引擎 _insert_depth 判据 ≤2mm 算完成)")
print(f"结束阶段 = {stages[-1] if stages else '?'} · 总步数 {n} · done={done}"
      f" · 夹持={getattr(sim, 'grasped', None)}")
print(f"遇阻事件 {getattr(sim, '_stall_events', '?')} · 滑脱帧 {getattr(sim, '_slip_run', '?')}"
      f" · 重夹次数 {getattr(sim, '_regrip_tries', '?')}")
print(f"引擎自己的估计: peg_head={np.round(sim.peg_head(), 4)} · hole={np.round(sim._hole_p(), 4)}"
      f" · _insert_depth={sim._insert_depth() * 1000:.1f} mm")
if meta:
    print("meta =", json.dumps({k: v for k, v in meta.items() if not isinstance(v, (list, dict))},
                               ensure_ascii=False)[:400])
print(f"\n耗时 {dt:.1f}s · 逐步轨迹 → {CSV} · 全日志 → {LOG.name}")

# 每阶段最后一次的 depth/lateral
print("\n──── 各阶段末 depth/lateral (mm) ────")
seen = {}
for st, _i, dp, lt in [(r[1], r[0], r[2], r[3]) for r in rows]:
    seen[st] = (dp, lt)
for st, (dp, lt) in seen.items():
    print(f"  {st:6s} depth={dp * 1000:+8.1f}  lateral={lt * 1000:7.1f}")
sys.exit(0)
