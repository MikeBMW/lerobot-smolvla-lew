# /home/ubuntu 顶层地图（每个东西是干什么的）

老倪 2026-09-29: 「/home/ubuntu 下的文件好多都不知道是干什么的，整合，没用的都删掉」。
本文是这个目录的**说明书**：每个顶层条目是什么、谁在用、能不能删。整理后顶层 84 条（含必须保留的点文件），磁盘 319G → 292G（红线 300G 以内）。

## 一、工程与代码（唯一真源）

| 路径 | 大小 | 是什么 | 谁在用 |
|---|---|---|---|
| `zmax/` | 1.5G | ★ **唯一工程根**（分支 main）：代码 `src/lerobot/*`、工具 `tools/*`、DDS `tools/dds/*`、状态空间画布、控制台 GUI、文档、台账 | 所有 systemd 服务、cron、控制台、训练脚本 |
| `zmax_data/` | 18G | **数据盘**：模型权重 `models/`、数据集原料 `raw_parts/`、备份 `backups/`、AOI 脚本 `aoi_v4/`、工具链 `toolchains/`、A/B 产物 `l4_ab/` | 训练/推理/AOI/网页 |
| `lerobot-smolvla-lew/` | 53G | **mac-hw 分支工作树**（领先 main 536 提交 + 9 个未提交改动），也是仓库 `.git` 本体与 `gui-venv311` 所在；训练容器 `-v ~/lerobot-smolvla-lew:/app` 挂的是它 | 历史分支/训练容器挂载 ★待老倪定去留 |
| `INTACT-JEPA/` | 11G | INTACT 官方仓库（论文权重 `checkpoints-paper/`、`checkpoints_hf/`、自带 `.git` ≈8.5G） | L4 直驱/官方评测 |
| `lerobot-venv/` | 7.9G | uv 建的 py3.12 venv，跑 `tools/auto_loop.py`（cron `@reboot`）等 | cron + 部分 tools（**在用，勿删**） |
| `dds-venv/` | 62M | DDS 专用 venv（cyclonedds） | `zmax-dds-*` 三个服务 + 探针 |
| `zmax/gui-venv311` | — | 控制台 GUI 的 venv（软链自 mac-hw 树的 gui-venv311） | `zmax-studio.service` |
| `stable-wm-cache/` | 134G | **世界模型/策略训练缓存**（`STABLEWM_HOME`）：官方数据集 `cube_single_expert.h5` 95G（**政策保护，在用**）、L5/v6 数据集、`checkpoints/` 各代权重 | 状态空间主干/四头/L4/L5 训练 |

## 二、运行时/系统（Hermes 与桌面，保留）

| 路径 | 大小 | 是什么 |
|---|---|---|
| `.hermes/` | 8.0G | Hermes 本体 + `tools/`(python/ffmpeg/chromium/node/uv 运行时) + `state.db`(会话库) + `backups/` |
| `.cache/` | 9.5G | 主要 `huggingface/hub`（离线权重缓存，删了要重下）+ pip/Lark 缓存 |
| `.config/` | 5.6G | 应用配置；大头 `LarkShell/aha` 4.4G = **飞书客户端本地数据**（没动） |
| `snap/` | 4.9G | snap 应用数据（chromium 4.4G 是浏览器 profile） |
| `.local/` `.vscode/` `.npm/` `.android/` `.dotnet/` `.nv/` `.pki/` `.ssh/` `.gnupg/` `.vnc/` `.xwechat/` `.bytertc/` `.copilot/` | <400M 各 | 编辑器/工具链/密钥/客户端配置（保留） |

## 三、数据与状态

| 路径 | 大小 | 是什么 | 保留策略 |
|---|---|---|---|
| `zmax_ss_remote/` | 3.0G | Orin 状态流按日 dump `state_YYYYMMDD.jsonl`(+ `.1`/`.gz` 轮转) | 只留最近 3 天；守护只读当天 |
| `zmax/outputs/`、`zmax/reports/` | — | 训练/评测/取证输出 + 清理台账 | 台账保留；大图/视频在 `reports/`（gitignore） |
| `zmax_data/release_check_*`、`demo_*`、`sim2real_*` | 数 G | 交付/演示/仿真→真机产物 | 按需归档 |

## 四、备份与镜像

| 路径 | 大小 | 是什么 |
|---|---|---|
| `hermes-backup-2026-09-26-111326.zip` | 601M | Hermes 备份（09-26）；`.hermes/backups/pre-update-2026-09-26-111515.zip` 是同日另一份，**两者都要还是留一份需定** |
| `zmax_replica_T1.tar.zst` + `.sha256` | 391M | T1 机器整套复制件（`system-replication-twin` 流程产物） |
| `zmax_replica_code.tar.gz` | 4.2M | 复制件里的代码包 |

## 五、个人文件（我自己不动）

`Downloads/` 488M（协议/PPT/PDF）· `Documents/` 274M · `Pictures/` 47M · `Desktop/` 20K · `ff_profile/` 4.9M（火狐 profile）· `nvme-gpt-backup.bak` 20K（分区表备份）· `bin/`（`dual_screen_setup.sh`/`orin_lan_setup.sh`）

## 六、本轮（09-29）动过的

**整合**（旧路径全部留软链，实测可用）：根目录 10 个散落脚本 → `zmax/tools/oneoff/`；`zmax_aoi` → `zmax/tools/aoi`；`aoi_v4` → `zmax_data/aoi_v4`；`dl_intact` → `zmax/tools/oneoff/dl_intact`；`state3d_app` → `zmax/tools/web/state3d_app`；`l4_ab` → `zmax_data/l4_ab`；`pkg` → `zmax_data/pkgs`；`android-sdk` → `zmax_data/toolchains/android-sdk`；`netplan_backup_*`/`lan_check_*`/`safety-backup`/`l4_snapshots` → `zmax_data/backups/`；`DUAL_SCREEN_FIX_20260915.md` → `zmax/docs/notes/`

**删除**（台账：`reports/disk_cleanup_ledger_20260929.json` + `reports/root_declutter_ledger_20260929.json`）：旧代 ckpt（unified_v7~v15、v6d1~d8、v6lora_30、v6r3 与各目录中间轮，最后一轮全保留）= 4G；嵌套重复目录 324M；零引用数据集 v5_sub25k/l5_new_sub12k/l5_gen_v6_probe 1.6G；l5_gen_v4.h5 12G（被 v6 取代）；旧天状态流 4G；`zmax_train` 工作树 7.4G（**原料 npz 已搬到** `zmax_data/raw_parts/v6_disturb/`，附重建命令）；`intact_pkgs` 301M；库内测试 venv 259M；包缓存 ~700M；08 月 hermes 备份 1.3G。

## 七、仍待老倪一句话的

1. `lerobot-smolvla-lew` **53G**：mac-hw 树（领先 main 536 提交 + 9 个未提交改动），训练容器还挂在它上面 —— 要不要搬到 `zmax/.worktrees/mac-hw`（顶层少一个 53G 目录）？
2. `stable-wm-cache` **134G**：其中 `cube_single_expert.h5` **95G** 是政策保护的官方数据集；剩下的 L5/v6 代数据集共约 30G 可逐代清（要按引用逐个确认）。
3. 仓库里有 3 个 >5M 文件**已入库**（`models/hjepa_zflow_model.pt`、`yolov8s.pt`、`docs/自主系统X.pptx`），违反"大文件不进代码库"——要不要做一次 git 历史瘦身（需要 force-push）？
4. `.config/LarkShell/aha` 4.4G（飞书本地数据）、`snap/chromium` 4.4G（浏览器 profile）：动它们会影响客户端，建议不动。
