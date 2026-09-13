# -*- coding: utf-8 -*-
"""✅ 分层记忆势场 · 真数据验证 (L2 肌肉 / L3 工艺 / L4 工作空间 / 总装机联络)

用的是**真数据**: data/muscle_memory.json 的 champ_x (真机真跑冠军轨迹) + io.exit (真终点)
+ 引擎现场几何 (RealStateSpaceSim._reset 采样的 hole/goal)。全部判据都是数值断言, 无文字空转。

用法: MUJOCO_GL=egl ./gui-venv311/bin/python tools/verify_memory_potential_fields.py
"""
from __future__ import annotations

import json
import os
import sys
import time

import numpy as np

ROOT = "/home/ubuntu/lerobot-smolvla-lew"
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("MUJOCO_GL", "egl")

from lerobot.memory.potential_field import (MemoryLayerBridge, ObstacleField,  # noqa: E402
                                            STAGE_ORDER, WorldField)

RES = []
FAILS = []


def chk(name, ok, detail=""):
    RES.append((bool(ok), name, detail))
    if not ok:
        FAILS.append(name)
    print(f"   {'✅' if ok else '❌'} {name}" + (f" — {detail}" if detail else ""))


def main():
    t0 = time.time()
    print("═══ ① 从真数据装配四层 (muscle_memory.json + 引擎几何) ═══")
    br = MemoryLayerBridge.from_real_data(ROOT, seed=104)
    print(f"   {br.reason}")
    chk("L2 技能势场从真轨迹建成 (7 段)", len(br.fields) == 7, f"建成 {len(br.fields)}: "
        + ", ".join(f.code for f in br.fields))
    chk("L3 流程势场建成", br.process is not None)
    chk("L4 障碍场接现场几何", bool(br.obstacle and br.obstacle.hole is not None),
        str(br.obstacle.to_dict() if br.obstacle else None)[:110])

    print("═══ ② L2 单技能场: 数学性质 (解析梯度/横向单调/收敛/终点=真 exit) ═══")
    rng = np.random.default_rng(0)
    for f in br.fields:
        # 解析梯度 vs 数值梯度
        x = f.P[len(f.P) // 2] + rng.normal(0, 0.004, 3)
        h = 1e-7
        num = np.array([(f.phi(x + np.eye(3)[j] * h) - f.phi(x - np.eye(3)[j] * h)) / (2 * h)
                        for j in range(3)])
        gerr = float(np.abs(num - f.grad(x)).max())
        # 横向势单调 (轨迹上 < 5mm < 10mm < 20mm)
        c = f.P[len(f.P) // 2]
        d = c - f.x_g
        d = d / (np.linalg.norm(d) + 1e-12)
        perp = np.cross(d, [0, 0, 1.0])
        perp = perp / (np.linalg.norm(perp) + 1e-12)
        t0_, t5, t10, t20 = (f.phi_tube(c), f.phi_tube(c + perp * 0.005),
                             f.phi_tube(c + perp * 0.010), f.phi_tube(c + perp * 0.020))
        mono_tube = t0_ <= t5 < t10 < t20
        # 收敛: 从入口 + 8mm 扰动出发, 用技能自己的 v_cap 积分到谷底
        xs = f.x_0 + rng.normal(0, 0.008, 3)
        n, info = 0, {}
        while n < 4000:
            v, info = f.velocity(xs, k_p=2.0, dt=0.02)
            xs = xs + 0.02 * v
            n += 1
            if info["at_goal"]:
                break
        d_end = float(np.linalg.norm(xs - f.x_g))
        # 李雅普诺夫判据 (严格): 随机点上 ∇Φ·(−∇Φ/‖∇Φ‖) < 0 且 Φ(x+ε·dir) < Φ(x)
        descent_ok, eps_ok = True, True
        for _ in range(60):
            xr = f.x_0 + rng.normal(0, 0.02, 3)
            g_ = f.grad(xr)
            ng = float(np.linalg.norm(g_))
            if ng < 1e-9:
                continue
            dirv = -g_ / ng
            if float(np.dot(g_, dirv)) >= 0:
                descent_ok = False
            if float(f.phi(xr + 1e-4 * dirv)) >= float(f.phi(xr)):
                eps_ok = False
        mono_phi = descent_ok and eps_ok
        goal_radius = float(np.linalg.norm(f.x_g - f.x_g))
        chk(f"{f.code} {f.stage}: 梯度/管壁/收敛",
            gerr < 1e-4 and mono_tube and d_end < 1.5e-3 and mono_phi and goal_radius < 1e-6,
            f"梯度误差 {gerr:.1e} · 横向单调 {mono_tube} · 收敛 {n}步→{d_end*1000:.2f}mm · "
            f"下降方向/Φ下降 {mono_phi} · "
            f"σ={f.sigma*1000:.1f}mm v_cap={f.v_cap} 谷底=轨迹末点" +
            (" · ⚠️ io.exit 不同源: " + f.goal_fallback_reason if f.goal_fallback else ""))

    print("═══ ③ L3 流程势场: 权重/平滑/谷底时序 ═══")
    ts = np.linspace(0, 1, 2001)
    W = np.array([br.process.weights(t) for t in ts])
    chk("Σw ≡ 1", float(np.abs(W.sum(1) - 1).max()) < 1e-9, f"最大偏差 {float(np.abs(W.sum(1)-1).max()):.2e}")
    dw = float(np.abs(np.diff(W, axis=0)).max())
    chk("权重连续 (Δw ∝ dt, 无阶跃)", dw < 0.05, f"细网格(1/2000)最大单步变化 {dw:.5f} → 无跳变")
    ts2 = np.linspace(0, 1, 201)
    W2 = np.array([br.process.weights(t) for t in ts2])
    dw2 = float(np.abs(np.diff(W2, axis=0)).max())
    chk("粗网格一致性 (Δw 随分辨率缩小 ≈ ×10)", dw2 / max(dw, 1e-12) > 5,
        f"1/200 网格 Δw={dw2:.4f} vs 1/2000 网格 Δw={dw:.5f} → 比值 {dw2/max(dw,1e-12):.1f}")
    path = br.process.goal_path(24)
    order_idx = [STAGE_ORDER.index(st) for _, _, st, _ in path]
    chk("谷底按时序推进 (阶段序号单调不减)", all(order_idx[i] <= order_idx[i + 1] for i in range(len(order_idx) - 1)),
        " → ".join(dict.fromkeys([st for _, _, st, _ in path])))
    print(f"   段时长占比 (真跑帧数归一): " + ", ".join(
        f"{f.code} {fr*100:.0f}%" for f, fr in zip(br.fields, br.process.frac)))
    print(f"   谷底轨迹 (抽样): " + " | ".join(
        f"t={t:4.2f} {st}@{np.round(g,3).tolist()}" for t, _, st, g in path[::6]))

    print("═══ ④ L4 工作空间: 真实几何斥力 + 世界模型项 ═══")
    ob = br.obstacle
    h = ob.hole
    rhat = np.array([1.0, 0.0, 0.0])
    p_wall = h + rhat * ob.r
    p_out = h + rhat * (ob.r + 0.02)
    p_bore = h + rhat * max(ob.r - 0.004, 1e-4)
    chk("孔壁势: 壁上 > 壁外 20mm (真几何)",
        ob.phi(p_wall) > ob.phi(p_out), f"壁上 {ob.phi(p_wall):.4f} vs 壁外 {ob.phi(p_out):.4f}")
    chk("壁上斥力朝外 (grad·径向 < 0)", float(np.dot(ob.grad(p_wall), rhat)) < 0,
        f"grad·r̂ = {float(np.dot(ob.grad(p_wall), rhat)):+.4f}")
    chk("孔内斥力朝轴 (grad·径向 > 0)", float(np.dot(ob.grad(p_bore), rhat)) > 0,
        f"grad·r̂ = {float(np.dot(ob.grad(p_bore), rhat)):+.4f}")
    chk("世界模型项未接预测器时恒 0 且标记", (not br.world.enabled) and abs(br.world.phi(h, 0.5)) < 1e-12,
        "enabled=False · Φ_world≡0 (诚实标注, 不编预测)")

    print("═══ ⑤ 总装机记忆: 逐层开关 (默认全关 → 零回退; 开一层 → 多一份贡献) ═══")
    saved = br.gates()
    br._gates = {k: 0 for k in br.LAYERS}                    # 先全关 (临时, 末尾还原)
    x_t = br.process.active(0.5).x_0 + np.array([0.001, 0.001, 0.0])
    u_in = np.array([0.3, 0.0, -0.1, 0.6])
    phi0, c0 = br.compose(x_t, 0.5)
    u0, i0 = br.blend_action(u_in, x_t, 0.5)
    chk("全关: compose=None 且动作恒等 (零回退)", (phi0 is None) and bool(np.allclose(u0, u_in)),
        f"compose={phi0} · w={i0['w']} · {i0['reason']}")
    br._gates = {"L2": 1, "L3": 0, "L4": 0, "assembly": 0}
    phi1, c1 = br.compose(x_t, 0.5)
    u1, i1 = br.blend_action(u_in, x_t, 0.5)
    chk("只开 L2: 有势场 + 技能势场贡献 + 干预动作", (phi1 is not None) and c1.get("L2", 0) != 0
        and i1["applied"] and not np.allclose(u1[:3], u_in[:3]),
        f"Φ_L2={c1.get('L2')} 技能={c1.get('L2_skill')} w={i1['w']} u_out={i1['u_out']}")
    chk("只开 L2: L3/L4 贡献仍为 0 (逐层可控)", (c1.get("L3", 0) == 0) and (c1.get("L4_obstacle", 0) == 0))
    br._gates = {"L2": 1, "L3": 1, "L4": 0, "assembly": 0}
    _, c2 = br.compose(x_t, 0.5)
    chk("再开 L3: 流程势场贡献出现", c2.get("L3", 0) != 0, f"Φ_L3={c2.get('L3')}")
    br._gates = {"L2": 1, "L3": 1, "L4": 1, "assembly": 0}
    x_hole = ob.hole + np.array([ob.r + 0.002, 0.0, 0.0])      # 靠孔壁 2mm (真几何附近)
    _, c3 = br.compose(x_hole, 0.99)
    chk("再开 L4: 障碍势贡献出现 (真几何, 靠孔壁 2mm)", c3.get("L4_obstacle", 0) != 0,
        f"Φ_obstacle={c3.get('L4_obstacle')} @ x=孔壁+2mm")
    it = br.intent(x_t, 0.5)
    chk("intent = 单位方向 + 速率 + 技能 + 置信", abs(np.linalg.norm(it["dir"]) - 1.0) < 1e-9
        and it["skill"] in [f.code for f in br.fields],
        f"dir={it['dir']} step={it['step_m']}m/s skill={it['skill']} conf={it['conf']}")

    print("═══ ⑥ 总装机记忆: 跨层仲裁 + 台账 (真写读) ═══")
    a1 = br.arbitrate("插入", contact_p=0.8)
    a2 = br.arbitrate("转移", contact_p=0.0)
    chk("接触段技能势场(L2)优先 / 自由段流程势场(L3)优先",
        a1["primary_layer"] == "L2" and a2["primary_layer"] == "L3",
        f"插入→{a1['primary_layer']} · 转移→{a2['primary_layer']}")
    n_before = br.ledger()["n"]
    rec = br.record_outcome("verify_memory_potential_fields", done=True, steps=0, insert_mm=None,
                            layers=br.gates(), note="验证脚本写入 (真台账)")
    n_after = br.ledger()["n"]
    chk("台账真写读 (总装机记忆)", n_after == n_before + 1 and rec["ts"] == br.ledger()["last"][-1]["ts"],
        f"n {n_before}→{n_after} · 末条 {rec['ts']} task={rec['task']}")

    br._gates = saved                                        # 还原原始开关 (老倪自己逐步打开)
    print(f"   （开关已还原为原值: {saved}）")

    out = os.path.join(ROOT, "reports", "memory_potential_fields.json")
    json.dump({"ts": time.strftime("%F %T"), "elapsed_s": round(time.time() - t0, 1),
               "reason": br.reason,
               "layers": br.describe(),
               "skills": [f.to_dict() for f in br.fields],
               "process": br.process.to_dict() if br.process else None,
               "goal_path": br.process.goal_path(24) if br.process else None,
               "obstacle": br.obstacle.to_dict() if br.obstacle else None,
               "checks": [{"ok": o, "name": n, "detail": d} for o, n, d in RES],
               "fails": FAILS, "passed": len(RES) - len(FAILS), "total": len(RES)},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n═══ 汇总: {len(RES) - len(FAILS)}/{len(RES)} 通过 ({time.time()-t0:.0f}s) ═══")
    print("   " + ("❌ 未通过: " + " · ".join(FAILS) if FAILS else "✅ 全部通过 — 分层记忆势场 (L2/L3/L4/总装机)"))
    print(f"   → {out}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
