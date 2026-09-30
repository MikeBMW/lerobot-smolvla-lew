# 并行线共存的发版与归档 (6 真源 / worktree 隔离 / 真源漂移) — 2026-09-26 实测

场景: 同一个仓库(同一台机器、甚至同一个检出目录)上跑着**两条线** —— 主线 (GUI/引擎/采集) 与
并行线 (APP/DDS 硬件监控, 每 2 分钟自动 commit 一条 `chore(hw)`)。发版时踩到 4 个真坑, 全部可复现。

## 坑① 并行线发版只改 studio.py → 6 处真源漂移
`tools/bump_version.py --to X.Y.Z --summary-file <f>` **先 `--dry`**。期望 6 处全 ✅:
```
studio.py 品牌 QLabel · studio.py 窗口标题×2 · studio.py changelog 行
update_checker.CURRENT_VERSION · version_sync.zmax_ver(不带 v) · docs_sync{version,zmax_version} + VERSION.md 表首插行
```
实测症状: dry-run 里 `update_checker / version_sync / docs_sync` 报 **"新命中 0"** —— 因为并行线
发布提交只动了 studio.py 的版本号, 那 3 处还停在上一版。若不做 dry-run 直接发, 结果就是
**版本号三处不一致 + 更新检测失效 + 下次发版跳号**。
修法: 手工 `sed` 补齐那 3 处后提交, 并在 VERSION.md 里**补记并行线那一版**(标注来源与"其发布只改了
studio.py"), 保持版本历史连续、诚实。

## 坑② VERSION.md 被别人的"文档迁移"删掉
症状: `bump_version.py` 报 `FileNotFoundError: <repo>/VERSION.md`。
排查: `git ls-tree HEAD | grep -i version` → 只剩 `docs/VERSION.md`(那是**另一份老的产品版本文档**, 别拿它顶替)。
修法: `git checkout <含该版本的提交> -- VERSION.md` 从历史恢复, 再发版; 顺手在交接单写明。

## 坑③ 共享检出目录被切到别的分支 (最危险)
症状: `git branch -vv` 显示当前目录停在并行线的分支; 结果 ——
- `tools/gui/studio.py` 是**旧版本**(实测 v5.6.0, 而 main 上已是 v5.14.0+);
- 新工具 / 画布 JSON / 新模块**全不在磁盘**;
- 引用这些文件的 systemd 服务**进程还在跑(内存里), 但 `systemctl restart` 必挂**。
修法(不动别人的检出):
```bash
git worktree add /home/ubuntu/zmax_rel main     # main 线独立检出, 本次发布/归档都在这里做
# 归档/发版脚本里的 REPO 一律指 worktree; 不要在并行线的检出里 checkout / commit
```
纪律: **一个 agent 线 = 一个 worktree**。提交前先 `git branch --show-current` 自证在正确的线上。

## 坑④ push 被并行线抢推 → rebase 即可
`git push` 返回 non-fast-forward。`git fetch && git rebase origin/main` 后重推;
两线改的文件通常不重叠(本次冲突面 0)。**别 force push**(会把并行线的提交打掉)。

## 归档 (保存数据) 的标准动作
1. 复制上一版 `archive_release_*.sh` → 改版本号 + **源目录改成 worktree**;
2. 内容 = 本轮新工具/新源码/文档(VERSION.md + 交接单 + 台账)/证据 JSON+MD/**活数据**(只存在于别的检出的审计 jsonl);
3. `MANIFEST.md` + `sha256sums.txt`, 交付前 `sha256sum -c sha256sums.txt | grep -c OK`;
4. ⚠️ **别把大快照塞进归档**: 本次误收 `muscle_memory.json`(6.3MB × 30 份) → 归档 200M; 剔除后 5MB。
   口径保持"只放真产物小文件", 归档应是 ~5MB 量级。

## 交接单 (关机前留档) 必须包含的四件事
① 本次完成项 + 证据路径 ② **在跑什么**(任务/ETA/是否落 ckpt —— 例如 `save_freq > steps` 的训练中途关机全丢)
③ 待现场/待授权清单 ④ 下次开工顺序 (+ 检出目录状态这类"环境事实")。

## 顺带修掉的真 bug (同类常见)
`~/.hermes/scripts/chain_health.py` 每 30 分钟报 `error`: 判定行 `v.startswith("FAIL")` 遇到上游
`null` 字段 (`/api/relay/orin/status` 的 `model`) 抛 `AttributeError`。
修法: `str(v or "")` 兜底 + **值型键(ts/disk/model 名)不参与状态判定**。教训: 守护脚本自己挂了
比被守护对象挂了更危险 —— 交接巡检时逐个 `cronjob list` 看 `last_status`。

## 技能/记忆同步脚本的位置纪律
`tools/sync_hermes_to_repo.sh` 用 `REPO_ROOT=$(dirname $0)/..` 自定位 → **必须在仓库内执行**;
拷到 `/tmp` 跑会 `mkdir: cannot create directory '//docs': Permission denied`。
发版后跑它, 让新技能/记忆落在**本线**的 main 上 (而不是并行线的分支)。
