# -*- coding: utf-8 -*-
"""🧪 L4 夹爪 yaw 指令 A/B 实证 (2026-09-11 老倪要求)

Arm A = 脚本开环 (② 段固定 ramp_yaw(+90°), 现状发布行为)
Arm B = 流形预测器逐帧决策 (ManifoldYawActuator: 候选角打分取代价最小)

口径: 同链路同 seed/重复数; 记 success/steps/② yaw 指令/插入深度/拔出/AOI/η/
预测器前向次数。输出 JSON + 控制台表。**不做任何写死/回填, 失败如实记。**
用法: gui-venv311/bin/python tools/ab_mani_yaw.py [--seeds 0,2,5] [--reps 2]
"""
import argparse
import json
import os
import re
import statistics as st
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("MUJOCO_GL", "glfw")
import gen_l4_demo_video as G  # noqa: E402

REP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reports")


def _num(pat, text, cast=float, default=None):
    m = re.search(pat, text or "")
    return cast(m.group(1)) if m else default


def one(arm, seed, rep):
    demo = G.L4Demo(seed=seed, record=False, mani_yaw=(arm == "mani_yaw"))
    try:
        ok, meta = demo.run_all()
    finally:
        try:
            demo.env.close()
        except Exception:
            pass
    hist = "\n".join(meta.get("history") or [])
    row = {
        "arm": arm, "seed": seed, "rep": rep, "success": bool(ok), "steps": meta.get("steps"),
        "yaw_cmd_deg": round(float(meta.get("yaw_cmd_deg") or 0.0), 1),
        "insert_mm": _num(r"⑤ 插入: 真物理推入深度 ([\d.]+)mm", hist),
        "pull_mm": _num(r"⑥ 拔出: 头退出孔口外 (\d+)mm", hist),
        "aoi_ok": bool(_num(r"⑦ AOI: \{'ok': (True|False)", hist, str) == "True"),
        "eta": round(float((meta.get("couple") or {}).get("eta") or 0.0), 4),
        "mani_calls": (meta.get("mani") or {}).get("n_calls"),
        "mani_decide": (meta.get("mani") or {}).get("n_decide"),
        "trained": (meta.get("mani") or {}).get("trained"),
        "hist2": next((h for h in (meta.get("history") or []) if h.startswith("②")), ""),
    }
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="0,2,5")
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    seeds = [int(s) for s in a.seeds.split(",") if s.strip()]
    rows = []
    t0 = time.time()
    for arm in ("scripted", "mani_yaw"):
        for seed in seeds:
            for rep in range(a.reps):
                r = one(arm, seed, rep)
                rows.append(r)
                print(f"  [{arm:9s}] seed={seed} rep={rep} success={r['success']} steps={r['steps']} "
                      f"yaw={r['yaw_cmd_deg']:+.1f}° 插入={r['insert_mm']} 拔出={r['pull_mm']} "
                      f"AOI={r['aoi_ok']} η={r['eta']} 预测器前向={r['mani_calls']}", flush=True)
    print("\n═══ 汇总 (同 seed/重复数同口径) ═══")
    for arm in ("scripted", "mani_yaw"):
        rs = [r for r in rows if r["arm"] == arm]
        succ = sum(1 for r in rs if r["success"])
        ins = [r["insert_mm"] for r in rs if r["insert_mm"] is not None]
        stp = [r["steps"] for r in rs if r["steps"]]
        yaw = [r["yaw_cmd_deg"] for r in rs]
        etas = [r["eta"] for r in rs if r["eta"]]
        print(f"  {arm:9s}: success {succ}/{len(rs)} · 步数均值 {st.mean(stp):.0f} · "
              f"插入均值 {st.mean(ins):.1f}mm · η均值 {st.mean(etas):.3f} · "
              f"yaw 指令 {min(yaw):+.1f}~{max(yaw):+.1f}° · 预测器前向 {rs[0]['mani_calls']}")
    out = a.out or os.path.join(REP_DIR, f"ab_mani_yaw_{time.strftime('%Y%m%d_%H%M%S')}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"meta": {"seeds": seeds, "reps": a.reps, "elapsed_s": round(time.time() - t0, 1),
                            "pred_weights": "models/l4_mani_predictor_v5.pt"},
                   "rows": rows}, f, ensure_ascii=False, indent=2)
    print("  → JSON:", out)


if __name__ == "__main__":
    main()
