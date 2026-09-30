---
name: intact-lewm-official-eval
description: Use when 复现/跑 INTACT(LeWM) 四任务官方评测或数据集报错。
---

# INTACT (LeWM) 官方评测 · 复现与排障

## 何时用
- 要跑 INTACT 论文权重的官方 Direct(零搜索) 评测: pusht / cube / reacher / tworoom
- 报 `InstantiationException: Error locating target 'module.…'`、`FileNotFoundError … .h5`、
  h5py `can't open directory (/usr/local/lib/plugin)`、`filter returned failure during read`、`truncated file`
- 要下载/解压/校验这四个基准数据集, 或想「不等大下载先看某任务的例子」

## 环境事实
```
仓库      /home/ubuntu/INTACT-JEPA            (自带 .venv, python3.10)
论文运行时 /home/ubuntu/INTACT-JEPA/paper_runtime   ← 评测必须走这里
缓存根     STABLEWM_HOME=/home/ubuntu/stable-wm-cache   (datasets/ + checkpoints/)
镜像      HF_ENDPOINT=https://hf-mirror.com   (会 302 到 huggingface.co CDN; 实测 ~1.5MB/s)
预检      scripts/preflight_check.py eval-official --task <t> --cache-dir $STABLEWM_HOME --policy recovery_delta_full_<t>_s3072
          (期望除 code integrity 外全 PASS; code integrity 报 module.py/train.py modified 是本机已知改动)
```

## 权威口径(与 l4_ab/intact_autopilot.sh 完全一致)
```bash
cd /home/ubuntu/INTACT-JEPA/paper_runtime
PYTHONPATH=/home/ubuntu/INTACT-JEPA/paper_runtime:/home/ubuntu/INTACT-JEPA \
STABLEWM_HOME=/home/ubuntu/stable-wm-cache LOCAL_DATASET_DIR=/home/ubuntu/stable-wm-cache \
MUJOCO_GL=egl PYOPENGL_PLATFORM=egl CUBLAS_WORKSPACE_CONFIG=:4096:8 \
/home/ubuntu/INTACT-JEPA/.venv/bin/python eval.py \
  --config-name=<pusht|cube|reacher|tworoom> solver=prior_only \
  policy=recovery_delta_full_<task>_s3072 seed=<0|1|42> eval.num_eval=100
```
- `solver=prior_only` = 论文 Direct/零搜索; 判据解里的 `solver_timing`: `get_cost_calls_mean=0` ·
  `candidate_action_steps_mean=0` · `configured_rollout_budget_mean=0` · `actor_warmstart_enabled_mean=1`
- 结果落 `$STABLEWM_HOME/<result_file>.txt`(追加) + 同名 `.json` 边车; result_file: pusht→pusht_results.txt,
  cube→ogb_cube_results.txt, reacher→dmc_results.txt, tworoom→tworoom_results.txt
- **逐局视频**落 `$STABLEWM_HOME/env_<i>.mp4`(736×288 · 50帧 · 15fps · 3 面板 agent|dataset|goal);
  下次运行同名覆盖 → 要留证必须跑完立刻归档
- 一次跑 = `eval.num_eval` 个并行 env; `world.max_episode_steps` 由 eval.py 设为 `2×eval_budget`

## 数据集来源 (HF 集合 quentinll/lewm) 与落位
| 任务 | HF 仓库 | 归档 | 解出 | eval 期望路径 |
|---|---|---|---|---|
| pusht | quentinll/lewm-pusht | pusht_expert_train.h5.zst (12.5G) | 43.1G | datasets/pusht_expert_train.h5 |
| cube | quentinll/lewm-cube | cube_single_expert.tar.zst | 94.9G | datasets/ogbench/cube_single_expert.h5 (软链 ../cube_single_expert.h5) |
| reacher | quentinll/lewm-reacher | reacher.tar.zst (22GiB) | 98.9G | datasets/reacher.h5 + 软链 datasets/dmc/reacher_random.h5 (配置里 dataset_name=dmc/reacher_random) |
| tworoom | quentinll/lewm-tworooms | tworoom.tar.zst (3.1G) | 11.9G | datasets/tworoom.h5 |

权重: HF `INTACT-JEPA/INTACT` @ revision `paper-e5-goal-v1`, 资产 `intact-goal-e5-seed<seed>.tar.gz`
→ `checkpoints/recovery_delta_full_<task>_s<seed>/weights_epoch_5.pt`。
发布包是 6 cell × 3 training seed × 4 task shard = 72 片, 本地通常只有 seed3072 那 4 片;
4 片逐张量比对: 198 个 ViT encoder 张量完全相同(共享编码器), 只有 action_encoder/predictor/actor 分任务
(动作输出块维度不同: pusht/reacher/tworoom 10, cube 25)。
清单/对账: `INTACT-JEPA/checkpoints_hf/INTACT-unified/PAPER_E5_GOAL_MANIFEST.json`

**本机实测基线 (seed3072 分片, 3 个 eval seed 均值; 括号内为官方同训练种子)**
```
pusht 79.33±4.93 (79.67) · cube 98.67±1.53 (98.67) · reacher 97.00±2.00 (97.0) · tworoom 78.67±4.04 (78.67)
```

## 坑 (全踩过, 逐条带判据)
1. **两处同名 module.py 抢 import** → `InstantiationException: Error locating target 'module.InverseTransitionActor'`
   - 根目录 `INTACT-JEPA/module.py`(只有 ARPredictor/IntentActionActor/Embedder/MLP) 与
     `paper_runtime/module.py`(有 InverseTransitionActor/Mixture…); `sys.path[0]` = **脚本所在目录**,
     比 PYTHONPATH 还靠前 ⇒ 用根 `eval.py`(cwd=根) 加载论文权重必然命中根 module.py 而失败。
   - 论文权重(config.json 里 `inverse_actor._target_=module.InverseTransitionActor`) **只能走 `paper_runtime/eval.py`**;
     根运行时的 `direct_solver` 检查 `has_intent_actor()`(根命名) 与论文 jepa(`inverse_actor`) 不兼容。
2. **h5 必须先落位**: 只有 `.zst/.tar.zst` 时 eval 报 FileNotFoundError(文件还没解压)。
3. **读 h5 数据前 `import hdf5plugin`**: 只读 keys/形状不报, 一读像素就 `OSError: can't open directory (/usr/local/lib/plugin)`。
4. **文件"在"≠完整**: 截断的 h5 能 open 也能 cache 列, 但读到缺失区间报
   `OSError: filter returned failure during read`; 直接 open 会给出
   `truncated file: eof=<实体大小>, stored_eof=<应有大小>`。判真身只看这个 stored_eof, 或 `zstd -t` / `tar -tvf`。
5. **每任务的 callables/列不同**(照抄 config/eval/<task>.yaml, 别套用另一个任务):
   - pusht: `_set_state(state)` → 数据集需 `state` 列
   - cube: `set_state(qpos,qvel)` + `set_target_pos(cube_id=0, target_pos=goal_privileged_block_0_pos, target_quat=goal_privileged_block_0_quat)`
   - reacher: `set_state(qpos,qvel)` + `set_target_qpos(goal_qpos)`, 且 **env 必须 `task=qpos_match`**(否则 assert)
   - `keys_to_cache` 只用于拟合归一化统计: pusht 需 action/proprio/state, cube/reacher 只需 action
6. **磁盘**: 四个原始 h5 全驻盘 ≈249G, 加开发环境/缓存会顶爆 396G 盘的 300G 红线 ⇒ 只留正在用的数据集;
   删前把 3 seed 结果 json + `videos/<task>_seed*/`(100 局 + showcase) 归档到 `l4_ab/intact_results/`
7. **删大文件前验证依赖**: 曾把 22GiB `reacher.tar.zst` 当冗余删掉, 而 `datasets/dmc/reacher_random.h5`
   只是它内含 reacher.h5(98.9GB) 的 **2GB 截断残片** ⇒ 唯一完整来源被删。删前用 stored_eof/`zstd -t` 验证, 别假设同名小文件是独立数据集

## 快速看例子: 自采 mini 集 (不等大下载, ~10 秒)
swm 自带采集器, 官方同 env 同格式:
```python
import stable_worldmodel as swm            # 需 MUJOCO_GL=egl
w = swm.World(env_name="swm/ReacherDMControl-v0", num_envs=20,
              max_episode_steps=100, image_shape=(224, 224), task="qpos_match")
w.set_policy(swm.policy.RandomPolicy())
w.collect(path="<cache>/datasets/reacher_mini.h5", episodes=40, seed=0, format="hdf5")
```
采完补列(否则 eval 起不来): `ep_idx = repeat(arange(n_ep), ep_len)` · `proprio = observation` ·
`goal_qpos = qpos`(eval 在 `start+goal_offset` 那一行读 goal_qpos 当目标关节角)。
跑: `eval.dataset_name=reacher_mini`(`HDF5Dataset` 按 `<cache>/datasets/<name>.h5` 解析)。
⚠️ 自采口径 ≠ 官方(40 回合随机策略 vs 官方全量), 结果文件/编号必须标注「非官方口径」, 不可与官方 SR 对比。

## 调试配置 (VSCode, .vscode/launch.json)
② cube 快捷档: `--config-name=cube solver=prior_only policy=recovery_delta_full_cube_s3072 seed=42 eval.num_eval=20`
模拟 reacher 预览档: `--config-name=reacher … eval.dataset_name=reacher_mini eval.num_eval=8`
断点看输入/动作: `paper_runtime/prior_only_solver.py:22`(动作张量, 入参形状实测 `pixels (envs,1,3,224,224) float32` ImageNet 归一化, `goal` 同规格) ·
`paper_runtime/jepa.py:645`(图像断言) · 动作链 solver→`jepa.py:638 get_action`→`module.py:246 InverseTransitionActor`→`swm/world/world.py:408 envs.step`

## 验证清单(交付前)
1. 预检 PASS(除 code integrity) 2. 解里 `success_rate` + 零搜索凭据 4 项
3. 视频抽帧 std>5(真图, 非黑帧) + ffprobe 尺寸/帧数 4. 结果 json 归档到 intact_results/ 后才允许删数据
