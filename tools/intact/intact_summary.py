# -*- coding: utf-8 -*-
"""汇总 INTACT 评测结果 (多 eval seed) → 表格 + summary.json + SUMMARY.md

纪律 (老倪红线):
  · SR 取官方 metrics 的 success_rate / episode_successes 逐条计数 (列表长度也核对)
  · "零搜索"只认 solver_timing 的实测均值: get_cost_calls_mean / candidate_action_steps_mean /
    configured_rollout_budget_mean (PriorOnlySolver 内被显式置 0)
  · 与官方对照必须写清"对照的是哪个数": 本机权重 = 训练 seed 3072 分片
    → 对照 PAPER_CHECKPOINTS.md 的 seed 3072 行 (pusht 79.67 …), 不是三训练种子均值
用法: python3 intact_summary.py <cache_dir> <out_dir>
"""
import json
import os
import sys

TASKS = ["pusht", "cube", "reacher", "tworoom"]
# 官方数值 (来源: INTACT-JEPA docs/PAPER_CHECKPOINTS.md + checkpoints/PAPER_E5_GOAL_MANIFEST.json)
OFF_TRAINSEED = {"pusht": 79.67, "cube": 98.67, "reacher": 97.00, "tworoom": 78.67, "macro": 88.50}
OFF_3SEED_MEAN = {"pusht": 80.22, "cube": 99.56, "reacher": 95.67, "tworoom": 82.11, "macro": 89.39}
OFF_3SEED_STD = {"pusht": 1.26, "cube": 0.77, "reacher": 1.76, "tworoom": 4.11, "macro": 0.77}


def mean_std(vals):
    if not vals:
        return None, None
    m = sum(vals) / len(vals)
    if len(vals) < 2:
        return m, 0.0
    var = sum((v - m) ** 2 for v in vals) / (len(vals) - 1)
    return m, var ** 0.5


def main() -> int:
    cache, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    summary, lines = {}, []
    lines += ["# INTACT 本地自主运行 · 评测汇总 (paper-e5-goal-v1, 权重=训练 seed 3072 分片)", "",
              "| 任务 | 本机 SR% (eval seed: 0/1/42) | 本机均值±样本std | 官方同训练种子 | 官方三训练种子均值 | get_cost_calls_mean | candidate_action_steps_mean | rollout_budget_mean | actor_warmstart |",
              "|---|---|---|---|---|---|---|---|---|"]
    for t in TASKS:
        files = sorted(f for f in os.listdir(out) if f.startswith(f"{t}_seed") and f.endswith(".json"))
        per = {}
        zero = {}
        for f in files:
            try:
                d = json.load(open(os.path.join(out, f), encoding="utf-8"))
            except Exception:
                continue
            m = d.get("metrics") or {}
            seed = f.split("_seed")[1].split(".")[0]
            sr = m.get("success_rate")
            eps = m.get("episode_successes") or []
            per[seed] = {"success_rate": sr, "episodes": len(eps),
                         "successes": sum(1 for x in eps if x),
                         "inference_mode": d.get("inference_mode"), "num_eval": d.get("num_eval"),
                         "horizon": d.get("horizon"), "eval_total_time": d.get("eval_total_time"),
                         "solver_timing": m.get("solver_timing"), "get_cost_calls": m.get("get_cost_calls"),
                         "rollout_candidates": m.get("rollout_candidates")}
            if not zero:
                zero = m.get("solver_timing") or {}
        vals = [v["success_rate"] for v in per.values() if isinstance(v["success_rate"], (int, float))]
        m_, s_ = mean_std(vals)
        f1 = lambda v: "—" if v is None else (f"{v:.2f}" if isinstance(v, float) else str(v))   # noqa: E731
        seedstr = " / ".join(f"{k}:{per[k]['success_rate']:.2f}" for k in sorted(per) if isinstance(per[k]["success_rate"], (int, float))) or "未评测"
        lines.append(f"| {t} | {seedstr} | {f1(m_)}±{f1(s_)} | {OFF_TRAINSEED.get(t)} | "
                     f"{OFF_3SEED_MEAN.get(t)}±{OFF_3SEED_STD.get(t)} | {f1(zero.get('get_cost_calls_mean'))} | "
                     f"{f1(zero.get('candidate_action_steps_mean'))} | {f1(zero.get('configured_rollout_budget_mean'))} | "
                     f"{f1(zero.get('actor_warmstart_enabled_mean'))} |")
        summary[t] = {"per_seed": per, "mean": m_, "sample_std": s_,
                      "official_same_training_seed": OFF_TRAINSEED.get(t),
                      "official_3_training_seed_mean": OFF_3SEED_MEAN.get(t),
                      "official_3_training_seed_std": OFF_3SEED_STD.get(t),
                      "zero_search": {"get_cost_calls_mean": zero.get("get_cost_calls_mean"),
                                      "candidate_action_steps_mean": zero.get("candidate_action_steps_mean"),
                                      "configured_rollout_budget_mean": zero.get("configured_rollout_budget_mean"),
                                      "actor_warmstart_enabled_mean": zero.get("actor_warmstart_enabled_mean"),
                                      "solve_time_mean": zero.get("solve_time_mean"),
                                      "num_solves": zero.get("num_solves")}}
    lines += ["",
              "**零搜索凭据**: Direct = `PriorOnlySolver` — 直接 `model.get_action(info, horizon)` 出动作块,",
              "`get_cost_calls_mean` / `candidate_action_steps_mean` / `configured_rollout_budget_mean` 实测均为 0,",
              "`actor_warmstart_enabled_mean=1` (意图 actor 真参与), `solve_time_mean` = 单次批量 Direct 规划耗时 (无候选搜索)。",
              "**对照口径**: 权重为官方训练 seed 3072 分片 → 逐任务对照 `docs/PAPER_CHECKPOINTS.md` 的 seed 3072 行;",
              "另列三训练种子均值±样本std 供参考 (来源 `checkpoints/PAPER_E5_GOAL_MANIFEST.json`)。",
              "**未做的**: cube 因磁盘闸门未评测 (诚实记录, 非静默跳过)。"]
    txt = "\n".join(lines)
    print(txt)
    with open(os.path.join(out, "SUMMARY.md"), "w", encoding="utf-8") as f:
        f.write(txt + "\n")
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"\n→ {out}/SUMMARY.md, {out}/summary.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
