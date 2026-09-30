---
name: zmax-engineering-repo
description: "Use when 整合/推送 Z-MAX 工程仓库或统一代码绝对路径。"
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [git, repo, path-namespace, zmax, github, housekeeping]
    related_skills: [git-history-slimming, zmax-usb-hermes-mirror, disk-redline-guard, linux-host-maintenance]
---

# Z-MAX 工程仓库 (zmax) — 工程根 / 命名空间 / 入库边界

## When to Use
- 老倪说「/home/ubuntu 太多东西/整合/没用的删掉」「工程代码放哪」「开新 github 仓库」。
- 要把代码里的绝对路径改成 `/home/ubuntu/zmax` 开头, 或怀疑改了路径后哪里断了。
- 要把技能/记忆推上 GitHub, 或仓库里混进了权重/截图/交付件。

## 基本事实 (2026-09-30 起)
- **工程根 = `/home/ubuntu/zmax`**, 它是**独立 git 仓库**, origin = `https://github.com/MikeBMW/zmax` (public, main)。
  · 旧名 `/home/ubuntu/zmax_rel`、`/home/ubuntu/zmax_dds` 仍是软链(兼容), 但代码里不该再出现。
  · `/home/ubuntu/lerobot-smolvla-lew`(分支 mac-hw)是**另一仓库里的另一棵工作树**, 内容与 main 有差异。
- **数据全在 `/home/ubuntu/zmax_data/`**: `ss_live/`(Orin 状态流+深度源, 旧名 zmax_ss_remote)、
  `runtime/moveit_plan/`(旧名 zmax_moveit_plan)、`stable-wm-cache/`(训练缓存 136G, 含政策保护的 95G 官方数据集)、
  `backups/`、`models/weights/`。**根上只留软链**。

## 入库边界 (老倪: 只放源代码 + 技能 + 记忆)
| 进 | 不进(留本机) |
|---|---|
| `src/` `tools/` `configs/` `flows/` `scripts/` `docker/` `dds/` `ros_*_ws/` 等代码与配置 | `reports/` 运行产物(截图/状态快照, 数百 MB) |
| `docs/**` 文本(.md/.csv/小图) | 权重 `*.pt/*.h5/*.safetensors`、交付件 `pdf/pptx/zip`、视频 |
| `docs/skills/hermes-all/` 技能全量镜像 | `outputs/` `runs/` `models/` `gui-venv311/`(venv) |
| `docs/memory/` 记忆快照(MEMORY.md + USER.md, 每日 + latest) | `.github/`(fork 的上游 CI) |

- 守卫: `python3 tools/repo_guard.py` (加 `--staged` 可做 pre-commit)。判据: 权重/交付件类 >200KB 报; 二进制 >300KB 报
  (白名单 `config/moveit_*/urdf/meshes/`); 文本/代码不设上限(studio.py 1MB、uv.lock 1.1MB 正常)。
- `.gitignore` 已封 `reports/ media/ outputs/ models/ backups/ *.pt *.h5 *.pdf *.pptx *.zip ...`。

## 路径命名空间统一 (老倪: 左右脑源码打开后都以 /home/ubuntu/zmax 开头)
```bash
python3 tools/ns_unify_paths.py --dry   # 先看要改哪些、多少处
python3 tools/ns_unify_paths.py         # 真改 (改前 tar 备份: zmax_data/backups/ns_unify_pre_<日期>.tar.gz)
```
规则(写在脚本里, 别手改):
1. `/home/ubuntu/zmax_rel/...` → `/home/ubuntu/zmax/...` **恒安全**(前者本就是软链)。
2. `/home/ubuntu/zmax_dds/...` → `/home/ubuntu/zmax/dds/...`。
3. `/home/ubuntu/lerobot-smolvla-lew/...` → `/home/ubuntu/zmax/...` **仅当 zmax 下存在同一相对路径**;
   两棵工作树分支不同、内容有差异 ⇒ 缺路径的一律保留并打印出来人工看。
4. **不动** `reports/`(历史取证, 改写=篡改证据) 与 `docs/skills|docs/memory`(是 `~/.hermes` 的镜像, 要改改源)。
5. **绝不能碰** `./.git` 指针文件(worktree 时它存着 gitdir 路径)与脚本自身。

仓库外一起改(否则口径不一致): `/etc/systemd/system/*.service` + `~/.hermes/scripts/*`(改前 `.bak`),
改完 `systemctl daemon-reload`, 再逐个核 `systemctl is-active`(reload 不会重启服务)。

## 基线自检 / 首次 clone 初始化 (老倪: 首 clone 就要识别出已下载的模型和数据)
- 入口: `bash tools/zmax_bootstrap.sh [--apply|--download|--smoke|--secrets|--systemd]`
  (实现在 `tools/zmax_bootstrap.py`; 清单 `tools/zmax_assets.json`, 机器可读, 加资产只加一条)。
- **识别顺序**(已下载的绝不重下): 默认路径 → `alt_paths`(老位置) → `alt_globs`(精确文件) → HF 老缓存 `~/.cache/huggingface`。
  命中即"可用/可采纳"; `--apply` 只建软链/建目录/写 `$ZMAX_DATA/zmax_paths.env`, **只增不改不删**。
- `--smoke` = 状态空间功能自检(10 个核心模块 import + 关键文件 + 端口), 全绿 = 代码面恢复完成。
- 退出码: 必需资产齐 0 / 缺 1(可进 CI)。裸机上跑一次应当**打印出确切的下载命令**, 而不是偷偷下 100G。
- 文档口径: `docs/notes/model-paths.md`(默认路径+下载命令) / `docs/notes/restore_matrix.md`(功能→代码→资产, 四类资产)。

## 默认落盘路径约定 (模型下载默认落哪)
| 变量 | 默认 | 放什么 |
|---|---|---|
| `ZMAX_DATA` | `/home/ubuntu/zmax_data` | 所有重东西的根 |
| `ZMAX_MODELS` | `$ZMAX_DATA/models` | **模型默认下载根** |
| `ZMAX_HF_HOME` | `$ZMAX_DATA/hf_cache` | **HF 缓存默认根**(布局同 `~/.cache/huggingface`: `hub/models--…`) |
| `STABLEWM_HOME` | `$ZMAX_DATA/stable-wm-cache` | 数据集 + 训练产物 |
| `ZMAX_SECRETS` | `$ZMAX_DATA/secrets` | `zmax.env`(600, 永不入库) |

环境变量优先; `--apply` 生成 `$ZMAX_DATA/zmax_paths.env`, `source` 后全部脚本/服务同一套路径。

## 密钥出库 (公开仓库的硬红线)
- 真值只放 `$ZMAX_DATA/secrets/zmax.env`(600); 代码/单元只留 `${VAR}` 占位;
  systemd 用 `EnvironmentFile=-/home/ubuntu/zmax_data/secrets/zmax.env`。
- `python3 tools/secret_scan.py [--staged]` 扫已跟踪/暂存区(值打码输出, 命中退 1); 与 `repo_guard.py` 一起当提交前双闸。
- 已泄露的值: 上游 vendored 文档里的示例 key 不算(路径白名单 `docs/source/` `src/lerobot/`);
  **历史里的密钥清不掉**(force-push 后旧对象仍可按 SHA 取) ⇒ 要么删库重建(破坏性, 需老倪点头), 要么轮换密钥。

## 技能 + 记忆同步
- 脚本: `tools/sync_hermes_to_repo.sh` (`--no-push` 只提交)。三件事: ① zmax-console 全家 → `docs/skills/xspace/`
  ② **技能全量镜像** `~/.hermes/skills` → `docs/skills/hermes-all/`(rsync --delete + 删 >300KB 大图)
  ③ 记忆 → `docs/memory/hermes-jingjing-{memory,user}-<日期>.md` + `-latest.md`; 然后 commit + push。
- cron: Hermes job `hermes-skill-memory-sync`(每 6h) → 包装脚本 `~/.hermes/scripts/sync_hermes_to_repo.sh`
  → **必须指向工程根那份**(2026-09-30 前指向 fork 副本, 会把技能推到错仓库)。

## 验证口径 (交付前必做)
```bash
cd /home/ubuntu/zmax && git status --porcelain | wc -l      # 0
python3 tools/repo_guard.py                                  # ✅ 干净
python3 -m compileall -q tools src/lerobot/policies/left_right
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8793/station   # 200
rm -rf /tmp/c && git clone --depth 1 https://github.com/MikeBMW/zmax.git /tmp/c && ls /tmp/c   # 全新克隆核验
```

## Pitfalls
| 坑 | 症状 | 修法 |
|---|---|---|
| 把 fork 路径当同义词批量替换 | 指向 mac-hw 树里不存在的文件 / 改错内容 | 先 `os.path.exists(zmax+tail)` 判存在, 不存在保留 |
| 改写 `./.git` 指针 | git 直接坏掉(找不到 gitdir) | 脚本 SKIP_FILES 显式排除 |
| 用 `du` 统计仓库体积 | 报出来的数跟 `git ls-tree HEAD` 差几倍(块取整 + 输出被截断) | 入库体积一律 `git ls-tree -r -l HEAD` 求和 |
| 只改仓库内、忘了 systemd/Hermes 脚本 | 单元里还是旧路径, 下次改口径又漂 | 仓库外一起 sed + daemon-reload + 核验 |
| 技能镜像与仓库不一致 | `git status` 一堆 D 与 ??(docs/skills 下) | `rsync -a --delete` 重新镜像, 别只 cp |
| 大图/PDF 混进技能镜像 | 仓库体积暴涨 | 镜像后 `find -size +300k -delete` + `repo_guard.py` 兜底 |
| 把 venv 当老位置资产"采纳" | 软链过去的 venv 跑不了(内部路径写死) | bootstrap 里 venv/env 类只报"复用原处"并给重建命令, **不建软链** |
| `alt_paths` 里写了目录 | 把整个目录当资产采纳(如 lora_l3 → reports/) | 精确文件用 `alt_globs` 且 **glob 先于 alt_paths**; 取文件要 `os.path.isfile` 过滤 |
| 从 fork 收源码时连生成物一起收 | `tools/ros2_interfaces/install/**` 上千个 rosidl 生成文件入库 | 排除 `/install/`、`docs/`、`reports/`、`media/`、`.github/`; 根级脚本归 `tools/fork_experiments/` |
| 用 `du -sh` 判目录空不空 | 明明有文件却报 0 | 用 `ls -A`/`os.listdir` 判非空; du 受挂载/稀疏影响 |
