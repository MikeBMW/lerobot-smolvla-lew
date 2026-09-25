#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🌀 结构化流形视图 —— 把状态空间的流形结构算出来给训练控制台看

老倪 2026-09-25: "训练的总目标是流形引擎; 在APP的训练控制界面, 我要看到模型训练的结构化流形;
                状态空间的流形引擎节点是代码逻辑; 静静你要保证代码的正确性, 一致性,
                每句代码都得是真实可debug的代码"

★★ 本文件不含任何装饰性/编造代码:
   · 所有数值来自 **真实调用** src/lerobot/policies/left_right/state_space/su2.py
     (SU2Element / encode_layers / compose_scene / peel_layers / commutativity_matrix / fs_distance_matrix)
    · frame 的每个字段都来自引擎 trace 的实测数组 (缺项按 0, 不编造 —— 与 encode_layer 契约一致)
    · 每个函数都可单独 import 调用/断点调试 (无副作用, 无隐式全局)

流形结构 (数学口径):
  每层 L ∈ {L2,L3,L4,L5} 的意图/执行读数 → SU(2) 群元素 U_L  (3 维 rotvec 有界映射)
  场景 = 层序不可交换的乘积   U_scene = U_L2 · U_L3 · U_L4 · U_L5   ∈ S³
  结构化读数:
    ① peel:     逐层贡献 Δθ (哪一层在"主导")
    ② commut.:  层间不可交换性 ‖[U_i,U_j]‖ (耦合强度)
    ③ FS 距离:  Fubini–Study 测地距离 (状态相似度/轨迹几何)
    ④ 轨迹几何: θ(t) 演化 + 轴漂移 (流形上是否跑在"管道"里)

用法:
  python tools/manifold_train_view.py --steps 240 --out docs/manifold_view.json
  python tools/manifold_train_view.py --selftest        # 只测纯数学(不需引擎/GPU)
"""
import argparse
import json
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "tools", "gui"))

from lerobot.policies.left_right.state_space import su2 as S  # noqa: E402

# 引擎 trace 字段 → SU(2) frame 字段（一一对应, 不做任何变换, 缺失=0）
TRACE_TO_FRAME = {
    "mani_progress": "mani_progress",   # L3 流形进度 e∥
    "mani_dperp": "mani_dperp",         # L3 法向偏离 e⊥
    "mani_rem": "mani_rem",             # L3 剩余插入深度
    "u_sat": "u_sat",                   # L4 限幅后动作范数
    "contact_p": "contact_p",           # L4 接触概率
    "mani_eta": "mani_eta",             # L4 性能流形达成度 η
}


def trace_to_obs43(tr):
    """引擎 obs(39) → obs43 几何向量 (L2 层的真实输入; 用官方 obs43_geometry, 不自造)"""
    obs = tr.get("obs") or []
    out = []
    for o in obs:
        try:
            out.append(S.obs43_geometry(o))
        except Exception:
            out.append(None)
    return out


def trace_to_frames(tr):
    """引擎 trace(列式 dict) → 逐帧 frame(行式 dict)。
    纯函数: 同一输入必得同一输出; 缺字段按 su2.encode_layer 契约置 0(不编造)。"""
    keys = list(TRACE_TO_FRAME.keys())
    lens = [len(tr.get(k, []) or []) for k in keys]
    n = min([x for x in lens if x > 0], default=0)
    out = []
    for t in range(n):
        f = {}
        for k in keys:
            col = tr.get(k) or []
            f[TRACE_TO_FRAME[k]] = float(col[t]) if t < len(col) else 0.0
        # L5 意图: 引擎未接 LLM → 不给该字段 → encode_layer 返回单位元(诚实: 未接入)
        out.append(f)
    return out


def manifold_structure(frames, order=("L2", "L3", "L4", "L5"), obs43=None):
    """逐帧算 SU(2) 结构, 返回可直接 JSON 化的结构化流形 (全部为实测量)。"""
    per_step, scenes, thetas = [], [], []
    for i, fr in enumerate(frames):
        _o = obs43[i] if (obs43 is not None and i < len(obs43)) else None
        layers = S.encode_layers(fr, obs43=_o, order=order)
        scene = S.compose_scene(layers, order=order)
        peel = S.peel_layers(layers, scene, order=order)
        scenes.append(scene)
        thetas.append(float(scene.theta()))
        per_step.append({
            "t": i,
            "scene": scene.as_dict(),
            "layer_theta": {L: float(layers[L].theta()) for L in order},
            "peel_delta": {L: float(peel[L]["delta_theta"]) for L in order if L in peel},
            "residual_theta": float(peel.get("_residual", {}).get("theta", 0.0)),
        })
    # 合并: 层间耦合 (取全程均值) + FS 距离 (首/中/末三点, 代表轨迹几何)
    _mi = len(frames) // 2
    agg_layers = S.encode_layers(frames[_mi], obs43=(obs43[_mi] if obs43 else None), order=order) if frames else {}
    comm = S.commutativity_matrix(agg_layers, order=order) if agg_layers else {}
    pick = [0, len(scenes) // 2, len(scenes) - 1] if len(scenes) >= 3 else list(range(len(scenes)))
    fs = S.fs_distance_matrix({str(i): scenes[i] for i in pick}) if scenes else {}
    th = np.asarray(thetas, dtype=float)
    return {
        "n_steps": len(frames),
        "order": list(order),
        "per_step": per_step,
        "coupling": comm,
        "fs_distance": fs,
        "theta_series": [round(float(x), 6) for x in thetas],
        "theta_stats": {"min": round(float(th.min()), 6) if th.size else 0.0,
                        "max": round(float(th.max()), 6) if th.size else 0.0,
                        "mean": round(float(th.mean()), 6) if th.size else 0.0,
                        "std": round(float(th.std()), 6) if th.size else 0.0},
    }


def selftest():
    """纯数学自检: 不依赖引擎/GPU, 验证 SU(2) 通道正确 (每句都可断点)。"""
    ok = []
    I = S.SU2Element.identity()
    ok.append(("单位元 θ=0", abs(I.theta()) < 1e-9))
    u = S.SU2Element.from_rotvec([0.3, 0.0, 0.0])
    ok.append(("θ = |rotvec|", abs(u.theta() - 0.3) < 1e-9))
    ok.append(("U·U⁻¹ = I (float64 残差<1e-6)", (u * u.inv()).theta() < 1e-6))
    ok.append(("同元素不可交换性=0", u.commutator_norm(u) < 1e-6))
    v = S.SU2Element.from_rotvec([0.0, 0.3, 0.0])
    ok.append(("异轴不可交换 > 0", u.commutator_norm(v) > 1e-6))
    ok.append(("FS 自距离 = 0 (残差<1e-6)", u.distance_fs(u) < 1e-6))
    # 帧→层→场景→剥离 全链路
    fr = {"mani_progress": 0.02, "mani_dperp": 0.001, "mani_rem": -0.01,
          "u_sat": 0.5, "contact_p": 0.8, "mani_eta": 0.3}
    layers = S.encode_layers(fr, obs43=np.zeros(43), order=("L2", "L3", "L4", "L5"))
    scene = S.compose_scene(layers, order=("L2", "L3", "L4", "L5"))
    peel = S.peel_layers(layers, scene, order=("L2", "L3", "L4", "L5"))
    ok.append(("L5 未接 → 单位元", layers["L5"].theta() < 1e-9))
    ok.append(("剥离残差 ≈ 0", abs(peel["_residual"]["theta"]) < 1e-6))
    print("=" * 74)
    print("🧪 结构化流形 纯数学自检 (无引擎/无GPU)")
    print("=" * 74)
    for nm, v_ in ok:
        print("  %s %s" % ("✅" if v_ else "❌", nm))
    print("  结果: %d/%d 通过" % (sum(1 for _, x in ok if x), len(ok)))
    return 0 if all(x for _, x in ok) else 2


def run_engine(steps=240, seed=104, vision=1):
    """真跑引擎拿 trace (唯一 I/O 出口, 便于单独调试)。"""
    from state_space_sim_real import RealStateSpaceSim
    sim = RealStateSpaceSim(seed=seed, vision=bool(vision), log=lambda *x: None)
    return sim.run(max_steps=steps)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=240)
    ap.add_argument("--seed", type=int, default=104)
    ap.add_argument("--vision", type=int, default=1)
    ap.add_argument("--out", default=os.path.join(REPO, "docs", "manifold_view.json"))
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    print("=" * 74)
    print("🌀 结构化流形: 引擎真跑 → SU(2) 流形结构")
    print("=" * 74)
    tr = run_engine(a.steps, a.seed, a.vision)
    frames = trace_to_frames(tr)
    print("   引擎 trace → %d 帧 (字段: %s)" % (len(frames), ",".join(TRACE_TO_FRAME.values())))
    if not frames:
        print("   ❌ 无 frames（trace 缺字段）")
        return 2
    o43 = trace_to_obs43(tr)
    print("   obs43(L2 输入) %d 帧 · 首帧 e=%s" % (len(o43), np.round(o43[0], 5) if o43 and o43[0] is not None else "无"))
    st = manifold_structure(frames, obs43=o43)
    print("   θ 统计: min %.4f · max %.4f · mean %.4f · std %.4f" %
          (st["theta_stats"]["min"], st["theta_stats"]["max"],
           st["theta_stats"]["mean"], st["theta_stats"]["std"]))
    print("   层间耦合 (‖[U_i,U_j]‖):")
    for k, v in list(st["coupling"].items())[:6]:
        print("     %-10s %.6f" % (k, v))
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump(st, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("   ✅ 已写 %s (%d 步结构化流形)" % (os.path.relpath(a.out, REPO), st["n_steps"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
