# -*- coding: utf-8 -*-
"""📈 L4 性能提升 — 引擎参数数据驱动寻优 (同口径多重复, 先基线后对照)

目标 (老倪 2026-09-12 明确): L4 交付门槛从"不回退"提到"**有提升**"。
本工具管的是**不依赖模型**的那条提升路径: 六层引擎的融合/限速/否决/对位参数全是
`ActionModulator(...)` 的构造参数 → 可以直接扫参, 不改源码、可回退。

KPI (同一口径, 逐条落盘):
  · success  = tr['done'][-1] (插入完成)
  · steps    = 完成步数 (效率)
  · insert_mm= tr['dist'][-1] (插入/推进质量)
  · timeout  = steps 打满 max_steps (卡死)

用法:
  # 基线 (不改任何参数, 多 seed 多重复)
  gui-venv311/bin/python tools/l4_tune.py --mode baseline --seeds 0,1,2,3 --reps 2
  # 单参数扫描 (坐标下降): 一次一个维度
  gui-venv311/bin/python tools/l4_tune.py --mode sweep --dim k_fb --values 0.6,1.0,1.5 --seeds 0,1,2
  # 组合确认 (把胜出参数与基线同口径对比)
  gui-venv311/bin/python tools/l4_tune.py --mode confirm --set k_fb=1.5,v_cap_scale=1.25 \
      --seeds 0,1,2 --reps 3
说明: 扫参用 --set 组合; 只有在 **同 seed 多重复** 下成功率↑ (或持平且步数↓≥5%) 才算"有提升"。
"""
import argparse
import json
import os
import statistics as st
import sys
import time

import numpy as np

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
os.environ.setdefault("MUJOCO_GL", os.environ.get("MUJOCO_GL", "egl"))
_CACHE = os.environ.get("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache")
if os.path.isdir(_CACHE):
    os.environ.setdefault("STABLEWM_HOME", _CACHE)
    os.environ.setdefault("LOCAL_DATASET_DIR", _CACHE)

# 可扫维度 (全部是 ActionModulator 构造参数, 不碰源码字面量)
DIMS = ["k_fb", "veto_th", "contact_th", "v_cap_scale", "align_xy_fine", "w_contact"]


def parse_set(s: str) -> dict:
    out = {}
    for kv in [x for x in s.split(",") if x.strip()]:
        k, v = kv.split("=")
        out[k.strip()] = float(v)
    return out


def _apply_params(sim, params: dict) -> dict:
    """把候选参数写到**已创建**的调度器实例上 (全部是 ActionModulator 的实例属性)。

    为什么要包一层: 引擎的 `self.sched` 是在 `_reset()` 里建的 (不是 __init__) →
    构造后直接取 sim.sched 会 AttributeError (实测踩坑)。所以用包 _reset 的钩子在它建好之后写参。
    未知参数名直接抛错 (不许静默忽略 —— 否则"扫了个不存在的参数"会得出假结论)。
    """
    s = sim.sched
    p = dict(params)
    applied = {}
    scale = p.pop("v_cap_scale", None)
    if scale is not None:
        s.v_cap = {k: float(v) * float(scale) for k, v in s.v_cap.items()}
        applied["v_cap_scale"] = float(scale)
    smin = p.pop("v_min_scale", None)
    if smin is not None:
        s.v_min = {k: float(v) * float(smin) for k, v in s.v_min.items()}
        applied["v_min_scale"] = float(smin)
    for k, v in p.items():
        if not hasattr(s, k):
            raise AttributeError(f"未知调度器参数 {k!r} (拒绝静默忽略)")
        setattr(s, k, float(v))
        applied[k] = float(v)
    return applied


def apply_mod_consts(spec: str) -> dict:
    """改**模块级常量** (如 INSERT_STALL_FRAMES / GRIP_CLOSE) → 直接 patch 引擎模块属性。

    为什么需要: 这些常量不在调度器实例上 (构造参数扫不到), 但引擎在方法里按模块名查找 →
    patch 模块属性即生效, 进程内有效、不改源码文件。**不存在的名字直接抛错** (不许静默忽略)。
    """
    if not spec:
        return {}
    import state_space_sim_real as S                          # noqa: PLC0415
    applied = {}
    for kv in [x for x in spec.split(",") if x.strip()]:
        k, v = kv.split("=")
        k = k.strip()
        if not hasattr(S, k):
            raise AttributeError(f"引擎模块无此常量: {k!r} (拒绝静默忽略)")
        fv = float(v)
        setattr(S, k, fv)
        applied[k] = fv
    return applied


def run_one(seed, params, max_steps):
    from state_space_sim_real import RealStateSpaceSim     # noqa: PLC0415
    sim = RealStateSpaceSim(seed=seed, vision=False, mode="insert", log=lambda *a: None)
    if params:
        _orig_reset = sim._reset

        def _patched_reset(seed_, *a, **kw):
            r = _orig_reset(seed_, *a, **kw)
            _apply_params(sim, dict(params))       # 调度器刚建好 → 此刻写参
            return r

        sim._reset = _patched_reset
    tr = sim.run(max_steps=max_steps)
    done = bool(tr["done"][-1]) if tr.get("done") else False
    return {"seed": seed, "done": done, "steps": len(tr["t"]),
            "insert_mm": (round(float(tr["dist"][-1]) * 1000, 1) if tr.get("dist") else None),
            "timeout": bool(len(tr["t"]) >= max_steps)}


def evaluate(label, params, seeds, reps, max_steps):
    rows = []
    for seed in seeds:
        for r in range(reps):
            row = run_one(seed, dict(params), max_steps)   # 传副本 (run_one 会 pop)
            row["rep"] = r
            rows.append(row)
            print(f"    [{label}] seed={seed} rep={r} done={row['done']} steps={row['steps']} "
                  f"insert={row['insert_mm']}mm", flush=True)
    succ = sum(1 for r in rows if r["done"])
    stp = [r["steps"] for r in rows]
    ins = [r["insert_mm"] for r in rows if r["insert_mm"] is not None]
    return {"label": label, "params": params, "n": len(rows), "success": succ,
            "success_rate": round(succ / max(1, len(rows)), 3),
            "steps_mean": round(st.mean(stp), 1) if stp else None,
            "steps_std": round(st.pstdev(stp), 1) if len(stp) > 1 else 0.0,
            "insert_mm_mean": round(st.mean(ins), 1) if ins else None,
            "timeouts": sum(1 for r in rows if r["timeout"]), "rows": rows}


def verdict(base, cand):
    """提升判据: 成功率↑ 或 (成功率持平 且 步数↓≥5%) 或 (成功率持平 且 插入更深)。"""
    ds = cand["success_rate"] - base["success_rate"]
    if ds > 0:
        return f"✅ 提升 (成功率 {base['success_rate']:.2f}→{cand['success_rate']:.2f})"
    if ds == 0 and base["steps_mean"] and cand["steps_mean"]:
        d = (base["steps_mean"] - cand["steps_mean"]) / base["steps_mean"]
        if d >= 0.05:
            return f"✅ 提升 (成功率持平, 步数 −{d*100:.1f}%)"
        if d <= -0.05:
            return f"❌ 回退 (步数 +{-d*100:.1f}%)"
    if ds < 0:
        return f"❌ 回退 (成功率 {base['success_rate']:.2f}→{cand['success_rate']:.2f})"
    return "≈ 无差异"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True,
                    choices=["baseline", "sweep", "confirm", "paired", "noise"])
    ap.add_argument("--dim", default="k_fb", help=f"sweep 维度, 可选 {DIMS}")
    ap.add_argument("--values", default="0.6,1.0,1.5")
    ap.add_argument("--set", default="", help="confirm/paired 用: k=v,k=v (调度器实例属性)")
    ap.add_argument("--mod-set", default="", help="引擎模块级常量: K=V,K=V (如 INSERT_STALL_FRAMES=8)")
    ap.add_argument("--seeds", default="0,1,2")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--max-steps", type=int, default=600)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    seeds = [int(s) for s in a.seeds.split(",") if s.strip()]
    rep_dir = os.path.join(ROOT, "reports")
    rec = {"ts": time.strftime("%F %T"), "mode": a.mode, "seeds": seeds, "reps": a.reps,
           "max_steps": a.max_steps, "runs": []}

    if a.mode == "baseline":
        print("═══ L4 基线 (现状参数, 同 seed 多重复) ═══")
        rec["baseline"] = evaluate("baseline", {}, seeds, a.reps, a.max_steps)
        print(f"  → 成功率 {rec['baseline']['success_rate']:.2f} · "
              f"步数 {rec['baseline']['steps_mean']}±{rec['baseline']['steps_std']} · "
              f"超时 {rec['baseline']['timeouts']}")
    elif a.mode in ("paired", "noise"):
        # ★ 配对设计 (评估铁律): 同 seed 内 base↔候选**背靠背交替**, 逐 seed 判胜负 —
        #   实测发现同 seed 同参数多次跑仍有波动 (base 步数 381→416, 甚至"默认参数"
        #   也会被判成提升/回退) → 单臂平均不可靠, 必须配对 + 留噪声对照。
        params = parse_set(a.set) if a.mode == "paired" else {"k_fb": 1.0}   # 默认值 = 空对照
        tag = "候选" if a.mode == "paired" else "空对照(默认值 k_fb=1.0 → 应当无差异)"
        print(f"═══ 配对确认 [{tag}]: {params} · mod={a.mod_set or '-'} · seeds={seeds} reps={a.reps} ═══")
        import state_space_sim_real as S                       # noqa: PLC0415
        _mods = {}
        if a.mode == "paired" and a.mod_set:
            for kv in [x for x in a.mod_set.split(",") if x.strip()]:
                k, v = kv.split("=")
                k = k.strip()
                if not hasattr(S, k):
                    raise AttributeError(f"引擎模块无此常量: {k!r}")
                _mods[k] = float(v)
        _orig_mods = {k: getattr(S, k) for k in _mods}
        pairs = []
        for seed in seeds:
            for r in range(a.reps):
                for k, v in _orig_mods.items():        # base 臂 = 原值
                    setattr(S, k, v)
                b = run_one(seed, {}, a.max_steps)
                for k, v in _mods.items():             # 候选臂 = 候选常量
                    setattr(S, k, v)
                c = run_one(seed, dict(params), a.max_steps)
                pairs.append({"seed": seed, "rep": r, "base": b, "cand": c})
                print(f"    seed={seed} rep={r} base(done={b['done']},{b['steps']}步) "
                      f"vs cand(done={c['done']},{c['steps']}步)", flush=True)
        w = sum(1 for p in pairs if p["cand"]["done"] and not p["base"]["done"])
        l = sum(1 for p in pairs if p["base"]["done"] and not p["cand"]["done"])
        n = len(pairs)
        br = sum(1 for p in pairs if p["base"]["done"]) / max(1, n)
        cr = sum(1 for p in pairs if p["cand"]["done"]) / max(1, n)
        print(f"  配对胜负: 候选胜 {w} · 基线胜 {l} · 同分 {n - w - l} (n={n})")
        print(f"  成功率: 基线 {br:.3f} → 候选 {cr:.3f}")
        concl = ("✅ 有提升 (配对净胜 ≥2 且非噪声水平)" if w - l >= 2 else
                 ("❌ 回退" if l - w >= 2 else "≈ 无差异 (在噪声内, 不能声称提升)"))
        print(f"  裁决: {concl}")
        rec["pair_sets"] = {"params": params, "wins": w, "losses": l, "n": n,
                            "base_rate": br, "cand_rate": cr, "conclusion": concl,
                            "pairs": pairs}
    elif a.mode == "sweep":
        print(f"═══ 单参数扫描: {a.dim} ∈ {a.values} ═══")
        base = evaluate(f"base({a.dim})", {}, seeds, a.reps, a.max_steps)
        rec["baseline"] = base
        for v in [float(x) for x in a.values.split(",") if x.strip()]:
            r = evaluate(f"{a.dim}={v}", {a.dim: v}, seeds, a.reps, a.max_steps)
            r["verdict_vs_base"] = verdict(base, r)
            rec["runs"].append(r)
            print(f"  → {a.dim}={v}: 成功率 {r['success_rate']:.2f} · 步数 {r['steps_mean']} · "
                  f"{r['verdict_vs_base']}")
    else:
        params = parse_set(a.set)
        print(f"═══ 组合确认: {params} ═══")
        base = evaluate("baseline", {}, seeds, a.reps, a.max_steps)
        cand = evaluate("candidate", params, seeds, a.reps, a.max_steps)
        rec["baseline"], rec["candidate"] = base, cand
        rec["verdict"] = verdict(base, cand)
        print(f"  基线 : 成功率 {base['success_rate']:.2f} · 步数 {base['steps_mean']} · 超时 {base['timeouts']}")
        print(f"  候选 : 成功率 {cand['success_rate']:.2f} · 步数 {cand['steps_mean']} · 超时 {cand['timeouts']}")
        print(f"  裁决 : {rec['verdict']}")

    out = a.out or os.path.join(rep_dir, f"l4_tune_{a.mode}_{time.strftime('%Y%m%d_%H%M%S')}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)
    print(f"  → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
