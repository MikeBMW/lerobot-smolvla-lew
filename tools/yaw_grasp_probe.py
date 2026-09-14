# -*- coding: utf-8 -*-
"""🎯 yaw 试抓探针 (2026-09-11): 让「候选 yaw → 真实试抓成败」有物理区分度。

背景: ② 段夹持靠治具钉 + 刚性锁 (等效真机刚性手爪) → 任意 yaw 都"成功" = 无监督信号。
本探针 = 同一段动作 **去掉刚性锁**, 用真实摩擦夹持 + 抬升试探判定成败:
  ① 来料转台 90° (模块横放) → 夹爪到模块上方 → 设定候选 yaw φ → 下降 → 释治具 → 闭夹 → 抬升
  ② 判据: 抬升 Δz > 0.08m (模块被真实夹起) = success; 记 Δz / 夹持随动 / 失败模式
输出: reports/yaw_probe_<ts>.json  [{seed, phi_deg, ok, dz, ...}]
用法: MUJOCO_GL=glfw gui-venv311/bin/python tools/yaw_grasp_probe.py --seeds 0 --phis -90,-75,...,90
"""
import argparse
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("MUJOCO_GL", "glfw")
import numpy as np  # noqa: E402
import gen_l4_demo_video as G  # noqa: E402


def probe_one(seed, phi_deg, tt_deg=90.0):
    """单次试抓: 返回 dict (真实物理判定, 无刚性锁)"""
    demo = G.L4Demo(seed=seed, record=False, mani_yaw=False)
    try:
        demo.stage_turntable90(target_deg=float(tt_deg))   # ① 抗干扰: tt_deg 横放 (可随机化)
        pc = demo.peg_center()
        demo.env._grip_yaw = 0.0
        demo.servo(pc + np.array([0, 0, 0.15]), tol=0.006, max_steps=600)
        # 📸 决策时刻的状态 (yaw_head 训练输入: 与 yaw_actuator 的 z7 定义同构)
        try:
            z7 = np.concatenate([demo.hand() - demo.site("pegGrasp"),
                                 demo.hand() - demo.peg_center(),
                                 [1.0 if demo._grip_lock else 0.0]]).tolist()
        except Exception:
            z7 = [0.0] * 7
        mod_yaw = float(demo._module_yaw_deg())
        peg_yaw = float(demo.peg_yaw_deg())
        # 候选 yaw 到设定值 (同脚本臂 slew 0.06)
        demo.ramp_yaw(math.radians(phi_deg), step_rad=0.06, hold=None, g=0.0, max_steps=400)
        demo.servo(pc + np.array([0, 0, 0.022]), tol=0.003, max_steps=400)
        demo._grab = False                             # 撤治具 (模块自由坐盘)
        for _ in range(30):
            demo.step(np.array([0.0, 0.0, 0.0, 0.0]))
        for _ in range(80):
            demo.step(np.array([0.0, 0.0, 0.0, 1.0]))  # 闭夹 (真实摩擦)
        # ⚠️ 不建立刚性锁 (demo._grip_lock 保持 False) = 真实摩擦夹持
        z0 = float(demo.peg_center()[2])
        h0 = demo.hand().copy()
        demo.servo(pc + np.array([0, 0, 0.18]), tol=0.008, max_steps=500)
        dz = float(demo.peg_center()[2] - z0)
        follow = float(np.linalg.norm(demo.peg_center() - pc - np.array([0, 0, dz])))
        yaw_end = float(np.degrees(demo.env._grip_yaw))
        return {"seed": seed, "phi_deg": float(phi_deg), "yaw_end_deg": round(yaw_end, 1),
                "tt_deg": float(tt_deg),
                "ok": bool(dz > 0.08), "dz_m": round(dz, 4), "follow_mm": round(follow * 1000, 1),
                "steps": int(demo.steps),
                # 🧠 训练特征 (yaw 决策时刻): z7 潜向量 + 模块朝向 + 候选角
                "z7": [round(float(v), 6) for v in z7],
                "a4": [0.0, 0.0, 0.0, 0.0],
                "module_yaw_deg": round(mod_yaw, 2), "peg_yaw_deg": round(peg_yaw, 2),
                "yaw_norm": round(float(phi_deg) / 90.0, 5)}
    finally:
        try:
            demo.env.close()
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="0")
    ap.add_argument("--phis", default="-90,-75,-60,-45,-30,-15,0,15,30,45,60,75,90")
    ap.add_argument("--tts", default="90", help="① 来料转台角 (deg, 逗号分隔) — 泛化测试用 60~120")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    seeds = [int(s) for s in a.seeds.split(",") if s.strip()]
    phis = [float(p) for p in a.phis.split(",") if p.strip()]
    tts = [float(t) for t in a.tts.split(",") if t.strip()]
    rows, t0 = [], time.time()
    for seed in seeds:
        for tt in tts:
            for phi in phis:
                for rep in range(a.reps):
                    r = probe_one(seed, phi, tt)
                    r["rep"] = rep
                    rows.append(r)
                    print(f"  seed={seed} tt={tt:+.0f}° φ={phi:+.0f}° → ok={r['ok']} "
                          f"Δz={r['dz_m']*1000:6.1f}mm 随动={r['follow_mm']:5.1f}mm "
                          f"yaw实际={r['yaw_end_deg']:+.1f}°", flush=True)
    ok_n = sum(1 for r in rows if r["ok"])
    print(f"\n试抓成功 {ok_n}/{len(rows)} · 用时 {time.time()-t0:.0f}s")
    for tt in tts:
        by_phi = {}
        for r in rows:
            if r["tt_deg"] == tt:
                by_phi.setdefault(r["phi_deg"], []).append(r["ok"])
        print(f"① 来料角 {tt:+.0f}° 按候选角成功率:")
        for phi in sorted(by_phi):
            v = by_phi[phi]
            print(f"   φ={phi:+6.1f}°  {sum(v)}/{len(v)}")
    out = a.out or os.path.join(G.REP, f"yaw_probe_{time.strftime('%Y%m%d_%H%M%S')}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"meta": {"seeds": seeds, "phis": phis, "tts": tts, "reps": a.reps,
                            "elapsed_s": round(time.time() - t0, 1)}, "rows": rows}, f,
                  ensure_ascii=False, indent=2)
    print(" → JSON:", out)


if __name__ == "__main__":
    main()
