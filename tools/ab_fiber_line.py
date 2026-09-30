#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""⚖️ 纤维丛通道 同口径 A/B (老倪门槛: 交付=有提升非仅不回退)

比什么 (每臂独立进程, 同 seed, 只差 SS_L4_FIBER):
  · 任务级: steps / done / dist_min(末端到目标最近距离) / 阶段分布
  · 稳定性判据 (I4, 与 layered-capability-stack 技能一致): 李雅普诺夫 V=½‖e‖² 的 first/last/min
      —— V 沿阶段**不升**才算"导引有效"; 两臂比较谁更低/更单调
  · 控制信号: u_ff 与 u_int 方向一致性(cos)、L2 收口闸否决计数(veto_dir/veto_mag)
  · 新通道自身: fiber ran/‖h_z‖/κ_tor/‖Ω‖/cos∠ + DiT cond_dim/applied

判定 (脚本自己给, 不靠人眼):
  fiber=1 臂在 V_last 或 dist_min 上**优于** fiber=0 臂 (3 seed 中 ≥2 个 seed 同向) → 记为"有提升候选"
  否则 → 记为"无提升 (仅叠加/不回退)"，不得进默认档。
退出码: 0 = 有提升候选; 3 = 无提升 (两者都算正常跑完), 2 = 跑失败。

用法: python3 tools/ab_fiber_line.py [--steps 150] [--seeds 0,2,5]
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = "/home/ubuntu/lerobot-venv/bin/python"
PROBE = os.path.join(ROOT, "tools", "probe_l4_callchain.py")


def run_arm(seed: int, fiber: int, steps: int) -> dict:
    dst = os.path.join(ROOT, "reports", f"ab_fiber_s{seed}_f{fiber}.json")
    env = dict(os.environ)
    env.update({"SS_PROBE_SEED": str(seed), "SS_L4_AUDIT_JSON": dst, "SS_L4_FIBER": str(fiber)})
    env.pop("SS_L4_FIBER_DATA", None)
    if fiber == 0:
        env.pop("SS_L4_FIBER", None)
    p = subprocess.run([PY, PROBE, "L4audit", str(steps)], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=3600)            # noqa: S603
    try:
        return json.load(open(dst, encoding="utf-8"))
    except Exception:                                                          # noqa: BLE001
        return {"err": f"无审计 json rc={p.returncode}", "stderr": p.stderr[-300:]}


def main() -> int:
    args = sys.argv[1:]
    steps = int(args[args.index("--steps") + 1]) if "--steps" in args else 150
    seeds = ([int(x) for x in args[args.index("--seeds") + 1].split(",")]
             if "--seeds" in args else [0, 2, 5])
    print(f"⚖️ 纤维丛 A/B · 步数 {steps} · seeds {seeds} · 每臂独立进程 · 只差 SS_L4_FIBER")
    rows, better, worse = [], 0, 0
    for s in seeds:
        a = run_arm(s, 0, steps)
        b = run_arm(s, 1, steps)
        fa, fb = a.get("final", {}) or {}, b.get("final", {}) or {}
        fa_, fb_ = a.get("summaries", {}), b.get("summaries", {})
        print(f"\n── seed {s} ──")
        for tag, f, sm in (("fiber=0", fa, fa_), ("fiber=1", fb, fb_)):
            fib = sm.get("fiber", {}) or {}
            dit = sm.get("l4_dit", {}) or {}
            il = sm.get("il", {}) or {}
            print(f"  {tag}: steps={f.get('steps')} done={f.get('done_any')} "
                  f"dist_min={f.get('dist_min')} dist_last={f.get('dist_last')} "
                  f"V_first={f.get('V_first')} V_last={f.get('V_last')} V_min={f.get('V_min')}")
            print(f"         阶段={f.get('stage_counts')}")
            print(f"         L4: il.applied={il.get('applied')} veto_dir={sm.get('l4',{}).get('l2_veto_dir')}"
                  f"/veto_mag={sm.get('l4',{}).get('l2_veto_mag')} · "
                  f"DiT ok={dit.get('ok')} cond_dim={dit.get('cond_dim')} · "
                  f"fiber ran={fib.get('ran')} ‖h‖={fib.get('h_norm_mean')} "
                  f"κ_tor={fib.get('kappa_tor_mean')} ‖Ω‖={fib.get('kappa_curv_mean')} cos={fib.get('cos_geo_mean')}")
        # 判据 (加**实质性阈值**: 相对提升 ≥1% 才算"更优"; 1e-9 级差异是数值噪声, 不许当提升)
        try:
            v0, v1 = (fa.get("V_last") or 0), (fb.get("V_last") or 0)
            d0, d1 = (fa.get("dist_min") or 0), (fb.get("dist_min") or 0)
            dv, dd = v0 - v1, d0 - d1
            relv = (dv / v0) if v0 > 1e-12 else 0.0
            reld = (dd / d0) if d0 > 1e-12 else 0.0
            MAT = 0.01                     # 实质性阈值 = 1%
            if relv >= MAT or reld >= MAT:
                better += 1
                print(f"  → ✅ 本 seed fiber=1 实质性更优 (ΔV={dv:+.3e} rel={relv:+.2%}, "
                      f"Δdist={dd:+.3e} rel={reld:+.2%})")
            elif relv <= -MAT or reld <= -MAT:
                worse += 1
                print(f"  → ❌ 本 seed fiber=1 实质性更差 (ΔV={dv:+.3e} rel={relv:+.2%}, "
                      f"Δdist={dd:+.3e} rel={reld:+.2%})")
            else:
                print(f"  → ➖ 本 seed 两臂**无实质差异** (ΔV={dv:+.3e} rel={relv:+.2%}, "
                      f"Δdist={dd:+.3e} rel={reld:+.2%} — 均 < 1% 阈值, 属数值噪声)")
            rows.append({"seed": s, "f0": fa, "f1": fb,
                         "dv": dv, "rel_v": relv, "dd": dd, "rel_d": reld})
        except Exception as e:                                                 # noqa: BLE001
            print(f"  → 判据异常 {type(e).__name__}: {e}")
            rows.append({"seed": s, "f0": fa, "f1": fb})
    print(f"\n小结: 更优 {better} / 更差 {worse} / 共 {len(seeds)} seed")
    ok = better > worse and better >= 2
    print("结论: " + ("✅ 有提升候选 → 可进入下一轮 (更多 seed + 视频证据)"
                     if ok else "➖ 无提升 (仅叠加/不回退) → 按门槛**不得进默认档**"))
    with open(os.path.join(ROOT, "reports", "ab_fiber_line_summary.json"), "w",
              encoding="utf-8") as f:
        json.dump({"steps": steps, "seeds": seeds, "better": better, "worse": worse,
                   "verdict": "improved" if ok else "no_gain", "rows": rows},
                  f, ensure_ascii=False, indent=1)
    return 0 if ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
