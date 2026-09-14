# 四任务官方评测 · 补充运行手册 (2026-09-13 全量实跑)

> 本文件是 `references/paper-runtime-eval-runbook.md` 的**续篇/增量**：那里是 pusht 单任务的现场转录，
> 这里是**四任务映射表 + 09-13 全量结果 + 产物归档约定 + reacher 残片案**。

## 1. 四任务映射表 (换任务只换这几个参数)
```
任务      --config-name   policy (checkpoints 目录名)               dataset_name(算 stats)       env_name                    结果文件 (落 $CACHE/)
pusht     pusht           recovery_delta_full_pusht_s3072           pusht_expert_train          swm/PushT-v1               pusht_results.txt
cube      cube            recovery_delta_full_cube_s3072            ogbench/cube_single_expert  swm/OGBCube-v0             ogb_cube_results.txt
reacher   reacher         recovery_delta_full_reacher_s3072         dmc/reacher_random          swm/ReacherDMControl-v0    dmc_results.txt
tworoom   tworoom         recovery_delta_full_tworoom_s3072         tworoom                     swm/TwoRoom-v1             tworoom_results.txt
```
命令模板 (与 `intact_autopilot.sh` 同口径)：
```bash
cd $ROOT/paper_runtime && python eval.py --config-name=<task> solver=prior_only \
  policy=recovery_delta_full_<task>_s3072 seed=<0|1|42> eval.num_eval=100 output.filename=<结果文件>
```
数据集布局别名 (缺了必然 FileNotFoundError)：
- `datasets/ogbench/cube_single_expert.h5 → ../cube_single_expert.h5` (101.9G)
- `datasets/dmc/reacher_random.h5 → ../reacher.h5` (98.9G，**必须解析到 `datasets/reacher.h5`**，
  不要把 h5 复制进 `datasets/reacher/` 子目录 —— 上次就是那样多出一份半截副本)

## 2. 09-13 全量实跑结果 (eval seed 0/1/42，各 100 局)
```
任务     本机 (0/1/42)      均值±std      官方 seed3072 列   官方三训练种子均值
pusht    76 / 85 / 77       79.33±4.93    79.67             80.22±1.26
cube     100 / 97 / 99      98.67±1.53    98.67             99.56±0.77   ← 首次跑通, 与官方完全相同
reacher  95 / 99 / 97       97.00±2.00    97.00             95.67±1.76   ← 该行数字是 09-12 的 (见 §4)
tworoom  81 / 74 / 81       78.67±4.04    78.67             82.11±4.11
```
总表 `~/l4_ab/intact_results/SUMMARY.md`；一键全量 `scripts/run_four_task_suite.sh`。

## 3. 产物归档约定 (三个"同名复用"陷阱)
1. **结果 sidecar json 同名复用** (`$CACHE/<结果文件>.json`) → 每跑完一个 seed 立刻
   `cp $CACHE/<结果文件>.json $OUT/<task>_seed<S>.json`，否则下一个 seed 覆盖它。
2. **复跑/复验的 json 必须放子目录** (`$OUT/recheck_<date>/`)，否则 `intact_summary.py` 会把同一 seed
   读成重复列，总表长这样：`0:76.00 / 0_recheck_0913:76.00 / 1:85.00 / …`（脏表）。
3. **每局视频同名复用** (`$CACHE/env_<i>.mp4`) → 每个 (task, seed) 跑完立刻拷到
   `$OUT/videos/<task>_seed<S>/`；seed42 再拼「前 6 局连播」showcase：
   `ffmpeg -f concat -safe 0 -i list.txt -c copy <task>_seed42_showcase.mp4`（list.txt 每行 `file '<abs>'`）。

## 4. reacher 那一行为什么是旧数字 (数据残片案, 09-13)
四任务全量复跑时 pusht/cube/tworoom 全部 rc=0，**reacher 三个 seed 全失败**：
```
OSError: Can't synchronously read data (filter returned failure during read)
```
真因不是 filter/插件：`datasets/dmc/reacher_random.h5` 与 `datasets/reacher/reacher.h5` 当时都已变成
2,030,042,624 B 的**截断残片**（HDF5 superblock `stored_eof = 98905882624`），是 09-12 21:57/22:03
一次中断解压覆盖的结果；而当时的判断「那个 23.7G 的 reacher.tar.zst 没被用到」把它删了 → 唯一完整来源没了。
⇒ 恢复：重下 `quentinll/lewm-reacher/reacher.tar.zst`（23,750,614,946 B，
sha256 `4ff2385e49712caa89f21b8e0a246e2614b621d3f22cf2d1224d845e879a1cc2`）→ 解出 `reacher.h5`
(98,905,882,624 B) → 落到 `datasets/reacher.h5` + 建软链 → 复跑 3 seed。
⇒ 通用规则见 `dataset-archive-provisioning` 的 `references/truncated-product-traps.md`：
**删归档前必须打开替代物验完整性**；名字像"小数据集"、大小看着合理，都不算证据。

## 5. 权重结构 (被问"为什么四个权重 / 没有泛化性么")
- 官方包 = 6 cell × 3 训练种子 × 4 任务分片 = 72 个 ckpt；本机只有 goal_intact cell × seed3072 的 4 片。
- 逐 key 比对：`encoder.*` 198 个张量四份完全相同（共享编码器）；不同的 109 个是
  `action_encoder.*` 6 + `predictor.*` 81 + `inverse_actor.*` 14 + `projector.*` 9 + `pred_proj.*` 9。
- 分片是物理必需：`inverse_actor.action_dim` = 10 (pusht/reacher/tworoom = 5 步块×2 维) vs 25 (cube = 5×5)。
- 明细 + 官方数字 + 比对脚本：`references/task-weights-and-official-numbers.md` · `scripts/diff_ckpt_prefixes.py`。
