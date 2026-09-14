# 容器重建后恢复流程 (2026-08-18 实测)

**触发**: Docker Desktop 引擎故障 → 容器重建 → `/root/lerobot-smolvla-lew` 仓库丢失。
`.hermes` 卷持久: 记忆/技能/.env 凭据都在。仓库在容器可写层, 不持久。

## 恢复步骤

1. **clone 大仓库** (605MB, 5-10 分钟):
   ```bash
   cd /root && git clone --depth 50 https://github.com/MikeBMW/lerobot-smolvla-lew.git
   ```
   用 background=true + notify_on_complete, 别干等。clone 失败会留残缺 .git (branch master 无 commit) → `rm -rf` 重来。

2. **重建 git 配置** (容器重建后全丢):
   ```bash
   git config --global user.name "MikeNi"
   git config --global user.email "mikeni@zmax.local"
   git config --global credential.helper store
   TOKEN=$(grep -oP '(?<=^GITHUB_TOKEN=).*' /root/.hermes/.env | head -1)
   printf 'https://MikeBMW:%s@github.com\n' "$TOKEN" > /root/.git-credentials
   chmod 600 /root/.git-credentials
   ```
   token 在 `~/.hermes/.env` 的 `GITHUB_TOKEN=` (40 字符)。

3. **小版本迭代** (技能主线流程):
   - 版本号 **6 处**: studio.py 窗口标题(~9584)+侧栏(~564) / update_checker.py CURRENT_VERSION / docs_sync.py version+zmax_version(~193,197) / integrity_check.py EXPECTED_VERSION
   - `python3 tools/ci/integrity_check.py` 通过才 commit
   - commit → push main → tag → push tag → 建 Release (gh 未装, 用 REST):
     `curl -s -X POST -H "Authorization: token $TOKEN" -H "Accept: application/vnd.github+json" https://api.github.com/repos/MikeBMW/lerobot-smolvla-lew/releases -d '{"tag_name":"vX.Y.Z","name":"Z-MAX vX.Y.Z","body":"..."}'`

## 坑 (2026-08-18 实测)

- **tag 误建**: `git commit | tail -1` 管道掩盖 commit 失败 (退出码是 tail 的 0), `&& git tag vX` 仍执行 → tag 指向旧 HEAD。修复: `git tag -d vX && git tag vX && git push origin vX --force`。
- **git config 写不进**: rm -rf 删掉了 shell 当前 cwd → getcwd 失败, 后续命令全挂。修复: 用 terminal 的 workdir 参数换目录 (/tmp) 执行。
- **push 卡死**: 用 `git -c http.version=HTTP/1.1 -c http.postBuffer=524288000 push origin main`。
- **管道掩盖退出码**: `cmd | tail -1; echo RC=$?` 拿到的是 tail 的 RC。要拿真实 RC 用 `cmd 2>&1 | tail -1; echo RC=${PIPESTATUS[0]}` 或不用管道。
