# ACT baseline comparison — session notes (2026-08-02)

## Why MSE was garbage initially
`select_action()` returns NORMALIZED actions (mean/std normalized during training).
Comparing raw outputs against ground-truth raw actions gave MSE ~78000.
Fix: pass the output through the unnormalizer postprocessor → MSE ~12000 (real signal).

## Loading the postprocessor correctly
```python
from lerobot.policies.act.modeling_act import ACTPolicy          # NOT policy_act
from lerobot.policies import make_pre_post_processors            # NOT lerobot.processors

policy = ACTPolicy.from_pretrained(ckpt_path).cuda().eval()
_, postprocessor = make_pre_post_processors(
    policy_cfg=policy.config,
    pretrained_path=str(ckpt_path),
)
out = policy.select_action(batch)   # normalized
out = postprocessor(out)            # unnormalized → comparable to GT
```

## Data loading — two distinct shapes
- `data/metaworld_act` (baseline source): 2D state/action (25650 frames), parquet has NO image column.
  LeRobotDataset auto-generates `observation.image` (3×96×96, real values) — feed it whenever
  `policy.config.image_features` is a dict (it is, post-load, even when config.json shows None).
- `data/metaworld_mt50`: 4D state/action (204806 frames), parquet image col = dict `{"bytes": PNG}`.
  Do NOT mix the two datasets for comparison — state dims differ.

## Verified numbers (RTX 4060, metaworld_act, n_obs_steps=1, chunk=7)
| model | steps | action MSE | success (<0.05) | latency |
|---|---|---|---|---|
| baseline (act_metaworld) | 300 | 12037.8 ± 29797 | 0% | 3.9ms |
| candidate (act_mw_v111) | 2000 | 11155.0 ± 10309 | 0% | 1.3ms |
| improvement | | **+7.33%** | — | faster |

## Auto-iteration run (2026-08-02, real numbers)
- Round 1 (2000 steps): +7.33% ≥ 5% → passed threshold on first try.
- Round 2 (auto-adjusted: 3000 steps, lr 8e-5): +3.67% < 5% → **改进方案重训** triggered.
  Then rerun with the improved config → **+8.18% ≥ 5% → 达标 → 部署** (84MB pushed to ECS, peer auto-pulled within 5s).
- Iteration path: 300 → 2000 → 3000 steps → MSE 12037 → 11155 → 11053.

## Auto-iterate loop (tools/auto_iterate.py)
train (steps+1000/round, lr×0.8/round) → act_compare → mse_improve_pct
→ >=5%: deploy + bump version; else: adjust hyperparams and retrain (max rounds).

### Bug 1: regex clobbered nested config fields
`improve_config()` did `re.sub(r"steps: \d+", f"steps: {steps}", text)` — this ALSO matched
`  n_obs_steps: 1` and `  n_action_steps: 7` (both contain `steps: \d+`), setting them to 3000.
Training then failed: `n_action_steps 3000 > chunk_size 7`.
Fix: `re.sub(r"^steps: \d+", ..., flags=re.M)` and `^lr: ...` — line-anchored, top-level only.
After any config-rewriting helper, grep the config to confirm nested fields survived.

### Bug 2: compare JSON path hardcoded
act_compare.py wrote `Path("docs/CICD_COMPARE_v1.1.0.json")` regardless of `--report`;
auto_iterate read `docs/CICD_COMPARE_auto.json` → "对比失败" with no visible error.
Fix: `json_path = Path(args.report).with_suffix(".json")` — HTML and JSON stay coupled.

## GUI integration (studio.py EvalModule)
- `_run_compare()` reads newest `docs/CICD_COMPARE_*.json`, shows verdict
  "✅ 提升 X% / ❌ 未提升 (需改进重训)" in a label + log line.
- Trigger: "🔬 基线对比" button in the evaluation module button row.
