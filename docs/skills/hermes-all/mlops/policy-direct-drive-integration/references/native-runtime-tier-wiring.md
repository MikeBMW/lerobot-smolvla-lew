# 原项目原生运行时 (paper_runtime) 跑评测 + 档位级接线 runbook

2026-09-12 实测, 仓库 `/home/ubuntu/INTACT-JEPA` + 本工程 `/home/ubuntu/lerobot-smolvla-lew`。
所有数字来自真实命令输出 (无估算)。

## 1. 原生权重评测 (零训练, 拿"原项目机器人被原项目权重驱动"的证据)

```bash
cd /home/ubuntu/INTACT-JEPA/paper_runtime            # ⚠️ 必须在 paper_runtime 下
export INTACT_SKIP_PREFLIGHT=1
export STABLEWM_HOME=/home/ubuntu/stable-wm-cache LOCAL_DATASET_DIR=/home/ubuntu/stable-wm-cache
export HF_ENDPOINT=https://hf-mirror.com MUJOCO_GL=egl PYOPENGL_PLATFORM=egl
export HDF5_PLUGIN_PATH=/home/ubuntu/.h5plugins PYTHONPATH=/home/ubuntu/INTACT-JEPA/paper_runtime
../.venv/bin/python eval.py --config-name=tworoom solver=prior_only \
    policy=recovery_delta_full_tworoom_s3072 seed=42 eval.num_eval=6 \
    output.filename=tworoom_direct_seed42_n6.txt
```

| 现象 | 根因 | 正解 |
|---|---|---|
| `Error locating target 'module.InverseTransitionActor'` | 在**仓库根**跑, 根运行时没有论文 actor 类 | `cd paper_runtime` (并把它放进 `PYTHONPATH`) |
| `Error locating target 'direct_solver.DirectSolver'` | `solver=direct` 不存在于 paper_runtime | 用 `solver=prior_only` (= 论文零搜索接口, `n_steps=0`) |
| 找不到结果文件 | 文件名逐任务不同 | 取 `config/eval/<task>.yaml::output.filename` |
| 视频不知道在哪 | 路径 = checkpoint 的父目录 | 缓存里 `checkpoints/env_*.mp4` (每次评测会覆盖 → 跑完立刻复制走) |
| `Unable to open file ... nosuchfile datasets/<name>.h5` | 数据集须落 `$STABLEWM_HOME/datasets/<name>.h5` | pusht=`pusht_expert_train.h5` · reacher=`dmc/reacher_random.h5` · cube=`ogbench/cube_single_expert.h5` · tworoom=`tworoom.h5` |

实测结果 (6 集, seed 42, 零搜索):

| 任务 | 环境 | success | get_cost_calls | 视频 |
|---|---|---|---|---|
| tworoom | OGBench tworoom | **100% (6/6)** | 0 | `reports/intact_official/tworoom/env_0..5.mp4` |
| cube | OGBench cube-single | **83.3% (5/6)** | 0 | `reports/intact_official/cube/env_0..5.mp4` |
| reacher | swm/ReacherDMControl-v0 | 待数据集 | — | — |
| pusht | swm/PushT-v1 | 待数据集 | — | — |

任务名撞车 (对外解释"为什么还要训练"):
- 原项目 `reacher` = **DMControl 两连杆臂** (`qpos_match`, 关节动作) —— 不是 metaworld 的 Sawyer 臂。
- 我们的任务 = metaworld **Sawyer peg-insert-side-v3** (4D 笛卡尔动作) → 原项目**从未训过** → 只能域内微调。
- 原生权重直开我们的机器人 = zero-shot, 实测 **0/2** (动作头输出与我们的动作空间 |ρ|≤0.22)。

## 2. 本工程侧接线的两个坑 (都实测)

1. **引擎不自动挂节点**: `SS_INTACT=1` 只影响 `_intact_u_ff` 分支, 节点要外部 `sim.attach_intact(node, adapter)`
   才会挂。未挂时: 120 步跑完、`_intact_node=None`、无任何报错 (静默"没接管")。
2. **`IntactRuntime(task=...)` 是原项目注册表名**:
   ```text
   task="insert" → 解析 recovery_delta_full_insert_s3072 (不存在)
                 → "数据源=未设置 · 策略=direct(零搜索) · action_dim=4 · trained=False"
                 → 每步 RuntimeError: INTACT 推理失败/未训练, 拒绝返回零动作 → 下发 [0,0,0,0]
   可用配置: INTACT_RUNTIME=root + INTACT_POLICY=intact_goal_zmax_v2_s3072/weights_epoch_N.pt
             + IntactRuntime(task="pusht", device="cpu")  → action_dim=8 · trained=True
   ```
   直驱脚本 `tools/intact_direct_rollout.py` 的 `--task` 默认值就是可用的那个 (registry 名)。

## 3. 直驱装配 (CLI 与 GUI 共用一份代码)

`tools/intact_direct_rollout.py::install_direct_act(sim, node, a_mean, a_std, infer_every=1, ...)`
- 包 `sim.sched.decide`: 先调原函数**只取阶段标签**, 再渲染真帧 → `node.step(fr, obs_source="engine_render")`
  → `chunk[step, slot*4:(slot+1)*4]` → `a_raw = z·std + mean` → `sim._direct_act`。
- 每次 `_reset` 后重新包 (sched 在 `_reset()` 里才建) — 否则第二回合失去直驱。
- 引擎侧 `_direct_act` 非 None 时该值就是 env 级动作 (clip ±1), 且**绕过夹爪阈值化/重抓逻辑**。

目标帧工件: `tools/make_intact_goal_frame.py --mode analytic --seed 0` → `reports/intact_goal_frame.npy`
((3,224,224) float32) + `.json` provenance (seed / done / steps / 插入mm / 帧std)。
**别用"数据集里帧数最多的回合"当 goal — 那是失败回合 (跑满 max_steps 才最长)。**

档位接线实测 (L4 档 + `chk_intact_exec` 默认勾选):
```
INTACT trained=True · action_dim=8 · policy=intact_goal_zmax_v2_s3072/weights_epoch_3.pt
150 步 · 真推理 150 次 · 错误 无
模型原始动作(归一化) [-0.019, 0.1235, 0.2301, 0.6563] → a_raw [-0.010, 0.002, 0.024, 0.601]
插入 177.6mm · done=False     (解析链同种子: 387 步 / 65.1mm 成功)
```
⇒ 接线成立, 任务是"模型能力不足"而不是"没接上"。日志必须同时给真推理次数 + 动作 + 结果,
否则"接管了没接管"无法判断。

## 4. 逐 epoch 判闸守护 (无人值守)

```bash
# 每落一个 .pt 就评一次 (CPU 推理, 不抢训练显存); 结果追加到日志 + 每 epoch 一个 json
while pgrep -f 'train.py --config-name <cfg>' >/dev/null || [ -n "$(ls <ckptdir>/*.pt 2>/dev/null)" ]; do
  for w in <ckptdir>/weights_epoch_*.pt; do
    grep -qx "$w" /tmp/gated.txt 2>/dev/null && continue
    INTACT_POLICY="$w" <venv>/python tools/intact_replay_check.py --n 60 --stride 300 --device cpu \
      --out "reports/intact_replay_$(basename "$w" .pt).json" && echo "$w" >> /tmp/gated.txt
  done; sleep 60
done
```
实测三个 epoch: MAE 0.1122 → **0.0968** → 0.0974 (常数基线 0.0993), 预测 std 始终 ~16× 小于教师
⇒ 全程判"未过闸", 不上闭环。判闸结论要写"未过 + 哪里没过", 不要只写"无提升"。
