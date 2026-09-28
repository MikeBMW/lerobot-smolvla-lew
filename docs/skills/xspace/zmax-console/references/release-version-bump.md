# Z-MAX 版本迭代 / 发布归档 (bump_version.py)

适用: 用户说「小版本迭代」「推进版本」「发布」「保存数据+推代码」时。

## 步骤 (按序, 不要跳)

1. 写摘要文件 `/tmp/v.txt` (中文摘要, 一段一段写清本批次改了什么/根因/实测值)。
2. **先 dry 跑**: `gui-venv311/bin/python tools/bump_version.py --to X.Y.Z --summary-file /tmp/v.txt --dry`
3. 逐行读 dry 输出。**每一行都必须 旧命中 ≥1 且 新命中 ≥1**。任何 ❌ / `旧命中 0` / `新命中 0`
   = 该处历史漏同步或工具正则不认 —— **先手工把那处改对再重跑 dry**, 不要带病写盘 (会静默漏一处,
   面板/窗口标题/校验各说各话)。
4. 去掉 `--dry` 写盘。同步点共 8 处 (工具自动改, 但要知道是哪些):
   studio 品牌 QLabel · studio 两处窗口标题 · studio changelog 注释行 · update_checker.CURRENT_VERSION ·
   docs_sync 的 `"version"` + `"zmax_version"` 两键 · version_sync.`zmax_ver` ·
   `tools/ci/integrity_check.py` 的 `EXPECTED_VERSION` · `VERSION.md` 表首插一行。
5. 校验: `gui-venv311/bin/python tools/ci/integrity_check.py` → 必须打印「版本号/功能卡/页面字典/导航/类 五处一致」。
6. 重启控制台 (GUI 改动必须重启才生效) 并**读窗口标题里的版本号**确认换版成功。
7. 提交: 长中文消息写文件 + `git commit -F <file>`; 然后 push。
8. **小版本**默认只 commit+push, **不打 tag**; tag 会触发 Windows/macOS 桌面包 CI (`build-win-exe.yml` 的 `on: push: tags: v*`),
   要出包时才 `git tag vX.Y.Z`。
9. **中版本 (X.Y.0) 按先例必须打 tag** (v5.14.0 / v5.15.0 都是带注释 tag):
   commit subject 用 `release: 中版本迭代 vX.Y.0 — <三五个关键词>`;
   然后 `git tag -f -a vX.Y.0 -m "中版本迭代 vX.Y.0 — <摘要>"` → `git push origin main` → `git push origin vX.Y.0`;
   复核 `git ls-remote --tags origin | grep vX.Y.0`(应看到 tag 对象 + `^{}` 指向的 commit) 与 `git log -1 origin/main`。
   打 tag 就意味着默认接受桌面包 CI 跑一轮 —— 报给用户时写"tag 已推, 出包 CI 会跑"。

## 坑 (每条都实际撞过)

- `AssertionError: 找不到 changelog 锚点 (# vX.Y.Z …)` = **上一个版本只改了版本号, 没插 changelog 注释行**。
  不要改工具绕过、也不要直接改版本号了事: 把缺失的那行按既有格式补在旧版本行**之前**
  (`# vX.Y.Z: <摘要>`), 内容取该发布 commit 的 subject, 再重跑 bump。锚点不补, 下次 bump 还会崩。
- 每次 bump 前先看 studio.py 里 changelog 的**最新一行版本号是否等于当前已发布版本号**; 不等就是有漏。
- 其它文件可能停在更老的版本 (实测 update_checker / version_sync / docs_sync / integrity_check 停在
  好几版之前)。处理方式: 先把它们改成**当前已发布版本号**, 再跑 bump 统一前进。
- 格式不一致: `version_sync.zmax_ver` 的值**不带 v 前缀**, 其余各处带 v (窗口标题/update_checker/docs_sync/
  integrity_check 的 EXPECTED_VERSION)。按各自格式改, 别一把 sed。
- 摘要里有引号/换行时: 用 `-F 文件` 提交; shell 里 `-m "…\"…\""` 会被引号截断 (报
  `pathspec '…' did not match any file`)。

## 「保存数据」= 现场批次归档 (用户口径: 验收后 保存数据+更新代码+共享技能)

放 `~/zmax_data/release_archive/vX.Y.Z_<YYYYMMDD>/`, **不进 git** (大文件/原始产物按 Git 精简纪律走数据盘):

```
logs/      现场执行器与安全层日志 (l2_daemon / vl_safety_monitor / vl_safety_fast / studio 启动日志)
state/     当时的真源快照 (裁决 JSON / 意图 / 授权与审计 / 相关 state.json)
evidence/  事故窗口的原始帧 (只取窗口内, 不整目录搬)
src/       本批次改动源码副本 (与 git 提交同源, 便于离线核对)
MANIFEST.sha256   cd 到归档根后 `find . -type f | sort | xargs sha256sum`
README.txt        主题 / 目录说明 / **逐字关键证据**(带时刻的原文行: 拒发原因、下发时刻、实测耗时)
```

README 里写「实测值 + 时刻」而不是叙述过程 —— 用户认证据、也复看每一行。

顺序: **先 bump 写盘 + integrity_check → 再归档**(这样 `src/*.diff` 能同时存下已提交与未提交两份:
`git diff <上一发布 commit>..HEAD` 与 `git diff <上一发布 commit>`), **最后 commit/tag/push** ——
归档里的 README 就写得出"本批 commit/tag"。
归档脚本可照 `archive_batch.sh` 的目录结构直接改; 归档**不进 git**, `MANIFEST.sha256` 用
`cd 归档根 && find . -type f ! -name MANIFEST.sha256 | sort | xargs sha256sum`。
