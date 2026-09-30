# -*- coding: utf-8 -*-
"""🎯 插入段 yaw 敏感性探针 (2026-09-11): 找 yaw 真正 load-bearing 的地方。

背景: ② 段"抓横放光模块"实测 13/13 全成功 (peg 是 15×15mm 方形截面 → 任意 yaw 都能夹住)
= 那里没有监督信号。插入段 (⑤) 才是 yaw 的作用点: 夹持相位/姿态错了 → 模块头对不上孔轴
→ 推入 stall / 深度不足。本探针 = 跑完 ①②③④ 后, 在插入相位上叠加 yaw 偏移 δ,
用**真实推入深度 / 成败**当标签。

输出: reports/yaw_insert_probe_<ts>.json  [{seed, delta_deg, depth_mm, ok, z7, ...}]
用法: MUJOCO_GL=glfw gui-venv311/bin/python tools/yaw_insert_probe.py --seeds 0 --deltas -90,...,90
"""
import argparse
import json
import math
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("MUJOCO_GL", "glfw")
import numpy as np  # noqa: E402
import gen_l4_demo_video as G  # noqa: E402


def probe_one(seed, delta_deg):
    demo = G.L4Demo(seed=seed, record=False, mani_yaw=False)
    try:
        demo.stage_turntable90()
        demo.stage_adapt_grasp()
        demo.stage_yaw_back()
        demo.stage_grasp_std()
        feat = {}

        _orig = demo.ramp_yaw

        def _patched(target, **kw):
            # 插入段唯一一次 ramp = 相位翻转; 在这里叠加 δ 并记录决策时刻状态
            if str(getattr(demo, "_stage", "")).startswith("⑤"):
                try:
                    feat["z7"] = np.concatenate([
                        demo.hand() - demo.site("pegGrasp"),
                        demo.hand() - demo.peg_center(),
                        [1.0 if demo._grip_lock else 0.0]]).tolist()
                except Exception:
                    feat["z7"] = [0.0] * 7
                feat["yaw_before_deg"] = float(np.degrees(demo.env._grip_yaw))
                target = target + math.radians(float(delta_deg))
                feat["yaw_target_deg"] = float(np.degrees(target))
            return _orig(target, **kw)

        demo.ramp_yaw = _patched
        ok = bool(demo.stage_insert())
        hist = "\n".join(demo.history)
        m = re.search(r"⑤ 插入: 真物理推入深度 ([\d.]+)mm", hist)
        depth = float(m.group(1)) if m else 0.0
        return {"seed": seed, "delta_deg": float(delta_deg), "ok": ok,
                "depth_mm": round(depth, 1), "steps": int(demo.steps),
                "z7": [round(float(v), 6) for v in feat.get("z7", [0.0] * 7)],
                "a4": [0.0, 0.0, 0.0, 0.0],
                "yaw_before_deg": round(feat.get("yaw_before_deg", 0.0), 1),
                "yaw_target_deg": round(feat.get("yaw_target_deg", 0.0), 1)}
    finally:
        try:
            demo.env.close()
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="0")
    ap.add_argument("--deltas", default="-90,-75,-60,-45,-30,-20,-10,0,10,20,30,45,60,75,90")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    seeds = [int(s) for s in a.seeds.split(",") if s.strip()]
    deltas = [float(d) for d in a.deltas.split(",") if d.strip()]
    rows, t0 = [], time.time()
    for seed in seeds:
        for d in deltas:
            r = probe_one(seed, d)
            rows.append(r)
            print(f"  seed={seed} δ={d:+6.1f}° → ok={r['ok']} 插入深度={r['depth_mm']:5.1f}mm", flush=True)
    print(f"\n用时 {time.time()-t0:.0f}s")
    print("按偏移统计:")
    for d in sorted({r["delta_deg"] for r in rows}):
        v = [r for r in rows if r["delta_deg"] == d]
        print(f"   δ={d:+6.1f}°  ok {sum(r['ok'] for r in v)}/{len(v)} · "
              f"深度均值 {np.mean([r['depth_mm'] for r in v]):5.1f}mm")
    out = a.out or os.path.join(G.REP, f"yaw_insert_probe_{time.strftime('%Y%m%d_%H%M%S')}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"meta": {"seeds": seeds, "deltas": deltas,
                            "elapsed_s": round(time.time() - t0, 1)}, "rows": rows},
                  f, ensure_ascii=False, indent=2)
    print(" → JSON:", out)


if __name__ == "__main__":
    main()
