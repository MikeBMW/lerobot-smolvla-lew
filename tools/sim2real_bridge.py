#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🌉 仿真 ↔ 真机 参数桥 (用真机模型参数全面对齐状态空间引擎的口径)

老倪 (09-22): 「同步所有仿真与真机数据，URDF，质量，惯性，自由度等，按照真实的机器人机械臂，
              全面更新状态空间的仿真数据」「不要发出真机控制指令，但是你可以采集真机的数据」

问题: 状态空间引擎跑的是 metaworld 世界 (R0/R1), 而真机是珞石 XMS5-R800-W4G3B4C。
      两边"同名"的量 (hand/peg/target/动作/限幅) 语义与量纲必须显式对上, 否则
      sim→real 迁移时口径漂移 (历史踩坑: 布局漂移写死几何 / gripper 语义反 / B 增益错)。

本工具产出 `config/robot/zmax_sim2real.json` = **引擎口径 ↔ 真机物理量 的对照表**,
每一条都带: 引擎侧来源 (代码位置) · 真机侧来源 (URDF/实测/标定) · 量纲换算 · 就绪度。
缺真机标定的一律 null + 原因 (绝不编造), 并计入 gaps。

只用只读数据 (URDF + 落盘真机帧 + 标定注册表), 零运动指令。

用法:
  gui-venv311/bin/python tools/sim2real_bridge.py            # 生成 + 打印对照表
  gui-venv311/bin/python tools/sim2real_bridge.py --check    # 只打印, 不写文件
  gui-venv311/bin/python tools/sim2real_bridge.py --json
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zmax_params as zp  # noqa: E402

ROOT = zp.ROOT
OUT = os.path.join(ROOT, "config", "robot", "zmax_sim2real.json")
LIVE_TAP = os.path.expanduser("~/zmax_data/real_tap_*/state_*.jsonl")

# 引擎侧口径常量 (来源 = 代码位置, 便于审计; 改动必须同步改代码)
ENGINE = {
    "obs_layout_39d": {"hand": "obs[0:3]", "peg_pos": "obs[4:7]", "peg_quat": "obs[7:11]",
                       "target": "obs[36:39]", "_src": "docs/闭环设计 + tools/gen_ss_metaworld_episode.py"},
    "action": {"u_unit": "m/s", "act1_eq_mps": 0.5,
               "_src": "state_space_sim_real: act=u(m/s)/0.5 (metaworld 伺服稳态 ≈9mm/步@act1)"},
    "limit": {"u_sat_mps": 0.6, "_src": "SS_LIMIT 默认 0.6 (tools/gen_ss_metaworld_episode.py:45 A_LIMIT)"},
    "insert_depth": {"value": 0.002, "_src": "state_space_sim_real (2026-09 收紧 0.006→0.002)"},
    "dt": {"value": 0.02, "_src": "引擎步长 20ms"},
}


def _live_frames(n=400):
    files = sorted(glob.glob(LIVE_TAP), key=os.path.getmtime, reverse=True)
    if not files:
        return [], None
    out = []
    try:
        with open(files[0], "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 2_000_000))
            lines = f.read().decode("utf-8", "replace").strip().splitlines()[-n:]
        for ln in lines:
            try:
                d = json.loads(ln)
            except Exception:  # noqa: BLE001
                continue
            if d.get("jpos") and d.get("tcp"):
                out.append(d)
    except Exception:  # noqa: BLE001
        pass
    return out, files[0]


def build() -> dict:
    spec = zp.robot_spec()
    cal = zp.calib()
    jl = zp.joint_limits(spec)
    frames, fpath = _live_frames()
    ctrl_tcp = spec.get("control_tcp") or {}
    tool_nom = spec.get("tool") or {}
    payload = spec.get("payload") or {}

    # 真机可达域 (从落盘帧实测; 静帧只能给"当前点", 不能给包络 → 显式标注)
    env = {"n_frames": len(frames), "state_file": fpath}
    if frames:
        tcp = [f["tcp"] for f in frames]
        env.update({
            "tcp_x_range": [round(min(t[0] for t in tcp), 4), round(max(t[0] for t in tcp), 4)],
            "tcp_y_range": [round(min(t[1] for t in tcp), 4), round(max(t[1] for t in tcp), 4)],
            "tcp_z_range": [round(min(t[2] for t in tcp), 4), round(max(t[2] for t in tcp), 4)],
            "static": (max(max(t[i] for t in tcp) - min(t[i] for t in tcp) for i in range(3)) < 0.002),
        })

    # 工具系偏移: 引擎 obs[4:7] 光模块 = TCP + R_tcp·(夹具偏移)。夹具偏移需示教几何
    geom = (cal.get("cell_geometry") or {}).get("points")
    peg_off = None
    peg_reason = ("未示教几何 → obs[4:7] 无法从 TCP 推 → 引擎侧保持感知直给 (真机侧走 YOLO 反投影); "
                  "现场零运动示教 tools/ss_geom_calib.py --record peg_head 后可闭合")
    if isinstance(geom, dict) and geom.get("peg_head") and geom.get("tool_at_peg_head"):
        p = geom["peg_head"]
        q = geom["tool_at_peg_head"]
        peg_off = [round(p[i] - q[i], 6) for i in range(3)]
        peg_reason = None

    bridge = {
        "_doc": ("Z-MAX 仿真↔真机参数桥 — 由 tools/sim2real_bridge.py 生成。"
                 "引擎口径 ↔ 真机物理量逐条对照 (含来源与就绪度), sim→real 迁移前先读本表。"),
        "_generated_at": time.strftime("%F %T"),
        "robot": {
            "engine_side": "metaworld 仿真臂 (R0 物理真实化)",
            "real_side": f"{spec['robot']['name']} (珞石, DOF {spec['robot']['dof']})",
            "urdf_sha256_16": spec["robot"]["urdf_sha256_16"],
            "link_mass_sum_kg": spec["totals"]["link_mass_sum_kg"],
            "payload_kg": payload.get("mass_kg"),
            "payload_cog_m": payload.get("cog_m"),
            "_mass_inertia_src": "URDF config/robot/xms5_r800_w4g3b4c.urdf (6 连杆全带惯量张量)",
        },
        "frames": {
            "engine_hand": {"obs": ENGINE["obs_layout_39d"]["hand"], "real": "TCP (FK(jpos) 或编码器)",
                            "real_fk_residual_mm": (spec.get("live_check", {}).get("fk", {}) or {}).get("err_mm"),
                            "_src": "URDF FK ↔ /robot/tcp_pose 实测对照 (tools/robot_spec_sync.py)"},
            "engine_peg": {"obs": ENGINE["obs_layout_39d"]["peg_pos"],
                           "real": "YOLO 2D + 反投影 (K + T_base_cam + plane_z) 或 plane_z 光线回退",
                           "tool_offset_m": peg_off, "_reason": peg_reason},
            "engine_target": {"obs": ENGINE["obs_layout_39d"]["target"],
                              "real": "示教孔位 (cell_geometry.goal)",
                              "ready": bool(isinstance(geom, dict) and geom.get("goal")),
                              "_reason": None if (isinstance(geom, dict) and geom.get("goal"))
                              else "未示教 goal (孔口/孔底)"},
            "control_tcp_offset_m": ctrl_tcp.get("offset_xyz_m"),
            "nominal_tool_offset_m": tool_nom.get("xyz"),
            "_tcp_note": ("产线 TCP 由只读多帧反解得到, 与 URDF 名义 tool1 差 ~3mm (工具几何名义值 vs 现场夹爪);"
                          " sim→real 用 control_tcp 口径, 不用名义 tool1"),
        },
        "scale_action": {
            "engine": ENGINE["action"], "real": {"unit": "m/s", "servo": "RT 伺服/点位 (Orin robot_driver)"},
            "act_to_mps": ENGINE["action"]["act1_eq_mps"], "u_sat_mps": ENGINE["limit"]["u_sat_mps"],
            "one_step_mm": round(ENGINE["action"]["act1_eq_mps"] * ENGINE["dt"]["value"] * 1000, 2),
            "_verify": "真机运动需现场闸门 (本工具不发任何指令)",
        },
        "joint_limits": {"n": len(jl), "items": jl,
                         "_src": "URDF 限位 (位置/速度/力矩)",
                         "used_by": "L2 收口闸 (逐轴夹紧) + 安全层限幅"},
        "workspace_real": env,
        "calib_refs": {"camera_K": (cal.get("camera") or {}).get("K"),
                       "T_base_cam": (cal.get("T_base_cam") or {}).get("value"),
                       "plane_z": (cal.get("plane_z") or {}).get("value"),
                       "depth_scale_sim_only": (cal.get("depth_scale") or {}).get("value")},
        "gaps": zp.gaps(),
        "_redline": "全流程只读: URDF + 落盘真机帧 + 标定注册表; 无任何真机控制指令 (move/jog/rt/gripper 一律未调)",
    }
    return bridge


def print_bridge(b: dict) -> None:
    r = b["robot"]
    print(f"🌉 仿真↔真机参数桥  {r['engine_side']}  ⇄  {r['real_side']}")
    print("─" * 84)
    print(f"真机质量: 连杆合计 {r['link_mass_sum_kg']} kg + 负载 {r['payload_kg']} kg (cog {r['payload_cog_m']})")
    f = b["frames"]
    print(f"hand  : {f['engine_hand']['obs']} ⇄ TCP       FK 残差 {f['engine_hand']['real_fk_residual_mm']} mm")
    ep = f["engine_peg"]
    print(f"peg   : {ep['obs']} ⇄ {ep['real']}")
    print(f"        工具系偏移 {ep['tool_offset_m']}  {('—' if ep['tool_offset_m'] else '⚠️ ' + str(ep['_reason'])[:60])}")
    print(f"target: {f['engine_target']['obs']} ⇄ 示教孔位   就绪 {f['engine_target']['ready']}")
    print(f"TCP   : 产线反解 {f['control_tcp_offset_m']}  名义 tool1 {f['nominal_tool_offset_m']}")
    s = b["scale_action"]
    print(f"动作  : {s['engine']['u_unit']}, act1={s['act_to_mps']} m/s → 单步 {s['one_step_mm']} mm, 限幅 {s['u_sat_mps']} m/s")
    print(f"限位  : {b['joint_limits']['n']} 轴 (URDF) → {b['joint_limits']['used_by']}")
    w = b["workspace_real"]
    if w.get("n_frames"):
        print(f"实测域: {w['n_frames']} 帧  TCP x{w['tcp_x_range']} y{w['tcp_y_range']} z{w['tcp_z_range']}"
              f"{'  (静帧: 只代表当前点, 非包络)' if w.get('static') else ''}")
    print("─" * 84)
    for g in b["gaps"]:
        print(f"⚠️ 缺口 {g['item']}: {str(g['reason'])[:72]}")
    if not b["gaps"]:
        print("✅ 无缺口")


def main() -> int:
    ap = argparse.ArgumentParser(description="仿真↔真机参数桥")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    b = build()
    if a.json:
        print(json.dumps(b, ensure_ascii=False, indent=1))
        return 0
    print_bridge(b)
    if a.check:
        print("\n(--check: 未写文件)")
        return 0
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(b, f, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)
    print(f"\n✅ 已写参数桥: {os.path.relpath(OUT, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
