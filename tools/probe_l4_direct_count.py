#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_l4_direct_count.py — L4 直驱路 (install_direct_act) 到底有没有把模型动作喂进 env

背景: L4 有两条 INTACT 路径, 前一步的调用链探针只照出了前馈槽位(_intact_u_ff, 被适配层闸拒),
      没照出**直驱路**(sim._direct_act —— 引擎在 _direct_act 非 None 时直接用模型动作做 env.step)。
      本探针只认直驱路的运行时计数 + 逐帧动作值, 用来定性"L4 到底是不是模型在驱动"。

跑法 (不动 GPU):
  CUDA_VISIBLE_DEVICES= gui-venv311/bin/python tools/probe_l4_direct_count.py 30
"""
from __future__ import annotations

import os
import sys

import numpy as np

STEPS = int(sys.argv[1]) if len(sys.argv) > 1 else 30
os.environ.setdefault("SS_INTACT", "1")
os.environ.setdefault("SS_INTACT_SHADOW", "1")
os.environ.setdefault("SS_INTACT_EVERY", "1")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "gui"))


def main() -> int:
    from state_space_sim_real import RealStateSpaceSim          # noqa: PLC0415
    LOGS: list[str] = []
    sim = RealStateSpaceSim(seed=0, vision=False, mode="insert",
                            log=lambda *a: LOGS.append(" ".join(str(x) for x in a)))
    # 与 probe_l4_callchain 的 L4 场景同口径: 直驱装配 + attach_intact(adapter=None)
    from probe_l4_callchain import build_intact_node            # noqa: PLC0415
    import intact_direct_rollout as idr                         # noqa: PLC0415
    nd, stf = build_intact_node()
    am, asd, meta = idr.load_stats(stf)
    print(f"归一化统计源: {stf}")
    print(f"  mean={np.asarray(am).round(4).tolist()}  std={np.asarray(asd).round(4).tolist()}")
    print(f"  文件字段: {sorted(meta.keys())[:8]}")
    rec, stt = idr.install_direct_act(sim, nd, am, asd, infer_every=1)
    sim.attach_intact(nd, None)
    sim._intact_drive = {"node": nd, "rec": rec, "state": stt}

    tr = sim.run(max_steps=STEPS)

    n_act = len(rec.get("act", []))
    n_raw = len(rec.get("raw", []))
    print("=" * 78)
    print(f"L4 直驱路取证 · 步数={STEPS}")
    print("=" * 78)
    print(f"① sim._direct_act 已装载: {getattr(sim, '_direct_act', None) is not None}")
    print(f"② 直驱记录 rec['act'] (模型动作喂 env 的次数) = {n_act}")
    print(f"   rec['raw'] (归一化逆变换后) = {n_raw}")
    stages = rec.get("stage", [])
    if stages:
        from collections import Counter
        print(f"   rec['stage'] 分布 = {dict(Counter(stages))}")
    cn = rec.get("chunk_norm", [])
    if cn:
        print(f"   chunk_norm: 均值 {np.mean(cn):.4f} · 最小 {np.min(cn):.4f} · 最大 {np.max(cn):.4f}")
    aa = np.asarray(rec.get("act", []), dtype=float)
    if aa.size:
        print(f"③ 模型动作 (喂给 env 的 4D, 前 5 帧):\n{np.round(aa[:5], 4)}")
        print(f"   |逐维 std| = {np.round(aa.std(axis=0), 4).tolist()}  (全 0 = 没真驱动)")
        print(f"   |逐维均值| = {np.round(aa.mean(axis=0), 4).tolist()}")
    # 与解析链对照: trace 里的 u_exec (实际执行)
    ex = tr.get("u_exec_vec") or tr.get("u_ff_vec")
    if ex is not None:
        ex = np.asarray(ex, dtype=float)
        nz = np.abs(ex).sum(axis=1) > 0
        print(f"④ trace u_exec: 帧数 {ex.shape[0]} · 非零帧 {int(nz.sum())} · "
              f"逐维 std {np.round(ex.std(axis=0), 4).tolist()}")
    print(f"⑤ 直驱路是否真决定动作: {'是 ✅' if n_act > 0 else '否 ❌ (模型动作没进 env)'}")
    print(f"   引擎内部统计 _intact_stats: {dict(sim._intact_stats)}")
    # ⑦ L2 收口闸 (决定"模型动作是被采纳还是被否决") —— 本探针的核心
    import json as _json
    def _J(o):
        try:
            return _json.loads(_json.dumps(o, default=lambda x: (x.tolist() if hasattr(x, "tolist")
                                                                else str(x))))
        except Exception:                                       # noqa: BLE001
            return str(o)[:400]
    _keys = ("n", "calls", "err", "gate", "dit", "l2_ready", "l2_err", "skill_ctx_dim",
             "skill_ctx_nonzero", "u_ff_source", "l3_cond_ready", "decoder", "evidence")
    print(f"⑦ 直驱 state (含 L2 收口闸计数): {_json.dumps(_J({k: stt.get(k) for k in _keys if k in stt}), ensure_ascii=False)}")
    g = stt.get("gate") or {}
    if g.get("n"):
        _n = max(1, int(g["n"]))
        print(f"   → 闸通过率: 融合 {g.get('blend',0)}/{_n} · 否决方向 {g.get('veto_dir',0)}/{_n} · "
              f"否决幅值 {g.get('veto_mag',0)}/{_n} · 交回参考 {g.get('ref_zero',0)}/{_n} · "
              f"阶段外 {g.get('stage_out',0)}/{_n}")
        if g.get("cos_used"):
            print(f"   → 方向一致性 w=cos: 均值 {g.get('cos_sum',0.0)/max(1,g.get('cos_used',1)):.3f} "
                  f"(∈0..1; <0 = 与参考反相) · 区间 [{g.get('w_min')}, {g.get('w_max')}]")
    fin = tr.get("final") or {}
    print(f"⑧ 结局: dist_min={fin.get('dist_min')} · done_any={fin.get('done_any')} · "
          f"V_last={fin.get('V_last')} · 阶段计数={fin.get('stage_counts')}")
    print(f"⑨ 模型动作 vs env 实际执行: rec['act'] 有 {n_act} 帧, "
          f"_direct_act={getattr(sim, '_direct_act', None) is not None} "
          f"⇒ {'模型动作被 env 采纳' if getattr(sim, '_direct_act', None) is not None else '模型动作未采纳 (被闸否决 → 执行参考)'}")
    warn = [w for w in LOGS if ("L4" in w or "INTACT" in w or "直驱" in w)]
    print(f"⑥ 引擎自报日志 (前 6 条): {warn[:6]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
