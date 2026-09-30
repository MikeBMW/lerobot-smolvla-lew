# INTACT-JEPA 本地自主运行 (Z-MAX 集成)

把 [zju3dv/INTACT-JEPA](https://github.com/zju3dv/INTACT-JEPA)（INTACT: Isomorphic Intent-to-Action
Learning for Search-Free World Models, MIT）在本机跑成**一条命令、幂等、可无人值守**的流程，
并作为状态空间 L4 层「🧠 INTACT 意图-动作」节点的后端
（节点封装见 `src/lerobot/manifold/intact_node/`，设计见 `docs/design/zmax_intact_node.md`）。

## 一键运行

```bash
bash tools/intact/run_paper_direct.sh pusht recovery_delta_full_pusht_s3072 42 100   # 单任务单 seed
bash tools/intact/intact_autopilot.sh --tasks "pusht tworoom reacher cube" --seeds "0 1 42" --num 100
```

流水线阶段：**环境自检 → 逐任务[下载 → size+SHA256 双核 → 解压 → 删归档] → 逐 seed 官方 Direct 评测 → 汇总**。
幂等：已完成的 seed / 已在位的数据集自动跳过；下载断点续传。

## 环境前置（一次性）

```bash
cd /home/ubuntu/INTACT-JEPA && bash scripts/install.sh cu124   # 若报需要 python3.10/uv 则用 uv 装
# .env: STABLEWM_HOME / LOCAL_DATASET_DIR 指向缓存根 (本机 = /home/ubuntu/stable-wm-cache)
# 权重: HF INTACT-JEPA/INTACT@paper-e5-goal-v1 的 intact-goal-e5-seed3072.tar.gz (~315MB)
#       解包到 $STABLEWM_HOME/checkpoints/recovery_delta_full_<task>_s3072/weights_epoch_5.pt
```

## 三条硬约束（都是踩出来的，违反会静默出错）

1. **论文 checkpoint 必须用 `paper_runtime`** — 官方 README 明说根运行时参数布局不同
   ("loading paper checkpoints through the root runtime is not supported")；
   且求解器要用论文自带的 `prior_only_solver.PriorOnlySolver`（零搜索），
   **不是**根仓库的 `direct_solver.py`（它检查 `has_intent_actor()`，论文里叫 `inverse_actor`）。
   运行前 `sha256sum -c paper_runtime/RUNTIME_SHA256SUMS` 校验评测指纹（5 文件），不得改动。
2. **数据完成判据 = size + SHA256 双核**，不能用文件大小 —— 多连接下载会让文件长度提前撑到高位、
   中间留空洞（实测 3GB/5GB 处整段为 0）。按大小判"下满"会解压出**截断的假 .h5**。
3. **hf-mirror 会回 308 Permanent Redirect**，Python 3.10 的 `urllib` 完全不支持 308
   （既无 `http_error_308` handler，`redirect_request` 白名单也只有 301/302/303/307）
   → 表现为"取不到元数据"或"`hf_hub_download` 卡 0 字节"。`hf_asset.py` 里两处都补了。

## 状态空间里的「单步运行」— 可以，且已实测

节点一次 `step()` = **一次真实模型前向**（obs 滑窗 + goal + 动作历史 → `model.get_action` → action chunk），
**无候选搜索**。三种触发方式等价：

```bash
# CLI 单步自检 (真权重; 会打印每步 chunk 形状/非零/std/诊断)
STABLEWM_HOME=$STABLEWM_HOME INTACT_RUNTIME=paper INTACT_DEVICE=cuda \
  PYTHONPATH=src python -m lerobot.manifold.intact_node.selftest --real
# 防假成功闸自检 (确定性"不可用"运行时; 节点必须拒绝返回零动作)
PYTHONPATH=src python -m lerobot.manifold.intact_node.selftest
# 画布路径 (等价 GUI 双击/单步执行该节点)
PYTHONPATH=src python -c "import sys;sys.path.insert(0,'tools/gui');import node_logic as n;n.node_intact({'log':print,'root':'.'})"
```
GUI 里：画布 L4 层节点「🧠 INTACT 意图-动作」→ **双击** / 右键运行节点 / ⏭单步 走执行链，均执行真实前向。

**实测 (paper 权重, GPU, 单步)**
```
step1: chunk(4,10) nonzero=40 std=0.2291 trained=True  forward_calls=4 candidate_sequences=0
step2: chunk(4,10) nonzero=40 std=0.2388 trained=True  (与上一步不同 → 随观测/动作历史变化)
step3: chunk(4,10) nonzero=40 std=0.2465 trained=True
平均单步 316 ms (含跨 venv IPC + 前向) · RobotIO 逐步下发 12 = 3×4
```

**单步正确性的三道闸 (踩坑换来的)**
1. `goal` 必须 **5 维** `[B,T,C,H,W]` — 模型内部把 `goal["pixels"]` 直接喂 ViT，传 4 维报
   `expected 4, got 3`；
2. 动作历史由**节点**持有并滚动注入（数据源每次给 raw 零 = reset 语义；不注入则每步输出恒定）；
3. 模型返回可能带 batch 维 `[1,H,D]` → 统一裁成 `[H,D]`；`act` 失败时 adapter 会返回零动作，
   **节点必须显式报错拒绝**（否则"形状对 + 全零"会被当成成功）。

## 本机实测结果（pusht，官方 Direct 协议，权重 = 训练 seed 3072 分片）

| eval seed | 本机 SR% | 成功数 |
|---|---|---|
| 0 | 76.00 | 76/100 |
| 1 | 85.00 | 85/100 |
| 42 | 77.00 | 77/100 |
| **均值** | **79.33 ± 4.93** | — |
| 官方同训练种子(3072) | 79.67 | 来源 `docs/PAPER_CHECKPOINTS.md` |
| 官方三训练种子均值 | 80.22 ± 1.26 | 来源 `checkpoints/PAPER_E5_GOAL_MANIFEST.json` |

**零搜索凭据**（逐 seed 实测，取自 `solver_timing`，非默认值）：
`get_cost_calls_mean = 0` · `candidate_action_steps_mean = 0` · `configured_rollout_budget_mean = 0` ·
`actor_warmstart_enabled_mean = 1`（意图 actor 真参与）· `solve_time_mean ≈ 0.27 s`（100 环境批量 Direct 规划，无候选搜索）

## 磁盘闸门

单任务启动前需 `≈2.6 × 压缩包 + 15GB` 可用空间；不足则**诚实跳过并记录**（不静默）。
cube 压缩包 46.2GB（解压后更大）→ 本机曾因可用不足 135GB 被闸门拦下。

## 文件

| 文件 | 作用 |
|---|---|
| `intact_autopilot.sh` | 主流水线（幂等/续传/磁盘闸门/多 seed） |
| `run_paper_direct.sh` | 单任务单 seed 评测（含指纹校验 + 就位检查） |
| `hf_asset.py` | HF 资产元数据/校验/URL（含 308 修复） |
| `intact_summary.py` | 汇总 → `SUMMARY.md` + `summary.json`（本机 vs 官方口径并列） |
| `SUMMARY_pusht.md` | 最近一次汇总快照 |
