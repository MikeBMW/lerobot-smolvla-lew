#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""⚖️ L4 通道 同口径多臂 A/B (老倪门槛: 交付=有提升非仅不回退)

默认三臂 (每臂独立进程, 同 seed, 只差开关):
  A0 = 基线 (L4 意图线关/不注入)               SS_L4_INTACT=1 只有; 不设 SS_L4_FIBER/SS_L4_ALIGN
  A1 = 纤维丛开                              SS_L4_FIBER=1
  A2 = 纤维丛 + 方向/幅度对齐 (Step ①)        SS_L4_FIBER=1 SS_L4_ALIGN=1

每臂记录: 任务终态 (steps/done/dist_min/dist_last) · 李雅普诺夫 V (first/last/min) · 阶段分布
        · L2 收口闸 (pass/veto/veto_dir/veto_mag/blend) · 对齐层 (applied/cos 前→后/幅度比)
        · 纤维丛 (ran/‖h‖/κ_tor/‖Ω‖/cos∠) · DiT (ok/cond_dim)

判定 (实质性阈值 = 相对 1%): 逐 seed 比 V_last 与 dist_min (都是越小越好);
  某臂在 ≥2/3 seed 上优于 A0 → 记该臂"有实质提升候选"; 否则"无实质提升 (仅叠加/不回退)"。
  同时打印收口闸通过率 (对齐的目标就是把它抬起来) —— 但**通过率上升 ≠ 提升**, 只有任务/稳定性指标才算。

退出码: 0 = 至少一臂有提升候选; 3 = 无提升; 2 = 跑失败。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = "/home/ubuntu/lerobot-venv/bin/python"
PROBE = os.path.join(ROOT, "tools", "probe_l4_callchain.py")
MAT = 0.01

ARMS = [("A0_基线", {}),
        ("A1_纤维丛", {"SS_L4_FIBER": "1"}),
        ("A2_纤维丛+对齐", {"SS_L4_FIBER": "1", "SS_L4_ALIGN": "1"})]


def run_arm(seed: int, tag: str, envx: dict, steps: int) -> dict:
    dst = os.path.join(ROOT, "reports", f"ab2_{tag}_s{seed}.json")
    env = dict(os.environ)
    for k in ("SS_L4_FIBER", "SS_L4_ALIGN", "SS_L4_INTENT_LINE", "SS_L4_DIT"):
        env.pop(k, None)
    env.pop("SS_L4_FIBER_DATA", None)
    env.pop("SS_L4_ALIGN_DATA", None)
    env.update({"SS_PROBE_SEED": str(seed), "SS_L4_AUDIT_JSON": dst})
    env.update(envx)
    p = subprocess.run([PY, PROBE, "L4audit", str(steps)], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=3600)            # noqa: S603
    try:
        return json.load(open(dst, encoding="utf-8"))
    except Exception:                                                          # noqa: BLE001
        return {"err": f"无审计 json rc={p.returncode}", "stderr": p.stderr[-300:]}


def rel_improve(a: float | None, b: float | None) -> float:
    """b 相对 a 的相对改善 (正 = b 更小 = 更好); 不可比 → 0。"""
    if a is None or b is None or abs(a) < 1e-12:
        return 0.0
    return (a - b) / abs(a)


def main() -> int:
    args = sys.argv[1:]
    steps = int(args[args.index("--steps") + 1]) if "--steps" in args else 150
    seeds = ([int(x) for x in args[args.index("--seeds") + 1].split(",")]
             if "--seeds" in args else [0, 2, 5])
    print(f"⚖️ L4 多臂 A/B · 步数 {steps} · seeds {seeds} · 臂={[t for t, _ in ARMS]}")
    verdict = {t: {"better": 0, "worse": 0} for t, _ in ARMS[1:]}
    summary_rows = []
    for s in seeds:
        res = {}
        for tag, envx in ARMS:
            res[tag] = run_arm(s, tag, envx, steps)
        base = res["A0_基线"].get("final", {}) or {}
        gb = (res["A0_基线"].get("summaries", {}).get("l4", {}) or {})
        print(f"\n── seed {s} ──  基线: steps={base.get('steps')} done={base.get('done_any')} "
              f"dist_min={base.get('dist_min')} V_last={base.get('V_last')} "
              f"闸: pass={gb.get('gate_pass')} veto={gb.get('l2_veto')}(dir={gb.get('l2_veto_dir')},"
              f"mag={gb.get('l2_veto_mag')}) blend={gb.get('blend')}")
        for tag, _ in ARMS[1:]:
            f = res[tag].get("final", {}) or {}
            sm = res[tag].get("summaries", {}) or {}
            l4, fib, al = sm.get("l4", {}) or {}, sm.get("fiber", {}) or {}, res[tag].get("align", {}) or {}
            rv = rel_improve(base.get("V_last"), f.get("V_last"))
            rd = rel_improve(base.get("dist_min"), f.get("dist_min"))
            if rv >= MAT or rd >= MAT:
                verdict[tag]["better"] += 1
                v = "✅更优"
            elif rv <= -MAT or rd <= -MAT:
                verdict[tag]["worse"] += 1
                v = "❌更差"
            else:
                v = "➖无实质差异"
            print(f"  {tag:14s} dist_min={f.get('dist_min')} V_last={f.get('V_last')} "
                  f"阶段={f.get('stage_counts')}")
            print(f"    闸: pass={l4.get('gate_pass')} veto={l4.get('l2_veto')}"
                  f"(dir={l4.get('l2_veto_dir')},mag={l4.get('l2_veto_mag')}) blend={l4.get('blend')} · "
                  f"对齐 applied={al.get('applied')} cos {al.get('cos_before_mean')}→{al.get('cos_after_mean')} "
                  f"幅度比={al.get('ratio_after_mean')}")
            print(f"    纤维丛 ran={fib.get('ran')} ‖h‖={fib.get('h_norm_mean')} "
                  f"κ_tor={fib.get('kappa_tor_mean')} ‖Ω‖={fib.get('kappa_curv_mean')} "
                  f"cos∠={fib.get('cos_geo_mean')} · ΔV={rv:+.2%} Δdist={rd:+.2%} → {v}")
            summary_rows.append({"seed": s, "arm": tag, "final": f,
                                 "gate": {k: l4.get(k) for k in ("gate_pass", "l2_veto",
                                                                 "l2_veto_dir", "l2_veto_mag", "blend")},
                                 "align": al, "fiber": {k: fib.get(k) for k in
                                                        ("ran", "h_norm_mean", "kappa_tor_mean",
                                                         "kappa_curv_mean", "cos_geo_mean")},
                                 "rel_V": rv, "rel_dist": rd, "verdict": v})
    print("\n小结 (相对基线 A0, 实质阈值 1%):")
    any_gain = False
    for tag, _ in ARMS[1:]:
        b, w = verdict[tag]["better"], verdict[tag]["worse"]
        ok = b > w and b >= 2
        any_gain = any_gain or ok
        print(f"  {tag:14s} 更优 {b} / 更差 {w} / 共 {len(seeds)} seed → "
              f"{'✅ 有实质提升候选' if ok else '➖ 无实质提升'}")
    print("结论: " + ("✅ 至少一臂有提升候选 → 可进下一轮 (更多 seed + 视频证据)"
                     if any_gain else "➖ 全部无提升 (仅叠加/不回退) → 按门槛不得进默认档"))
    with open(os.path.join(ROOT, "reports", "ab_l4_arms_summary.json"), "w", encoding="utf-8") as f:
        json.dump({"steps": steps, "seeds": seeds, "arms": [t for t, _ in ARMS],
                   "verdict": {t: verdict[t] for t, _ in ARMS[1:]}, "rows": summary_rows,
                   "gain": bool(any_gain)}, f, ensure_ascii=False, indent=1)
    return 0 if any_gain else 3


if __name__ == "__main__":
    raise SystemExit(main())
