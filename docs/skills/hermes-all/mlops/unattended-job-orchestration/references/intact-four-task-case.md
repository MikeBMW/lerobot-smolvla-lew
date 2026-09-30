# 实例: INTACT-JEPA 官方三/四任务评测 (2026-09-12)

场景: 论文复现流水线 —— 每任务 [下载 HF 归档 → size+sha256 双核 → 解压 → 3 个 eval seed 官方 Direct 评测] → 汇总表。
tworoom 3.1GB / cube 46GB, 单机 4060 笔记本, 出口带宽 ~1.6MiB/s, 磁盘红线 200G。
下载耗小时级, 评测还要 GPU —— 全程不能占着会话等。

## 目录约定

```
/home/ubuntu/l4_ab/intact_autopilot.sh        执行体 (任务表/资产表/评测/汇总, 幂等+续传)
/home/ubuntu/l4_ab/chain_cube_after_tworoom.sh 接力脚本 (上游结束→起下游)
/home/ubuntu/.hermes/scripts/cube_final_watch.sh 哨兵 (cron no_agent, every 20m)
/home/ubuntu/l4_ab/intact_results/           结果: <task>_seed<N>.json + SUMMARY.md + summary.json
/home/ubuntu/l4_ab/intact_results/autopilot.log 全量日志 (tee 追加)
```

流水线内部关键点 (踩坑后固化):
- 结果文件名**逐任务不同** (`pusht_results.txt` / `ogb_cube_results.txt` / `dmc_results.txt` / `tworoom_results.txt`),
  猜名字会误报"未产出结果" → 用 `result_file()` 映射表。
- "结果已齐" 只能跳过**评测**, 数据该补还得补 (曾因整段 `continue` 导致数据没下)。
- 解压后目标路径与评测期望不一致 → 建**符号链接**别名 (`dmc/reacher_random.h5 -> ../reacher.h5`), 不复制 GB 级文件。
- 解压成功即删归档; 结果齐后**显式** `RECLAIM=1` 才回收数据集 (默认保留给 VSCode 手动调试)。
- 磁盘闸门: `NEED_GB = 资产×2.6 + 15`, 低于 `free_min`(80G) 就跳过并诚实记录, 不硬跑。

## 接力脚本 (原文)

```bash
#!/usr/bin/env bash
# 自动接力: 等 tworoom 流水线(下载+解压)结束 → 立刻恢复 cube 的下载与 3-seed 评测
# 为什么要接力: 两个 46GB/3GB 任务抢同一出口带宽会互相拖慢; 先让小的(tworoom)完成
set -uo pipefail
LOG=/home/ubuntu/l4_ab/intact_results/autopilot.log
say() { echo "[$(date '+%F %T')] [接力] $*" | tee -a "$LOG"; }

say "等待 tworoom 流水线结束 (含解压)..."
while pgrep -f "tasks .tworoom" >/dev/null 2>&1; do sleep 60; done
sleep 20
say "tworoom 流水线已结束; 开始恢复 cube (断点续传 58% 起)"
bash /home/ubuntu/l4_ab/intact_autopilot.sh --tasks "cube" --seeds "0 1 42" --num 100 >> "$LOG" 2>&1
say "cube 流水线结束"
```

## 哨兵脚本 (原文) — 有内容才发, 否则静默

```bash
#!/usr/bin/env bash
set -uo pipefail
OUT=/home/ubuntu/l4_ab/intact_results
CACHE=/home/ubuntu/stable-wm-cache
LOG=$OUT/autopilot.log
OK_FLAG=$OUT/.four_tasks_reported
FAIL_FLAG=$OUT/.cube_failed_reported
TASKS="pusht cube reacher tworoom"; SEEDS="0 1 42"

[ -f "$OK_FLAG" ] && exit 0

alive=0; pgrep -f 'intact_autopilot|chain_cube_after_tworoom' >/dev/null 2>&1 && alive=1
missing=""
for t in $TASKS; do for s in $SEEDS; do
  [ -f "$OUT/${t}_seed${s}.json" ] || missing="$missing ${t}_seed${s}"
done; done

if [ -z "$missing" ]; then
  python3 /home/ubuntu/l4_ab/intact_summary.py "$CACHE" "$OUT" >/dev/null 2>&1
  echo "✅ INTACT 四任务官方评测全部完成 (paper_runtime 指纹校验通过 · 零搜索 Direct)"
  echo
  sed -n '/^# INTACT/,$p' "$OUT/SUMMARY.md"
  touch "$OK_FLAG"; exit 0
fi

if [ "$alive" = "0" ] && [ ! -f "$FAIL_FLAG" ]; then
  echo "⚠️ INTACT 流水线已结束, 但以下结果缺失:$missing"
  echo "—— autopilot.log 最后 12 行 ——"; tail -12 "$LOG"
  touch "$FAIL_FLAG"
fi
exit 0
```

挂载: `cronjob(action='create', no_agent=true, schedule='every 20m', script='cube_final_watch.sh',
deliver='feishu:oc_c0b4048546145c5c581ddd1a9e8f565d')` —— CLI 会话收不到 cron 输出, 必须点名平台。
挂之前手动干跑一次: 此时 cube 未完成 → **应零输出 rc=0** (实测确认过)。

## 汇总表格式 (intact_summary.py 产出, SUMMARY.md)

```
| 任务 | 本机 SR% (eval seed: 0/1/42) | 本机均值±样本std | 官方同训练种子 | 官方三训练种子均值 | get_cost_calls_mean | candidate_action_steps_mean | rollout_budget_mean | actor_warmstart |
| pusht   | 0:76.00 / 1:85.00 / 42:77.00 | 79.33±4.93 | 79.67 | 80.22±1.26 | 0.00 | 0.00 | 0.00 | 1.00 |
| cube    | 未评测 | —±— | 98.67 | 99.56±0.77 | — | — | — | — |
| reacher | 0:95.00 / 1:99.00 / 42:97.00 | 97.00±2.00 | 97.0  | 95.67±1.76 | 0.00 | 0.00 | 0.00 | 1.00 |
| tworoom | 0:81.00 / 1:74.00 / 42:81.00 | 78.67±4.04 | 78.67 | 82.11±4.11 | 0.00 | 0.00 | 0.00 | 1.00 |
```

- SR 取 `metrics.success_rate` (json 里 SR 嵌套在 `metrics` 下, 不在顶层 —— 顶层只有 num_eval/solver 等元数据)。
- **零搜索凭据** 一同列出: `get_cost_calls / candidate_action_steps / configured_rollout_budget` 全 0
  + `actor_warmstart_enabled_mean=1` + `solve_time_mean` = 单次批量 Direct 耗时。
- 未做的行**如实写** "未评测" 并在脚注说明原因 ("cube 因磁盘闸门未评测 (诚实记录, 非静默跳过)") ——
  本用户红线: 缺口不许含糊。
- 对照口径: 权重是官方训练 seed 3072 分片 → 逐任务对 `docs/PAPER_CHECKPOINTS.md` 的 seed 3072 行;
  另列三训练种子均值±样本std 作参考 (来源 `checkpoints/PAPER_E5_GOAL_MANIFEST.json`)。

## tworoom.h5 验证留档

`stable-wm-cache/datasets/tworoom.h5` 12.78GB, 920,809 帧 / 10,000 集, 16 个 dataset。
真解码抽检 idx 0 / 306936 / 920808: pixels 224×224×3 `mean/std=225.6/80.6` (真图),
action/proprio 有限值 (仅末帧 action=nan, 正常); `ep_offset` 步进 == `ep_len`, 末集 `offset[-1]+len[-1]==920809` ✓。
`pixels` 用 blosc 滤镜 → 读之前必须 `import hdf5plugin` (细节见 `hf-dataset-subset` 的
`references/hdf5-blosc-verification.md` 与 `scripts/verify_h5_dataset.py`)。

评测日志复核真实量 (防止空壳结果): `670809 valid starting points found for evaluation.` +
`{'success_rate': 81.0, ... 'get_cost_calls': 0.0}` + `eval_total_time ≈ 24.8s/100 episodes`。
eval.py 不显式把模型搬 CUDA (只用 `CUDA_VISIBLE_DEVICES` 给 `MUJOCO_EGL_DEVICE_ID` 选渲染卡,
模型 device = 参数所在 device) → 与同机训练**不抢显存**, 但要在真起跑时 `nvidia-smi` 复核一次。
