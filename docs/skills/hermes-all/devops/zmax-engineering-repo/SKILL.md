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
