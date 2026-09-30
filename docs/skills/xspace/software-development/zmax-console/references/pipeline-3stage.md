# 三阶段渐进式训练管线 (2026-08-02 落地)

老倪策略: **仿真快速验证 → 零样本测试 → 真机保守微调**。落地为 `tools/cicd_pipeline.py` + GUI `PipelinePanel` (simulink_module.py, 「🎯 3阶段」按钮)。

## 三阶段定义 (STAGES dict)

| Stage | 数据 | 超参 (ACTConfig) | 意图 |
|---|---|---|---|
| 1 MetaWorld 仿真 | data/metaworld_joint_v2 (关节空间 7D/6D/64², 后文"joint 采集治本") | lr=1e-4, lr_backbone=0(冻结), kl=10, chunk=100, n_action=50, 无ensemble | 快速验证算法/数据 |
| 2 Sim-to-Real 测试 | data/closed_loop_v2 (Orin 7D/6D/64² LeRobot 目录) | 加载 stage1 ckpt 评估 MSE/成功率/延迟 (先仿真验证再 Sim2Real) | 量化 Reality Gap |
| 3 Orin 微调 | data/closed_loop_v2 | lr=1e-5, lr_backbone=1e-6, kl=10, chunk=100, n_action=1, ensemble=0.01, policy.path=stage1 ckpt (CLI --policy.path= 等号) | 保守迁移 |

命令: `.venv/bin/python tools/cicd_pipeline.py run --steps1 N --steps3 N` (自动流转) / `stage N --steps N` (单阶段) / `status` / `test` (最少迭代跑通链路)。状态落 `docs/PIPELINE_STATE.json`，GUI 面板 2s 轮询刷新。

## 状态结构 — 每阶段独立持久化 (用户实测反馈修复)

**用户反馈 (2026-08-02): "我运行了第一阶段，应该显示已完成"** — 旧结构只存 `{stage, state}` 全局字段，S1 完成后自动进入 S2 时 `stage=2`，面板把 S1 卡打回"未开始"。修复 (commit 4dc029f5):

```json
{ "stage": 2, "state": "running", "log": "...",
  "stages": {
    "1": {"state": "success", "ckpt": ".../pretrained_model", "steps": 300},
    "2": {"state": "success", "result": {"dim_mismatch": true, ...}},
    "3": {"state": "pending"}
  } }
```

- `run_stage()`: 每阶段 `stages[str(stage)]` 独立 state/ckpt/result，历史阶段**不被后续阶段覆盖**；全局 stage/state 只反映当前阶段。
- PipelinePanel._refresh 读 `stages` 而非全局 state：每张卡独立颜色/徽章。
- 兼容旧字段: `ckpt1`/`stage2`/`ckpt3` 顶层字段保留为兜底读 (stages 优先)。
- ckpt 显示用 `Path(ckpt).parts[-4]` 取训练目录名 (pretrained_model/000300/checkpoints/<dir> — dirname 两次会取到 "checkpoints"，本会话踩过)。

## 配置生成 (gen_train_cfg) — 踩过的坑

- **re.sub 子串误匹配**: pattern `(steps:\s*).*` 会先匹配到 `n_obs_steps: 1` (它在文件更靠前) → 顶层 `steps: 300` 没被改。**必须行锚定**: `(?m)^steps:.*`。
- **重复键覆盖**: 模板 policy 段已有 n_obs_steps/n_action_steps/chunk_size，直接插入新值会被旧值覆盖。先删旧行 `(?m)^  {k}:.*\n` 再插入。
- **yaml 浮点坑**: `f"{1e-5}"` = `'1e-05'` 无小数点 → pyyaml 解析为 **str** → draccus DecodingError。必须 `_f(x)` 格式化: `f"{x:.6f}".rstrip('0').rstrip('.')` + 无小数点补 `.0` (10.0→'10.0', 0.0→'0.0', 1e-5→'0.00001')。
- **temporal_ensemble 与 n_action_steps 互斥**: ACTConfig 要求 ensemble 时 `n_action_steps=1` (每步查询才能集成)。S3 用 ensemble=0.01 必须 n_action=1。报错: `n_action_steps must be 1 when using temporal ensembling`。
- **预训练初始化 (2026-08-02 修正, 三处全踩过)**: CLI 传 **`--policy.path=<ckpt_dir>` 必须等号形式** — 空格形式报 `unrecognized arguments: --policy.path`; `--policy <dir>` 报 `Expected a dict for a choice class`; **YAML policy 段写 `path:` 会崩** (`The fields path are not valid for ACTConfig`)。正确: `lerobot_train --config_path <cfg> --policy.path=<ckpt_dir>`。TrainPipelineConfig 没有 from_yaml 方法，配置合法性用 yaml.safe_load 断言或直接跑训练验证。

## 维度不匹配 → joint 采集治本 (2026-08-02 后半段)

原状: metaworld = 4D state/4D action (LeRobot mt50 数据集是**任务空间**观测: 末端 xyz+夹爪); Orin closed_loop = 7D/6D。维度不同 → 零样本测试和权重迁移物理不可行 (Stage2 catch RuntimeError 报 dim_mismatch, Stage3 降级从零训练)。

**治本: `tools/collect_metaworld_joint.py` 用 MuJoCo qpos 采关节空间数据** → `data/metaworld_joint_v2` (7D state/6D action/64² 图) 与 Orin `closed_loop_v2` **完全同维度**:
- state = `env.data.qpos[0:6]` 前6关节角 + 夹爪归一化距离 (`norm(rightclaw.xpos-leftclaw.xpos)/0.1` clip 0-1) → 7D
- action = 关节速度差分 `qpos[0:6]` 逐帧差 → 6D (metaworld 3.x 无 joint action 模式, 只能记录差分)
- image = `mujoco.Renderer(env.model, 64, 64)` offscreen (WSL headless OK)
- metaworld 3.1.1 API: `MT1('reach-v3')` (v2 名报 not a V3); 先 `env.set_task(mt.train_tasks[0])` 再 reset (否则 AssertionError _last_rand_vec); Gymnasium 元组式 reset/step; `qpos` 16D 前 7 才是关节角; 夹爪 body 名 rightclaw/leftclaw
- Stage1 数据切到 joint 集后: Stage2 Sim2Real **真正跑通** (实测 MSE=0.0884 成功率0% "零样本需微调", 不再是维度不匹配), Stage3 权重迁移成功 (不再降级)。这是用户策略"仿真预训练→真机微调"成立的前提。

## Stage2 失败排查 (2026-08-02 用户 "为什么阶段2失败了")

**验证/测试脚本污染真实 `docs/PIPELINE_STATE.json`** (写入模拟 stages) → stages.1 丢失 → run_stage(2) 找不到 S1 ckpt → 旧兜底 `latest_ckpt("outputs/train/act_mw_v111")` 回退到**假训练时代的 2D/pusht 模型** → 在 4D 真实数据上 mat1/mat2 崩 → failed。教训:
- **测试脚本不得写真实状态文件** (用临时路径或跑完恢复原文件)
- 兜底必须 `latest_s1_ckpt()` (glob outputs/train/act_s1_* 按 mtime 最新, 真实模型), **固定旧目录名会捡回假训练产物**
- 判别模型真假: config.json `input_features` state shape (真 metaworld=4 / 真 orin=7 / 假 pusht 模板=2)

## 数据链路 (已实测)

- data/metaworld_act: LeRobot 格式目录 (train/val.npz + meta/) ✓ 可直接 root 训练
- data/closed_loop: task_closed_loop.npz 含 observations(3,64,64)+states(7)+actions(6) — 完整版; _ensure_training_data 只存 states/actions (无图)
- 20 步最少迭代全链路实测 ~40s: S1 metaworld → S2 dim_mismatch 报告 → S3 从零训练 closed_loop (22M 参数, 161 帧)

## GUI PipelinePanel

- 3 张 QFrame 阶段卡 (状态色: pending灰/running青/success绿/failed红, 2s QTimer 轮询 PIPELINE_STATE.json)
- S1/S3 卡带 steps QSpinBox (可配), S2 无
- 每卡「▶ 运行本阶段」+ 底部「▶ 全流程自动运行 (1→2→3)」
- 执行走 CICDWorker 后台线程跑 `[.venv/bin/python, tools/cicd_pipeline.py, ...]`，日志流式进面板 log_box
- closeEvent 必须停 _timer
