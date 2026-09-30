# Z-MAX 工程仓库（zmax）

具身智能机器人平台 Z-MAX 的**工程代码 + Hermes 技能 + 记忆**仓库。
（光模块工厂精细操作：L5 定方向 / L4 认知 / L3 调度 / L2 检测收口）

## 目录

| 路径 | 内容 |
|---|---|
| `src/` | 引擎与策略源码（含左右脑 `src/lerobot/policies/left_right/`，状态空间 `.../left_right/state_space/`） |
| `tools/` | 全部工具：控制台 GUI、L2 守护、相机/推流、DDS、AOI、训练与评测脚本、装机脚本 |
| `configs/` `config/` `flows/` | 模型/训练/状态空间画布配置；`feature.dbc` 能力特征库 |
| `docs/skills/hermes-all/` | Hermes 技能全量镜像（每 6h 由 cron 同步） |
| `docs/memory/` | 记忆备份（MEMORY.md / USER.md 每日快照 + latest） |
| `docs/` | 设计文档、协议、笔记（文本） |
| `scripts/` `docker/` `dds/` `ros_*_ws/` `launch/` | 运行/部署脚手架 |

## 运行环境与路径约定

- 工程根固定为 **`/home/ubuntu/zmax`**（旧名 `/home/ubuntu/zmax_rel`、`/home/ubuntu/zmax_dds` 是软链，兼容保留）。
- 代码内所有绝对路径都以此前缀开头：`/home/ubuntu/zmax/tools/...`。批量统一脚本见 `tools/ns_unify_paths.py`。
- 数据/运行产物不在本仓库：`/home/ubuntu/zmax_data/`（模型权重、数据集原料、备份、运行产物）。

## 不进仓库的东西（有意为之）

运行截图与状态快照（`reports/`，数百 MB）、模型权重（`*.pt`/`*.h5`）、交付件（`pdf`/`pptx`/`zip`）、
视频、虚拟环境 —— 都留在本机 `/home/ubuntu/zmax_data/`，避免代码库被二进制拖大。

## 同步

```bash
bash tools/sync_hermes_to_repo.sh          # 技能 + 记忆 → docs/ 并推送
```
