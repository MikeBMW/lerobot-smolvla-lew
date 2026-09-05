# 20260807 光模块数据生成链路 (peg-insert-side-v3)

官方专家策略采样成功轨迹 → npz → npz_to_lerobot 转训练格式。生成任意 metaworld 任务数据同法。

## 生成脚本 tools/gen_peg_data.py

- 专家策略：`metaworld.policies.sawyer_peg_insertion_side_v3_policy.SawyerPegInsertionSideV3Policy`（官方规则策略，插入成功率 ~85%）
- 命令：`./.venv/bin/python tools/gen_peg_data.py --eps 30 --out data/metaworld_peg_v2`
- 关键参数：
  - `--camera corner2`（与 rollout 视频同视角，一致性）
  - `--img 128`（对齐训练管道 IMG_SIZE）
  - 失败轨迹 150 步提前终止（`max_steps = 150 if ep_idx % 4 else 300`，渲染慢）
- 观测：`env._get_obs()` 39D（含 peg/hole 目标坐标）；图像从 obs dict `observation.image` 取（V3 env obs 是 dict；reset 返回 dict/数组兼容处理）
- 结果：30 成功 eps / 41 尝试（73%）；5850 帧（每 eps ~195 帧）；train 80% (4800) + val 20% (1050)

## npz_to_lerobot 转换

- `./.venv/bin/python tools/npz_to_lerobot.py --npz data/metaworld_peg_v2/train.npz --out data/metaworld_peg_lerobot --task "..." --fps 10 --episode-frames 200`
- 24 eps / 4800 帧 parquet（train 部分）；**val 6 eps 不转**（训练/验证标准划分，用户问"下载全么"时解释）
- 命名：官方任务名 **peg-insert-side-v3**（本地目录名 peg_v2/peg_lerobot 是内部存储名）

## 数据内容判定要点

- metaworld success 标记：**只有 episode 最后一帧 success=1**（中间帧全 0）——"1.1% 成功率"≠失败轨迹，是 10/10 全成功（读 next.success 分布时注意）
- MT50 官方 50 任务，本地只下载了 chunk-000 前 2 片 = task 0（nut-on-peg 套环）——其他任务需下载更多分片
- metaworld/policies/ 下 50 个策略文件 = 50 任务的专家数据源，`sawyer_<task>_v3_policy.py` 命名规则
