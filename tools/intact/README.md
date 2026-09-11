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
