#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fit_intact_action_frame.py — INTACT 动作空间 ⇄ 引擎 u 空间 逐轴对齐性判定

问题 (200 步实测): 模型动作逐维 std [0.0452, 0.0076, 0.0404, 0.5694] vs 参考 [0.0703, 0.0537, 0.027, 0.0]
  ⇒ dy 塌到 14% · dz 过冲 150% · dx 反相 ⇒ L2 收口闸 veto_dir 200/200 ⇒ 模型动作 0 采纳。
本脚本回答一个**可判决**的问题:
  · 是"两个动作空间差一个逐轴线性映射" (约定不符 → 可用 calibrations/intact_action_map.json 对齐, 便宜)
  · 还是"模型压根没学到该动作分布" (能力不足 → 必须训练侧解决)

做法 (**同口径配对, 不污染**):
  1. 引擎装直驱 (install_direct_act) 但**闸开着** → 模型每帧真推理, 动作被闸否决 ⇒ env 仍走参考链
     ⇒ 模型看到的每一帧都是**参考轨迹上的帧** (off-policy 配对, 不是自我漂移后的帧) —— 配对合法。
  2. 逐帧取 (模型原始输出 rec['raw'][t] / 反归一化后 rec['act'][t], 参考 u_ff_vec[t])。
  3. 对引擎 4 轴 (dx,dy,dz,gripper) 各做: 在模型 8 维里搜最佳维 j + 最小二乘缩放 K
     (过原点, 允许负号) → 报 |corr| / R²。
判据: 4 轴平均 R² ≥ 0.5 且有轴 corr>0.5 ⇒ 线性可对齐 (写标定); 否则 ⇒ 能力不足 (训练侧)。

跑法: CUDA_VISIBLE_DEVICES= gui-venv311/bin/python tools/fit_intact_action_frame.py [steps] [seed]
"""
from __future__ import annotations

import json
import os
import sys
import time

import numpy as np

STEPS = int(sys.argv[1]) if len(sys.argv) > 1 else 400
SEED = int(sys.argv[2]) if len(sys.argv) > 2 else 0
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
os.environ.setdefault("SS_INTACT", "1")
os.environ.setdefault("SS_INTACT_SHADOW", "1")
os.environ.setdefault("SS_INTACT_EVERY", "1")
os.environ.setdefault("SS_DIRECT_GATE", "1")      # ★ 关键: 闸开着 → 参考链驱动 → 配对不污染

AX = ["dx", "dy", "dz", "gripper"]


def main() -> int:
    from state_space_sim_real import RealStateSpaceSim          # noqa: PLC0415
    from probe_l4_callchain import build_intact_node            # noqa: PLC0415
    import intact_direct_rollout as idr                         # noqa: PLC0415

    LOGS: list[str] = []
    sim = RealStateSpaceSim(seed=SEED, vision=False, mode="insert",
                            log=lambda *a: LOGS.append(" ".join(str(x) for x in a)))
    nd, stf = build_intact_node()
    am, asd, _meta = idr.load_stats(stf)
    # ★ 拿**完整 chunk** (8 维), 而不是直驱路硬选的 slot 0:4 ——
    #   若真实布局不是"前 4 维=当前帧", 只搜 4 维会把最佳维系统性搜错 (标 slice 就靠这个)。
    CHUNKS: list[np.ndarray] = []
    try:
        from lerobot.policies.intact.service import IntactIntentService   # noqa: PLC0415
        _orig_once = IntactIntentService.run_once
        def _wrap_once(self, *a, **kw):
            rep = _orig_once(self, *a, **kw)
            out = getattr(self, "last_out", None)
            ch = getattr(out, "chunk", None) if out is not None else None
            if ch is not None:
                CHUNKS.append(np.asarray(ch, dtype=float).copy())
            return rep
        IntactIntentService.run_once = _wrap_once
        print(f"✅ 完整 chunk 捕获已装: {IntactIntentService.__module__}")
    except Exception as e:                                          # noqa: BLE001
        print(f"⚠️ 完整 chunk 捕获失败 ({type(e).__name__}: {e}) → 退化为 rec['raw'] 4 维")
    rec, stt = idr.install_direct_act(sim, nd, am, asd, infer_every=1)
    sim.attach_intact(nd, None)
    sim._intact_drive = {"node": nd, "rec": rec, "state": stt}

    t0 = time.time()
    tr = sim.run(max_steps=STEPS)
    dt = time.time() - t0

    raw = np.asarray(rec.get("raw", []), dtype=float)          # 模型原始输出 (归一化空间)
    act = np.asarray(rec.get("act", []), dtype=float)          # 反归一化后 (env 动作空间)
    ref = np.asarray(tr.get("u_ff_vec"), dtype=float)          # 参考 (教师) 控制向量
    n = min(len(raw), len(ref))
    # 完整 chunk: 每帧取第 0 行 (当前步的 D_official 维)
    F = None
    if CHUNKS:
        try:
            F = np.stack([np.asarray(c, dtype=float)[0].ravel() for c in CHUNKS[:n]])
            print(f"✅ 完整 chunk 矩阵: {F.shape} (n × D_official)")
        except Exception as e:                                      # noqa: BLE001
            print(f"⚠️ chunk 堆叠失败: {type(e).__name__}: {e}")
            F = None
    print("=" * 84)
    print(f"INTACT 动作空间 ⇄ 引擎 u 空间 逐轴判定 · steps={STEPS} · seed={SEED} · 用时 {dt:.1f}s")
    print("=" * 84)
    print(f"样本: 模型 {len(raw)} 帧 · 参考 {len(ref)} 帧 → 配对 n={n}")
    print(f"归一化统计源: {stf}")
    print(f"  mean={np.round(am, 4).tolist()}  std={np.round(asd, 4).tolist()}")
    if n < 30:
        print("❌ 样本不足, 无法判定")
        return 1
    R, A, U = raw[:n], act[:n], ref[:n]
    print(f"\n① 分布对照 (原始空间)")
    print(f"{'':10s}{'模型std':>10s}{'参考std':>10s}{'比值':>9s}{'模型均值':>10s}{'参考均值':>10s}")
    for d, ax in enumerate(AX):
        ms, rs = float(R[:, d].std()), float(U[:, d].std())
        ratio = ms / rs if abs(rs) > 1e-9 else float("nan")
        print(f"  {ax:8s}{ms:10.4f}{rs:10.4f}{ratio:9.3f}{float(R[:, d].mean()):10.4f}{float(U[:, d].mean()):10.4f}")
    # 参考零帧 (夹爪/静止阶段) 会影响拟合 → 报占比并同时给"非零参考帧"结果
    nz = np.abs(U[:, :3]).sum(axis=1) > 1e-6
    print(f"② 参考 xyz 非零帧: {int(nz.sum())}/{n} (拟合用非零帧更干净)")

    print(f"\n③ 逐轴最佳线性对齐 (搜维范围: {'完整 chunk 全部 ' + str(F.shape[1]) + ' 维' if F is not None else '直驱 slot 4 维'}; 过原点最小二乘, 允许负号)")
    print(f"{'引擎轴':8s}{'最佳模型维':>11s}{'corr':>8s}{'K(缩放)':>10s}{'R²':>8s}   判定")
    M = F if F is not None else R
    res = {}
    for d, ax in enumerate(AX):
        y = U[:, d]
        best = None
        for j in range(M.shape[1]):
            x = M[:, j]
            if x.std() < 1e-9:
                continue
            # 用非零参考帧拟合 (夹爪在停爪阶段是 0, 会把 K 往 0 拉)
            m = nz if d < 3 else np.ones(n, bool)
            if m.sum() < 20:
                m = np.ones(n, bool)
            xx, yy = x[m], y[m]
            if xx.std() < 1e-9:
                continue
            K = float((xx * yy).sum() / max((xx * xx).sum(), 1e-12))
            pred = K * xx
            ss_res = float(((yy - pred) ** 2).sum())
            ss_tot = float(((yy - yy.mean()) ** 2).sum()) + 1e-12
            r2 = 1.0 - ss_res / ss_tot
            c = float(np.corrcoef(xx, yy)[0, 1]) if xx.std() > 1e-9 else 0.0
            if best is None or abs(c) > abs(best["corr"]):
                best = {"j": j, "corr": c, "K": K, "r2": r2}
        if best is None:
            print(f"  {ax:8s}  (模型该维全零, 无信息)")
            res[ax] = None
            continue
        verdict = ("✅ 线性可对齐" if abs(best["corr"]) >= 0.5 else
                   ("🟡 弱相关" if abs(best["corr"]) >= 0.25 else "❌ 无关 (能力不足)"))
        print(f"  {ax:8s}{best['j']:>11d}{best['corr']:>8.3f}{best['K']:>10.4f}{best['r2']:>8.3f}   {verdict}")
        res[ax] = best

    oks = [v for v in res.values() if v]
    strong = [v for v in oks if abs(v["corr"]) >= 0.5]
    mid = [v for v in oks if 0.25 <= abs(v["corr"]) < 0.5]
    print("\n④ 判决")
    print(f"  |corr|≥0.5 的轴: {len(strong)}/4 ({[AX[i] for i, v in enumerate(res.values()) if v and abs(v['corr'])>=0.5]})")
    print(f"  0.25≤|corr|<0.5 的轴: {len(mid)}/4")
    if len(strong) >= 3:
        print("  ⇒ 结论: **动作空间差一个逐轴线性映射** (约定问题) → 可用 models/intact_action_map.json 对齐")
    elif len(strong) + len(mid) >= 3:
        print("  ⇒ 结论: **部分可对齐** → 定向重训/标定结合; 不可对齐的轴说明模型该轴信息不足")
    else:
        print("  ⇒ 结论: **模型未学到该动作分布** (能力不足, 非约定问题) → 必须训练侧解决, 标定无意义")
    out = {"steps": STEPS, "seed": SEED, "n_pairs": int(n), "stats_src": stf,
           "model_std": [float(R[:, d].std()) for d in range(R.shape[1])],
           "ref_std": [float(U[:, d].std()) for d in range(4)],
           "fit": res, "strong_axes": len(strong), "mid_axes": len(mid),
           "model_act_sample": R[:200].tolist(), "ref_u_sample": U[:200].tolist()}
    os.makedirs(os.path.join(ROOT, "reports"), exist_ok=True)
    p = os.path.join(ROOT, "reports", f"intact_action_frame_fit_seed{SEED}_{STEPS}.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n配对样本已落盘: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
