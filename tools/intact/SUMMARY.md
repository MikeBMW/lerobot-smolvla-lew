# INTACT 本地自主运行 · 评测汇总 (paper-e5-goal-v1, 权重=训练 seed 3072 分片)

| 任务 | 本机 SR% (eval seed: 0/1/42) | 本机均值±样本std | 官方同训练种子 | 官方三训练种子均值 | get_cost_calls_mean | candidate_action_steps_mean | rollout_budget_mean | actor_warmstart |
|---|---|---|---|---|---|---|---|---|
| pusht | 0:76.00 / 1:85.00 / 42:77.00 | 79.33±4.93 | 79.67 | 80.22±1.26 | 0.00 | 0.00 | 0.00 | 1.00 |
| cube | 未评测 | —±— | 98.67 | 99.56±0.77 | — | — | — | — |
| reacher | 0:95.00 / 1:99.00 / 42:97.00 | 97.00±2.00 | 97.0 | 95.67±1.76 | 0.00 | 0.00 | 0.00 | 1.00 |
| tworoom | 0:81.00 / 1:74.00 / 42:81.00 | 78.67±4.04 | 78.67 | 82.11±4.11 | 0.00 | 0.00 | 0.00 | 1.00 |

**零搜索凭据**: Direct = `PriorOnlySolver` — 直接 `model.get_action(info, horizon)` 出动作块,
`get_cost_calls_mean` / `candidate_action_steps_mean` / `configured_rollout_budget_mean` 实测均为 0,
`actor_warmstart_enabled_mean=1` (意图 actor 真参与), `solve_time_mean` = 单次批量 Direct 规划耗时 (无候选搜索)。
**对照口径**: 权重为官方训练 seed 3072 分片 → 逐任务对照 `docs/PAPER_CHECKPOINTS.md` 的 seed 3072 行;
另列三训练种子均值±样本std 供参考 (来源 `checkpoints/PAPER_E5_GOAL_MANIFEST.json`)。
**未做的**: cube 因磁盘闸门未评测 (诚实记录, 非静默跳过)。
