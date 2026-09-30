#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ss_su2_verify.py — SU(2) 统一状态空间 实测验证 (真实引擎数据, 不编造)

跑法: gui-venv311/bin/python tools/ss_su2_verify.py
产出:
  ① 群公理自检数值 (机器精度)
  ② 真实引擎轨迹 (StateSpaceSim) 逐帧 → SU(2) 状态: 轨迹/收敛度/阶段表
  ③ 节点级全面映射 (引擎 io_trace 全节点 → 群元素)
  ④ 分层剥离/层间不可交换性/Fubini-Study 距离矩阵
  ⑤ reports/su2_state_report.json
"""
import json
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "tools", "gui"))

from lerobot.policies.left_right.state_space import su2          # noqa: E402


def _engine_trace():
    """真实引擎轨迹 (state_space_sim.StateSpaceSim, 与画布 ▶运行 同源)"""
    import state_space_sim as sss
    sim = sss.StateSpaceSim(log=None)
    tr = sim.run(io_every=25)
    return sim, tr


def stage_table(tr, n_step=8):
    """按阶段聚合: SU(2) 偏离角/收敛度 (真实逐帧均值)"""
    obs_list = tr["obs"]
    stages = [str(s).replace("阶段 ", "").split("·")[0].strip() for s in tr["stage"]]
    frames = [{"mani_progress": tr["mani_progress"][i], "mani_dperp": tr["mani_dperp"][i],
               "mani_rem": tr["mani_rem"][i], "u_sat": tr["u_sat"][i],
               "contact_p": tr["contact_p"][i], "mani_eta": tr["mani_eta"][i]}
              for i in range(len(obs_list))]
    agg = {}
    for i, st in enumerate(stages):
        layers = su2.encode_layers(frames[i], obs_list[i])
        scene = su2.compose_scene(layers)
        d = agg.setdefault(st, {"n": 0, "theta": 0.0, "vis": 0.0, "theta_L2": 0.0})
        d["n"] += 1
        d["theta"] += scene.theta()
        d["vis"] += scene.visibility()
        d["theta_L2"] += layers["L2"].theta()
    for st, d in agg.items():
        for k in ("theta", "vis", "theta_L2"):
            d[k] = round(d[k] / max(1, d["n"]), 4)
    return agg


def node_scene_from_io(tr, k=0):
    """节点级全面映射: io_trace 第 k 帧全部节点 → 群元素 → 场景态 (+诚实标注)"""
    io = tr.get("io_trace") or []
    if not io:
        return {}, su2.SU2Element.identity(), []
    frame = io[min(k, len(io) - 1)][1]
    detail = {}
    nodes = su2.encode_nodes(frame, detail=detail)
    return nodes, su2.scene_from_nodes(nodes), detail.get("no_numeric_output", [])


def main():
    out = {"module": "su2.py (SU(2) 统一状态空间)", "node": "VEH.5.041"}

    # ① 群公理
    axioms = su2.group_axiom_selftest(n=128, seed=7)
    out["group_axioms"] = axioms
    print("① SU(2) 群公理自检 (n=128, 机器精度):")
    for kk, vv in axioms.items():
        print("   %-34s %s" % (kk, vv))
    print("   → all_ok =", axioms["all_ok"])

    # ② 真实引擎轨迹
    sim, tr = _engine_trace()
    n = len(tr["stage"])
    print("\n② 真实引擎 (StateSpaceSim): %d 步, 阶段序列首末: %s → %s"
          % (n, tr["stage"][0], tr["stage"][-1]))

    us = su2.SU2UnifiedState(log=None)
    thetas, vis = [], []
    for i in range(n):
        frame = {"mani_progress": tr["mani_progress"][i], "mani_dperp": tr["mani_dperp"][i],
                 "mani_rem": tr["mani_rem"][i], "u_sat": tr["u_sat"][i],
                 "contact_p": tr["contact_p"][i], "mani_eta": tr["mani_eta"][i],
                 "u_x": tr["u_fuse_vec"][i][0], "u_y": tr["u_fuse_vec"][i][1],
                 "u_z": tr["u_fuse_vec"][i][2], "dist": tr["dist"][i]}
        scene, layers, u = us.push(frame, tr["obs"][i])
        thetas.append(round(u["state"]["theta"], 5))
        vis.append(round(u["state"]["visibility"], 5))

    last = us.history[-1]
    print("   末帧统一状态: θ=%.4f rad · 收敛度|w|=%.4f · Bloch 球面点 ‖r‖=%.6f"
          % (thetas[-1], vis[-1], float(np.linalg.norm(last))))
    print("   初始 θ=%.4f → 末 θ=%.4f (θ↓=误差收敛; |w|↑=向参考态收敛)"
          % (thetas[0], thetas[-1]))
    out["engine_trace"] = {"n_steps": n, "bloch_series": us.history,   # Bloch 轨迹(可视面板用)
                           "theta_series": thetas,
                           "theta_first": thetas[0], "theta_last": thetas[-1],
                           "visibility_first": vis[0], "visibility_last": vis[-1],
                           "bloch_last": last,
                           "theta_series_every10": thetas[::max(1, n // 10)]}

    # ③ 阶段表
    st_tab = stage_table(tr)
    out["stage_table"] = st_tab
    print("\n③ 分阶段统一状态 (真实逐帧均值):")
    print("   %-12s %6s %10s %10s %10s" % ("阶段", "帧数", "θ_total", "收敛|w|", "θ_L2"))
    for st, d in st_tab.items():
        print("   %-12s %6d %10.4f %10.4f %10.4f"
              % (st, d["n"], d["theta"], d["vis"], d["theta_L2"]))

    # ④ 节点级全面映射
    nodes, scene_nodes, empty = node_scene_from_io(tr, len(tr.get("io_trace", [])) // 2)
    out["node_mapping"] = {"n_nodes": len(nodes),
                           "nodes": {k: {"theta": round(v.theta(), 4),
                                         "axis": [round(float(x), 3) for x in v.axis()],
                                         "visibility": round(v.visibility(), 4)}
                                     for k, v in nodes.items()},
                           "no_numeric_output": empty,
                           "scene": {"theta": round(scene_nodes.theta(), 4),
                                     "visibility": round(scene_nodes.visibility(), 4),
                                     "bloch": [round(float(x), 4) for x in scene_nodes.bloch()]}}
    print("\n④ 节点级全面映射 (io_trace 中间帧): %d 个节点 → 群元素" % len(nodes))
    for k, v in nodes.items():
        print("   %-22s θ=%.4f |w|=%.4f n̂=%s"
              % (k, v.theta(), v.visibility(), np.round(v.axis(), 3).tolist()))
    if empty:
        print("   ⚠ 本帧无数值输出(映射为单位元, 不编造): %s" % ", ".join(empty))
    print("   场景合成态: θ=%.4f 收敛|w|=%.4f Bloch=%s"
          % (scene_nodes.theta(), scene_nodes.visibility(),
             np.round(scene_nodes.bloch(), 4).tolist()))

    # ⑤ 分层剥离 / 不可交换 / 距离矩阵 (末帧)
    i = n - 1
    frame_last = {"mani_progress": tr["mani_progress"][i], "mani_dperp": tr["mani_dperp"][i],
                  "mani_rem": tr["mani_rem"][i], "u_sat": tr["u_sat"][i],
                  "contact_p": tr["contact_p"][i], "mani_eta": tr["mani_eta"][i]}
    layers = su2.encode_layers(frame_last, tr["obs"][i])
    scene = su2.compose_scene(layers)
    u = su2.understand(scene, layers)
    out["understand_last"] = u
    print("\n⑤ 分层剥离 (末帧, 逐层读贡献):")
    for L in ("L2", "L3", "L4", "L5"):
        d = u["layer_peel"].get(L)
        print("   %s θ=%.4f → 剥离后残余 θ=%.4f (该层贡献 Δθ=%.4f) n̂=%s"
              % (L, d["layer_theta"], d["theta_after"], d["delta_theta"],
                 np.round(d["layer_axis"], 3).tolist()))
    print("   全剥离残差 θ=%.3e (应≈0: 群恒等元 = 分解自洽)"
          % u["layer_peel"]["_residual"]["theta"])
    print("   层间不可交换 ‖[Ui,Uj]‖:")
    for kk, vv in u["noncommutativity"].items():
        if kk.split("|")[0] < kk.split("|")[1]:
            print("      %-8s %.6f" % (kk, vv))
    print("   Fubini–Study 层间距离:")
    for kk, vv in u["layer_distance"].items():
        if kk.split("|")[0] < kk.split("|")[1]:
            print("      %-8s %.6f" % (kk, vv))

    # ⑥ 可视化载荷
    payload = su2.viz_payload(frame_last, tr["obs"][i], node_states=nodes, history=us.history)
    out["viz_payload_keys"] = sorted(payload.keys())
    print("\n⑥ 统一可视化载荷 keys: %s" % out["viz_payload_keys"])

    rp = os.path.join(REPO, "reports", "su2_state_report.json")
    os.makedirs(os.path.dirname(rp), exist_ok=True)
    with open(rp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("\n报告: %s (%d bytes)" % (rp, os.path.getsize(rp)))
    return 0 if axioms["all_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
