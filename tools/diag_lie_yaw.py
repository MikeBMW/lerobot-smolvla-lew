#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧭 diag_lie_yaw.py — ② 验证: SU(2) 意图是否真的驱动 yaw 出口 (每臂独立进程)

三臂 (同 seed 同起点, yaw 段同 slew 限幅):
  script : 脚本开环 ramp_yaw(90°)          (现状 Arm A)
  mani   : 流形预测器/试抓头决策            (Arm B)
  su2    : 接触 twist 的绕轴残差 + 增益融合 (Arm C, 本轮新增)

判据 (全部几何/真值, 不看日志口气):
  · 收尾时**剩余几何残差** |yaw_from_twist(e)| — 越小 = 姿态真的对齐了 (Σ 需为 0)
  · 与所需角的差、K 均值、步数
用法: python tools/diag_lie_yaw.py <arm> [seed]
"""
from __future__ import annotations

import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "tools"), os.path.join(ROOT, "src")]
os.environ.setdefault("MUJOCO_GL", "glfw")

import numpy as np  # noqa: E402

ARM = sys.argv[1] if len(sys.argv) > 1 else "script"
SEED = int(sys.argv[2]) if len(sys.argv) > 2 else 0


def main() -> int:
    import gen_l4_demo_video as G
    from lerobot.manifold.lie_intent import wrap_pi, yaw_from_twist

    if ARM == "su2":
        os.environ["SS_L4_LIE_YAW"] = "1"
    print(f"臂={ARM} seed={SEED} · SS_L4_LIE_YAW={os.environ.get('SS_L4_LIE_YAW')!r}", flush=True)
    try:                                    # ⚠️ 必须先建自定义场景 XML (否则 metaworld 找不到 _l4.xml)
        G.ensure_scene()
    except Exception as _e:                                                 # noqa: BLE001
        print(f"  ⚠️ ensure_scene 失败: {type(_e).__name__}: {_e}", flush=True)
    demo = G.L4Demo(seed=SEED, record=False, mani_yaw=(ARM == "mani"))
    demo.stage_turntable90(target_deg=90.0)
    pc = demo.peg_center()
    demo.env._grip_yaw = 0.0
    demo.servo(pc + np.array([0.0, 0.0, 0.15]), tol=0.006, max_steps=600)

    e0 = demo._contact_twist_demo()
    req0 = math.degrees(yaw_from_twist(e0)) if e0 is not None else float("nan")
    print(f"  起始: 模块 yaw={demo.peg_yaw_deg():.2f}° · 折叠 φ={demo._module_yaw_deg():.2f}° · "
          f"几何需求 Δφ={req0:+.2f}°", flush=True)

    if ARM == "su2":
        phi_cmd = demo._align_yaw_su2()
        info = getattr(demo, "_lie_yaw_info", None)
    elif ARM == "mani":
        phi_cmd = demo._align_yaw_manifold()
        info = None
    else:
        demo.ramp_yaw(math.pi / 2, step_rad=0.03, hold=None, g=0.0, max_steps=400)
        phi_cmd = float(math.degrees(demo.env._grip_yaw))
        info = None

    e1 = demo._contact_twist_demo()
    req1 = math.degrees(yaw_from_twist(e1)) if e1 is not None else float("nan")
    # 收尾"姿态失配": 模块长轴与"对齐态"的圆上测地距离 (180° 折叠)
    mis = abs(math.degrees(wrap_pi(math.radians((demo._module_yaw_deg() + 90.0) % 90.0))))
    out = {"arm": ARM, "seed": SEED, "phi_cmd_deg": round(phi_cmd, 3),
           "phi_geo_req_start_deg": round(req0, 3), "phi_geo_req_end_deg": round(req1, 3),
           "residual_end_deg": round(abs(req1), 3), "module_yaw_end_deg": round(demo.peg_yaw_deg(), 2),
           "align_mismatch_deg": round(mis, 3), "lie_info": info}
    p = os.path.join(ROOT, "reports", f"lie_yaw_{ARM}_s{SEED}.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print("结果: " + json.dumps(out, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
