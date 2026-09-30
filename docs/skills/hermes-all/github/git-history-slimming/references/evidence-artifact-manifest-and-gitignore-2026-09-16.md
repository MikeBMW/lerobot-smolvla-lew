# 证据产物入库: manifest + .gitignore, 别让 `git add <dir>/` 一次吞上千个文件 (2026-09-16 实测)

场景: 一轮实验做完要「保存数据」(关机前收尾), `reports/` 下积了几百个产物: 演示 mp4、见证 png、A/B 结果 json。
直接 `git add reports/` 的后果与正解:

## 坑 1: `git status` 把未跟踪**目录**折叠成一行 → 你以为是 20 个文件, 其实 1862 个
`?? reports/evidence_ab10_f0_r1/` 这样一行 = 该目录下全部文件。实测一次 `git add reports/` 提交了
**1862 files / 34 万行插入**, 其中还有 4.8MB 的 json。**先 `git status --short | wc -l` 看条数,
再 `git ls-files --others --exclude-standard <dir> | wc -l` 看真实文件数**。

## 坑 2: 项目的 .gitignore 只盖顶层, 嵌套媒体全漏
`reports/*.mp4` 命中顶层, 但 `reports/evidence_l4/xxx.mp4` 照样是 untracked → 每次 `git status` 刷屏,
一疏忽就被 add 进去。补齐递归规则:
```
reports/**/*.mp4
reports/**/*.avi
reports/**/*.zip
reports/**/*.tar.gz
```

## 正解: 大文件只留「清单」, 小文件才入库
1. 补 .gitignore (上一条)。
2. **扫盘生成留档清单**(不看 git 状态, 直接 walk, 否则被 ignore 的看不见):
   ```python
   import os, datetime
   big = [(p, os.path.getsize(p)) for r,_,fs in os.walk("reports") for f in fs
          for p in [os.path.join(r,f)] if os.path.getsize(p) > 1_000_000]
   ```
   写成 `reports/EVIDENCE_MANIFEST_<date>.md`: 时间戳 + 大文件(路径/体积/合计 GB) + 小文件列表 +
   一句"需要交付时另行上传数据服务器/网盘"。这样**删了也不失忆, 库也不膨胀**。
3. 只 add 小文件 + 清单 + .gitignore; 提交后用
   `git show --shortstat HEAD` / `git diff-tree --no-commit-id --name-only -r HEAD | xargs du -ch | tail -1`
   **复核提交体积** (实测 29MB 可接受, 若上百 MB 立即 `git reset --soft HEAD~1` 重新选择性 add)。
4. 项目铁律(用户口径): **zip/pdf/pptx/rosbag/模型权重/训练视频一律不进代码库**, 交付件放网盘或数据服务器。

## 顺带: 关机前收尾顺序 (用户口径「保存数据 / 记忆 / 技能 / 小版本 / 推送」)
1. 数据: 上述 manifest + 选择性提交; 工作区最终 0 条未提交。
2. 技能/记忆: 跑同步脚本 (`~/.hermes/scripts/sync_hermes_to_repo.sh`) → 它自己 commit+push 技能与记忆备份。
3. 小版本: 版本号五处同步 + VERSION.md 历史行 + tag + push (直连可用时
   `git -c http.version=HTTP/1.1 -c http.postBuffer=524288000 push origin main` 即可, 无需代理)。
4. tag 校验: `git ls-remote --tags origin | grep vX.Y.Z` 必须有回显才算推成功。
5. 停服务再关机: systemd 用户单元 `systemctl --user stop <unit>` → 后台守护 `pkill -f "[x]xx"` →
   复核无相关 python 进程 + `sync` 刷盘。
