# /home/ubuntu 顶层地图（每个东西是干什么的）

老倪 2026-09-29: 「/home/ubuntu 下的文件好多都不知道是干什么的，整合，没用的都删掉」。
本文是这个目录的**说明书**：每个顶层条目是什么、谁在用、能不能删。

**当前状态（2026-09-30 第三轮整理后）**：顶层 **60 条** = **12 条在役软链 + 39 个目录 + 点文件**；顶层已**没有裸脚本/裸文件**（`find -maxdepth 1 -type f -not -name '.*'` 为空）。磁盘 **281G / 396G（75%）**，红线 300G 以内。
设计原则一句话：**根上只留「工程 `zmax/` + 数据盘 `zmax_data/` + 标准家目录/点文件」**，其余一律归位并留软链兼容；软链只留**还有在役引用**的。

## 一、工程与数据（两个主角）

| 路径 | 大小 | 是什么 | 谁在用 |
|---|---|---|---|
| `zmax/` | 1.6G | ★ **唯一工程根**，独立 git 仓库（origin `MikeBMW/zmax`，public，main）：代码 `src/`、工具 `tools/`、DDS `dds/`、画布 `flows/`、配置 `configs/`、技能镜像 `docs/skills/hermes-all/`、记忆 `docs/memory/` | 所有 systemd 服务、cron、控制台、训练脚本 |
| `zmax_data/` | 168G | ★ **数据盘**（`ZMAX_DATA`）：`models/`(模型默认下载根) `hf_cache/`(HF 缓存默认根) `stable-wm-cache/`(数据集+训练产物) `ss_live/`(Orin 状态流) `runtime/` `aoi_v4/` `backups/` `secrets/`(600) `dataspace/` `real_cam/` … | 训练/推理/AOI/网页/服务 |
| `lerobot-smolvla-lew/` | 37G | **mac-hw 分支工作树**（另一仓库的历史分支，领先 main），训练容器挂载点 | 历史分支/训练容器 ★待定去留 |
| `INTACT-JEPA/` | 11G | INTACT 官方仓库（论文权重 `checkpoints-paper/`、`checkpoints_hf/`） | L4 直驱/官方评测 |
| `lerobot-venv/` `dds-venv/` | 7.9G / 62M | py3.12（cron `auto_loop`）/ DDS 专用 venv | cron + `zmax-dds-*` 服务（**在用，勿删**） |
| `zmax/gui-venv311` | — | 控制台 GUI 的 venv（在仓库目录内，已 gitignore） | `zmax-studio.service` |

## 二、在役兼容软链（12 条 · 每条都有真调用，别当垃圾删）

判据 = 目标路径被**服务单元 / 活代码 / 巡检脚本**真引用（不是注释、不是历史文档）；无引用的已在 09-30 第三轮清掉。

| 软链 | 指向 | 在役引用证据 |
|---|---|---|
| `zmax_rel` | `zmax` | 活进程按此路径起（`.../zmax_rel/gui-venv311/...`）+ 旧工程根名 |
| `zmax_dds` | `zmax/dds` | `zmax-dds-pub.service` |
| `stable-wm-cache` | `zmax_data/stable-wm-cache` | `studio.py` / `simulink_module.py` / `dds_hw.py` / `dataset_viewer.py` / `l5_plan_and_gen.py` / `intact_robot_panel.py`（`STABLEWM_HOME` 老路径） |
| `zmax_ss_remote` | `zmax_data/ss_live` | `ss-bypass` / `ss-remote-tap` / `ss-yolo-bypass` 三单元 + 4 个源码 |
| `zmax_moveit_plan` | `zmax_data/runtime/moveit_plan` | `zmax-moveit-plan-req.service` |
| `aoi_v4` | `zmax_data/aoi_v4` | `zmax-agent-hub.service`（`--dir .../aoi_v4/deliver`） |
| `yolov8s.pt` | `zmax_data/models/weights/yolov8s.pt` | `gui/yolo_perception.py` / `gui/simulink_module.py` |
| `state3d_app` | `zmax/tools/web/state3d_app` | `gui/studio.py` |
| `zmax_aoi` | `zmax/tools/aoi` | `.hermes/scripts/aoi_watch.sh`（巡检） |
| `l4_ab` | `zmax_data/l4_ab` | `.hermes/scripts/disk_redline.sh` + `v6_judge_watch.py` |
| `android-sdk` | `zmax_data/toolchains/android-sdk` | `tools/app/*/build_*_apk.sh` |
| `dl_intact` | `zmax/tools/oneoff/dl_intact` | `tools/oneoff/dl_aria.sh` / `dl_intact_datasets.sh` |

另: `.cache/huggingface` → `zmax_data/hf_cache`（不在顶层，但同属兼容层: 让 `HF_HOME` 不设也能命中数据盘）。

## 三、运行时 / 系统（Hermes 与桌面，保留）

| 路径 | 大小 | 是什么 |
|---|---|---|
| `.hermes/` | 7.5G | Hermes 本体 + `tools/`(python/ffmpeg/chromium/node/uv) + `state.db`(会话库 1.4G) + `skills/` + `cron/` |
| `.cache/` | 173M(+HF 走软链) | pip/Lark/字体等缓存（HF 已并入 `zmax_data/hf_cache`） |
| `.config/` | 5.7G | 应用配置；大头 `LarkShell/aha` 5.3G = **飞书客户端本地数据**（没动） |
| `snap/` | 4.8G | snap 应用数据（chromium profile） |
| `.local/` `.vscode/` `.npm/` `.android/` `.dotnet/` `.nv/` `.pki/` `.ssh/` `.gnupg/` `.vnc/` `.xwechat/` `.bytertc/` `.copilot/` | <400M 各 | 编辑器/工具链/密钥/客户端配置（保留） |

## 四、备份与个人文件

| 路径 | 大小 | 是什么 |
|---|---|---|
| `zmax_data/backups/` | ~1.1G | `hermes-backup-2026-09-26-111326.zip`(601M) + `hermes/pre-update-2026-09-26-111515.zip`(629M) + `zmax_replica_T1.tar.zst`+`.sha256`(391M) + `zmax_replica_code.tar.gz`(4.2M) —— 09-30 从根上归位 |
| `Downloads/` `Documents/` `Pictures/` `Desktop/` `Videos/` `Templates/` `ff_profile/` `bin/` | 1.6G 合计 | 老倪个人文件/桌面脚本/浏览器 profile（**我不动**）；`bin/` 两个运维脚本（`dual_screen_setup.sh` `orin_lan_setup.sh`）；`Desktop/` 三个 .desktop（Hermes / XSpace-Studio + 一个 `.bak_preworktree`） |
| `hermes-install/` | 4K | **Hermes 安装/恢复对**（09-30 归文件夹）: `安装Hermes.desktop` + `hermes-restore.sh`（→ `zmax/tools/oneoff/hermes-restore.sh`）；desktop 的 `Exec` 用 `$(dirname %k)` 取同目录脚本 ⇒ **两个文件必须同目录**，所以整对放这里，双击这个 .desktop 即可装 |

## 五、整理记录

### 09-29 第一轮
**整合（旧路径全留软链）**：根目录 10 个散落脚本 → `zmax/tools/oneoff/`；`zmax_aoi` → `zmax/tools/aoi`；`aoi_v4` → `zmax_data/aoi_v4`；`dl_intact` → `tools/oneoff/dl_intact`；`state3d_app` → `tools/web/state3d_app`；`l4_ab` → `zmax_data/l4_ab`；`pkg` → `zmax_data/pkgs`；`android-sdk` → `zmax_data/toolchains/`；`netplan_backup_*`/`lan_check_*`/`safety-backup`/`l4_snapshots` → `zmax_data/backups/`。
**删除**（台账 `reports/disk_cleanup_ledger_20260929.json` + `root_declutter_ledger_20260929.json`）：旧代 ckpt 4G、嵌套重复目录 324M、零引用数据集 1.6G、`l5_gen_v4.h5` 12G、旧天状态流 4G、`zmax_train` 工作树 7.4G（原料 npz 已搬 `zmax_data/raw_parts/v6_disturb/`）、`intact_pkgs` 301M、库内测试 venv 259M、包缓存 ~700M、08 月 hermes 备份 1.3G。

### 09-30 第二轮（工程仓库化 + 根目录收尾）
**工程收敛**：`/home/ubuntu/zmax` 变独立 git 仓库（origin `MikeBMW/zmax`），代码里绝对路径统一到 `/home/ubuntu/zmax`；新建 `tools/ns_unify_paths.py`、`repo_guard.py`、`secret_scan.py`、`zmax_bootstrap.{py,sh}` + `zmax_assets.json`。
**根目录收尾**：`stable-wm-cache`(136G)→`zmax_data/`（软链）；`zmax_ss_remote`→`zmax_data/ss_live`；`zmax_moveit_plan`→`zmax_data/runtime/`；`.cache/huggingface`(9.5G)→`zmax_data/hf_cache`（软链回）；`aoi_v4`→`zmax_data/aoi_v4`（软链回）；4 个备份压缩包 → `zmax_data/backups/`；`yolov8s.pt`、分区表备份、`安装Hermes.desktop` 归位；空目录 `zmax_state_space` 删除；`.hermes` 缓存/旧日志清理。
**清理记录**：`reports/declutter_ledger_20260930.json`；仓库入库体积 45MB（守卫 `tools/repo_guard.py` 逐次核）。

### 09-30 第三轮（顶层裸脚本清理 · 老倪: 「怎么有那么多 sh 脚本和 py 文件」）
**根因**：09-29 把散落脚本收进仓库时按"只搬不删"在**根上留了软链**，但单元/cron/代码随后都改指仓库真路径了 ⇒ 那批软链**已经没人调用**，在文件管理器里却仍显示成一堆 `*.sh` / `*.py`（看着乱，实为死链）。
**清掉 22 条死链**（逐条判过"有没有真调用"）: 10 个 oneoff 脚本链（`chain_v2.sh` `dl_aria.sh` `dl_dog.sh` `dl_intact_datasets.sh` `gate_watch.sh` `gw_fix.sh` `gw_restart.sh` `prep_reacher.sh` `run_official_eval.sh` `hermes-restore.sh`）· 5 个 DDS/上传链（`zmax_dds_{publisher,aggregator,ss_daemon,ss_verify}.py` `zmax_hw_uploader.py`，单元早已执行 `zmax/tools/dds/*` 与 `zmax/tools/hw_uploader.py`）· 6 条备份/杂链（`l4_snapshots` `lan_check_20260920` `netplan_backup_20260920_1657` `nvme-gpt-backup.bak` `safety-backup` `pkg`）· `安装Hermes.desktop`。**目标文件一件没删**（仓库/数据盘里都在）。
**顺带修的真引用**：`tools/oneoff/prep_reacher.sh` 里 `bash /home/ubuntu/run_official_eval.sh` → 仓库路径（否则删链会断这条链）。
**归文件夹（有用的）**：Hermes 安装/恢复对 → `~/hermes-install/`（两者必须同目录，`Exec` 用 `$(dirname %k)`）；10 个 oneoff 脚本的**真身**本就在 `zmax/tools/oneoff/`，5 个 DDS/上传脚本真身在 `zmax/tools/dds/` 与 `zmax/tools/`。
**台账**：`zmax_data/artifacts_20260930/tidy_ledger_20260930.json`（含每条原指向）。验证: 顶层裸文件 **0**、DDS 三单元仍 active、`systemctl --failed` **0**。

## 六、仍待老倪一句话的

1. **公开仓库历史里的 agent hub token**：代码/单元已出库改成 secrets 文件，但**历史提交里清不掉**（force-push 后旧对象仍可按 SHA 取）。三选一：① 删库重建 ② 轮换 token（要同步工控机部署件）③ 维持现状。
2. `lerobot-smolvla-lew` **37G**：mac-hw 树（领先 main），训练容器还挂着 —— 搬到 `zmax/.worktrees/mac-hw` 能让顶层少一个 37G 目录（需改容器挂载）。
3. `zmax_data/stable-wm-cache/datasets` 里除政策保护的 `cube_single_expert.h5`(95G) 外，历史代数据集（v5/v6 系列约 30G）可逐代清 —— 要按引用逐个确认后再动。
4. `.config/LarkShell` 5.3G（飞书数据）、`snap` 4.8G（chromium profile）、`Downloads` 1.2G：动它们会影响客户端或属于个人文件，**建议不动**，要清你说一声。
