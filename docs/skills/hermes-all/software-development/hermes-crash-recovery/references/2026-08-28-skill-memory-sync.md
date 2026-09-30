# Hermes 技能+记忆 → GitHub 自动同步 (2026-08-28)

老倪指令: "技能完整同步到 GitHub; 记忆一点都不能丢, 每次都要备份"。
落地: 仓库 `lerobot-smolvla-lew` 的 `docs/skills/xspace/` + `docs/memory/` 成为
本机 `~/.hermes/` 的异地备份 (本地 + GitHub 双保险, 机器丢失/重装可恢复)。

## 组成

| 部件 | 路径 | 说明 |
|---|---|---|
| 同步脚本(真身) | `~/lerobot-smolvla-lew/tools/sync_hermes_to_repo.sh` | 镜像技能 + 备份记忆 + manifest + commit + push |
| cron 包装 | `~/.hermes/scripts/sync_hermes_to_repo.sh` | 一行 exec 调用真身 (cron 只收相对路径) |
| cron 任务 | `hermes-skill-memory-sync` | `no_agent=true`, `every 6h`, `deliver='local'` |

手动跑: `bash tools/sync_hermes_to_repo.sh` (同步+提交+推送) 或 `--no-push` (只同步+提交)。

## 同步内容

1. **zmax-console 全家** → `docs/skills/xspace/zmax-console/`
   (SKILL.md + references/ + scripts/ + templates/, ~214 文件)
2. **关键技能 ~20 个** (mlops 训练/评估/CICD + github 工作流 + devops) → `docs/skills/xspace/<name>/`
   - 体积守卫: >3MB 跳过 (防仓库膨胀)
3. **记忆备份** → `docs/memory/`
   - `hermes-jingjing-memory-{YYYY-MM-DD}.md` (每日带日期) + `-latest.md` (永远最新)
   - `hermes-jingjing-user-{YYYY-MM-DD}.md` + `-latest.md`
   - 日期文件 = 每天的记忆状态都留在 git 历史里, 删不掉
4. **manifest.json**: xspace 技能数 + last_sync 日期

## 幂等性设计 (关键)

- manifest `last_sync` 用**日期粒度** (`now[:10]`), 不用时间戳
  → 同一天重复跑 git diff 为零 → 无垃圾 commit (cron 每 6h 跑不刷屏)
- 记忆文件覆盖同名日期文件, 内容相同则无 diff
- 只有技能/记忆**真的变了**才产生 commit

## 恢复路径 (崩溃后)

```bash
git clone https://github.com/MikeBMW/lerobot-smolvla-lew.git
# 技能: docs/skills/xspace/* → ~/.hermes/skills/<category>/
# 记忆: docs/memory/hermes-jingjing-*-latest.md → 逐条 merge 进 Hermes memory
```

⚠️ 记忆恢复必须 diff 对比 (备份可能比当前环境旧), 技能可整目录覆盖, 记忆不可盲覆盖。

## ⚠️ ghproxy 大包 push 断连坑

同步 200+ 文件 → pack 变大 → ghproxy 报 `fatal: the remote end hung up unexpectedly`,
**push 静默失败**: 本地 HEAD 前进但 `origin/main` 不更新。
验证: `git rev-parse HEAD` vs `git rev-parse origin/main` 不一致 = push 没成功。

修法 (已内置脚本):
```bash
git -c http.sslVerify=false -c http.postBuffer=524288000 push origin main   # + 失败重试一次
```
手动推大改动时也要带 postBuffer。

## 教训

- cron `script=` 只收 `~/.hermes/scripts/` 下的相对文件名, 绝对路径被拒
- 技能同步与代码同步同仓库同 commit, 技能更新 = 自动进 GitHub (老倪验收流程:
  功能验收后 → 保存数据 + 更新代码 + 共享技能 commit+push)
