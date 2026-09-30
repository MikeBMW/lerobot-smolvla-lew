# Z-MAX 模型 / 数据 的默认落盘路径（约定）

> 一句话：**代码在 `/home/ubuntu/zmax`（git 仓库），一切"重"的东西在 `/home/ubuntu/zmax_data`，
> 模型下载默认落 `<数据盘>/models`，HF 下载默认走 `<数据盘>/hf_cache`。**
> 仓库永远不含权重/数据集（大文件不进库），但仓库里带着**清单 + 识别器**：新机器 clone 下来跑一次
> `bash tools/zmax_bootstrap.sh` 就知道哪些已经有了、哪些缺、缺的怎么取——**已经下载过的绝不重下**。

## 1. 路径表

| 变量 | 默认值 | 放什么 |
|---|---|---|
| `ZMAX_CODE` | `/home/ubuntu/zmax` | 代码/技能/记忆（git 仓库） |
| `ZMAX_DATA` | `/home/ubuntu/zmax_data` | 所有"重"东西的根（数据盘；本机绑 E 盘） |
| `ZMAX_MODELS` | `$ZMAX_DATA/models` | **模型默认下载根**（权重、第三方模型目录） |
| `ZMAX_HF_HOME` | `$ZMAX_DATA/hf_cache` | **HF 缓存默认根**（布局同 `~/.cache/huggingface`，即 `hub/models--…`） |
| `STABLEWM_HOME` | `$ZMAX_DATA/stable-wm-cache` | 训练集 + 训练产物（世界模型/BC/LoRA） |
| `ZMAX_SECRETS` | `$ZMAX_DATA/secrets` | 本机密钥 `zmax.env`（600，**永不入库**） |
| `ZMAX_REPOS` | `/home/ubuntu` | 第三方仓库源码（如 `INTACT-JEPA`） |

覆盖方式：环境变量优先级最高；`bash tools/zmax_bootstrap.sh --apply` 会把整套约定写成
`$ZMAX_DATA/zmax_paths.env`，`source` 一下所有脚本/服务都用同一套路径（换盘只改这一个文件）。

## 2. 模型：下什么、下到哪、怎么下

| 资产 | 落盘位置 | 体积 | 命令 |
|---|---|---|---|
| SAM3 分割权重 | `$ZMAX_MODELS/sam3_hf` | 3.2G | `HF_ENDPOINT=https://hf-mirror.com hf download facebook/sam3 --include 'model.safetensors' '*.json' --local-dir $ZMAX_MODELS/sam3_hf`（**gated=manual**：需 HF 账号申请授权 + `HF_TOKEN`；有本地副本可直接拷，不必重下） |
| YOLO 在役权重 | `$ZMAX_MODELS/weights/yolov8s.pt` | 21M | `curl -L -o $ZMAX_MODELS/weights/yolov8s.pt https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8s.pt` |
| SmolVLM2-500M | `$ZMAX_HF_HOME/hub/models--HuggingFaceTB--SmolVLM2-500M-Video-Instruct` | 1.9G | `HF_HOME=$ZMAX_HF_HOME hf download HuggingFaceTB/SmolVLM2-500M-Video-Instruct --include 'model.safetensors' '*.json'` ← **必须带 include**，不带会连 `onnx/` 5.4G 一起下（总 7.4G） |
| Qwen2.5-VL-3B | `$ZMAX_HF_HOME/hub/models--Qwen--Qwen2.5-VL-3B-Instruct` | 7.0G | `HF_HOME=$ZMAX_HF_HOME hf download Qwen/Qwen2.5-VL-3B-Instruct` |
| INTACT/LeWM 权重 | `/home/ubuntu/INTACT-JEPA/checkpoints_hf` | 2.5G（hub 上 7G） | `hf download INTACT-JEPA/INTACT --include 'INTACT-unified/*' --local-dir <目标>` 再解压 |
| L3 LoRA / hJEPA 头 | `$ZMAX_MODELS/`、`$ZMAX_DATA/lora_l3_init.pt` | 11M×4 / 11M | **训练产物**：从备份盘恢复，或按仓库里的训练脚本重做 |

## 3. 数据：只有一样要"下载"，其余都是自产

| 数据 | 落盘位置 | 体积 | 取法 |
|---|---|---|---|
| `cube_single_expert.h5` | `$STABLEWM_HOME/datasets/` | **94.9G**（hub 上是 43G 的 `cube_single_expert.tar.zst`） | `hf download quentinll/lewm-cube --local-dir <临时目录>` → 解压 `.tar.zst` → 放回 datasets/。**磁盘要留 ≥145G**（包+解压同在）。 |
| `optical_insert_v5/v6_disturb.h5` | 同上 | 6.9G / 4.0G | 自采集+生成（脚本在 `tools/`），或从备份恢复 |
| `intact_goal_*` / `unified_v*` / `lora_*`（26 个 run） | `$STABLEWM_HOME/checkpoints/` | ~10G+ | 训练产物（保护区，不清理），备份恢复或重训 |

## 4. 三条铁律

1. **大文件不进 git**：权重/数据集/交付件只放 `zmax_data` 或网盘；入库由 `tools/repo_guard.py` 卡体积（>300KB 二进制、>200KB 受限后缀直接拒）。
2. **已有的绝不重下**：识别顺序 = 默认路径 → `alt_paths`（老位置）→ `alt_globs`（精确文件）→ HF 老缓存 `~/.cache/huggingface`。命中即"可用/可采纳"，`--apply` 只加软链不改数据。
3. **密钥不进库**：真值只在 `$ZMAX_SECRETS/zmax.env`（600）；单元用 `EnvironmentFile=` + `${VAR}`；每次提交前 `python3 tools/secret_scan.py --staged`。

## 5. 新机器三步（首 clone）

```bash
git clone https://github.com/MikeBMW/zmax.git /home/ubuntu/zmax
cd /home/ubuntu/zmax
bash tools/zmax_bootstrap.sh            # ① 只读体检：识别已有模型/数据，列出缺什么(给确切命令)
bash tools/zmax_bootstrap.sh --apply    # ② 铺目录骨架 + 写 zmax_paths.env + 采纳老位置资产(软链)
bash tools/zmax_bootstrap.sh --smoke    # ③ 状态空间功能自检：10 个核心模块导入 + 关键文件 + 端口
# 缺模型时： bash tools/zmax_bootstrap.sh --download     (走 hf-mirror)
# 缺服务时： bash tools/zmax_bootstrap.sh --systemd      (装 30 个单元)
# 缺密钥时： bash tools/zmax_bootstrap.sh --secrets      (生成占位，现场填真值)
```

退出码：必需资产齐 = 0；缺必需项 = 1（可进 CI）。

清单是机器可读的：`tools/zmax_assets.json` —— 加一个模型就加一条，不用改脚本。
