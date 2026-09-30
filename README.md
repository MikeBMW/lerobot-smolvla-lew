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
- **模型/数据默认落盘路径**（`ZMAX_DATA/models`、`zmax_data/hf_cache`、`zmax_data/stable-wm-cache`）见
  [`docs/notes/model-paths.md`](docs/notes/model-paths.md)；清单是机器可读的 `tools/zmax_assets.json`。

## 首次 clone 之后（新机器初始化）

```bash
git clone https://github.com/MikeBMW/zmax.git /home/ubuntu/zmax && cd /home/ubuntu/zmax
bash tools/zmax_bootstrap.sh            # ① 只读体检: 识别本机已下载的模型/数据, 列出缺什么(给确切命令)
bash tools/zmax_bootstrap.sh --apply    # ② 铺目录骨架 + 写 zmax_paths.env + 采纳老位置资产(软链)
bash tools/zmax_bootstrap.sh --smoke    # ③ 状态空间功能自检: 10 个核心模块导入 + 关键文件 + 端口
bash tools/zmax_bootstrap.sh --download # ④ (按需) 下缺失的模型/数据, 走 hf-mirror
bash tools/zmax_bootstrap.sh --systemd  # ⑤ (按需) 装 30 个 systemd 单元
bash tools/zmax_bootstrap.sh --secrets  # ⑥ (按需) 生成密钥占位文件, 现场填真值
```

识别顺序：默认路径 → 老位置 `alt_paths` → 精确文件 `alt_globs` → HF 老缓存 `~/.cache/huggingface`。
**已经下载过的一律不重下**，只建软链把约定路径接上。`--apply` 只增不改不删。

基线能恢复到什么程度、哪些东西搬不动（现场标定真值 / 厂商 SDK / 训练产物 / 密钥）：
见 [`docs/notes/restore_matrix.md`](docs/notes/restore_matrix.md)。

## 入库守卫（提交前必跑）

```bash
python3 tools/repo_guard.py     # 大文件/二进制守卫: 权重、交付件、>300KB 二进制一律拒
python3 tools/secret_scan.py    # 密钥扫描: 真密钥形态命中即拒(值打码输出)
```

密钥真值只放 `/home/ubuntu/zmax_data/secrets/zmax.env`（600，永不入库）；
systemd 单元用 `EnvironmentFile=-/home/ubuntu/zmax_data/secrets/zmax.env` + `${VAR}` 引用。

## 不进仓库的东西（有意为之）

运行截图与状态快照（`reports/`，数百 MB）、模型权重（`*.pt`/`*.h5`）、交付件（`pdf`/`pptx`/`zip`）、
视频、虚拟环境 —— 都留在本机 `/home/ubuntu/zmax_data/`，避免代码库被二进制拖大。

## 同步

```bash
bash tools/sync_hermes_to_repo.sh          # 技能 + 记忆 → docs/ 并推送
```
