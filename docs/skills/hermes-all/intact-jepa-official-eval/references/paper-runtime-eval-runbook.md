# paper_runtime 官方评测 · 实测转录 (2026-09-13, 本机 4060 会话)

## 1. 现场症状与根因
用户贴的错误:
```
FileNotFoundError: [Errno 2] Unable to synchronously open file (unable to open file:
name = '/home/ubuntu/stable-wm-cache/datasets/pusht_expert_train.h5', errno = 2, ...)
```
根因**不是代码**: 归档只下到压缩包、从没解压。
```
/home/ubuntu/dl_intact/pusht_expert_train.h5.zst   13136247974 B   09-13 03:51 下完 (zstd -t 通过)
$STABLEWM_HOME/datasets/ 里当时没有 pusht_expert_train.h5
```
为什么没人解压: 解压属于 intact_autopilot 流水线, 而 `/home/ubuntu/l4_ab/intact_results/autopilot.log`
显示整条流水线 09-12 15:30 就「流水线结束」了; .zst 是 09-13 03:51 才下完 → **接力断档** (+ 机器 07:42 关机重启)。
修复与验证走 `dataset-archive-provisioning` 技能 (解压 → 字节门 → h5py 三判据 → 真跑复现)。

## 2. 修复后的真跑转录 (rc=0)
```
=== 0) 指纹 ===  eval.py OK / jepa.py OK / module.py OK / prior_only_solver.py OK / sitecustomize.py OK
=== 1) 数据集就位 ===  pusht_expert_train.h5 46300921856 B
                      checkpoints/recovery_delta_full_pusht_s3072/weights_epoch_5.pt 84734848 B
=== 2) 评测 ===  1869611 valid starting points found for evaluation.
  {'success_rate': 77.0, 'episode_successes': array([...]), 'solver_timing': {
     'actor_warmstart_enabled_mean': 1.0, 'candidate_action_steps_mean': 0.0,
     'get_cost_calls_mean': 0.0, 'configured_rollout_budget_mean': 0.0,
     'solve_time_mean': 0.2723, 'num_solves': 2},
   'eval_total_time': 23.93, 'cem_time_per_episode': 0.00545}
```
- seed 42 / 100 局 → 77.0, **与 09-12 那份记录逐位一致** = 同一份数据、可复现。
- 100 局只要 ~24 秒 (Direct 无搜索), 整跑含建环境 ~50 秒 → 复跑验证成本极低, 没有理由不做。

## 3. 用户自己那次 VSCode debugpy 跑 (20 局)
命令: `eval.py --config-name=pusht solver=prior_only policy=recovery_delta_full_pusht_s3072
seed=42 eval.num_eval=20 output.filename=debug_pusht.txt`
```
JAX version 0.6.2 available.
[atomic_save] installed crash-safe checkpoint plugin ...            ← 与评测无关
Cached 'action' / 'proprio' / 'state' from '.../pusht_expert_train.h5'   ← 数据集真的读到了
Loading checkpoint from folder .../recovery_delta_full_pusht_s3072
Created ViT-tiny from scratch with config: {'hidden_size': 192, 'num_hidden_layers': 12,
    'num_attention_heads': 3, 'intermediate_size': 768, 'image_size': 224, 'patch_size': 14}
1869611 valid starting points found for evaluation.
[ 201658 209212 221573 305422 472617 ... 2275375 ]                   ← 20 个起点索引
UserWarning: Casting input x to numpy array. / Backend tkagg is interactive backend. /
    lance is not fork-safe.                                          ← 三条无害
{'success_rate': 90.0, ...}   ← 18/20
```
产物: `$STABLEWM_HOME/debug_pusht.txt` (1787 B)。

## 4. 口径 (为什么 90% 不能当提升)
| 跑法 | 结果 | Wilson 95% CI |
|---|---|---|
| 20 局 (调试档) | 18/20 = 90.0% | 69.9% ~ 97.2% |
| 100 局 (官方口径) | 77/100 = 77.0% | 67.8% ~ 84.2% |

区间大幅重叠 → 90% 与 77% 不矛盾, 是抽样噪声。官方 = 100 局 × seed 0/1/42。
历史表 (可复现): pusht 76/85/77 → 79.33±4.93 (官方 79.67) · reacher 95/99/97 → 97.00±2.00 (官方 97.0) ·
tworoom 81/74/81 → 78.67±4.04 (官方 78.67) · cube 未评 (官方 98.67)。

## 5. 视频证据 (world.py `_evaluate_from_dataset` → `plot/video_utils.save_panel_videos`)
```python
save_panel_videos(Path(video), {'agent': frames, 'dataset': dataset_videos, 'goal': goal_state['goal']})
```
- 落在 `$STABLEWM_HOME` 根 (results_path 来自 hydra 输出目录 + cache 配置): `env_0.mp4 … env_<N-1>.mp4`, 每局一个。
- 面板布局 (代码反推 + ffprobe 实测吻合): 3 × 224×224 并排 + 文字标签行 → 736×288 · 50 帧 · 15 fps · 3.333 s。
- **同名覆盖实锤**: 08:17 那次 100 局写了 env_0..env_99; 08:19 用户那次 20 局把 env_0..env_19 覆盖掉 →
  盘上 100 个文件里 80 个 mtime 08:17、20 个 08:19。跨运行/跨局数互相污染, 必须跑完即归档。
- 黑帧自检 (本机实测值, 抽第 25 帧): env_0 std=18.8 · env_3 std=20.7 · env_6 std=20.7 · env_50 std=19.2 → 真图。
- 归档落点: `/home/ubuntu/l4_ab/intact_results/pusht_debug_0913_videos/`
  (18 个 `env??_success.mp4` + `env03_FAIL.mp4` + `env06_FAIL.mp4` + README.txt, 0.3 MB)。
  失败局靠 `episode_successes` 顺序定位: `[T,T,T,F,T,T,F,...]` → 第 3、6 局失败。

## 6. 附带发现
- `preflight_check.py` 需要位置参数 mode (`eval-official|eval-clear|train-single|train-multitask`),
  且 `--policy` 不传会出 `[FAIL] checkpoint: evaluation requires --policy` (假失败)。
- `[FAIL] code integrity: modified:module.py,train.py` 是**我们自己的 INTACT 微调改动**, 恒现, 不是回归;
  但不带 `--strict-git-clean` 时它只打印, 不阻塞评测。
- 只用 h5py 打开而不导入 hdf5plugin: 读 keys/形状 OK, 一旦读 `pixels` 数据就
  `OSError: Can't synchronously read data (can't open directory (/usr/local/lib/plugin))`。
