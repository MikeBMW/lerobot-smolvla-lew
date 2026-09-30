# Hermes 本体升级 — 逐步配方与判据

适用：源码安装（`Install method: git`）的 Hermes 自我升级。目标：一次跑通、可回滚、可验证。

## 0. 先认清安装形态

```bash
hermes --version          # 版本 / upstream sha / Install directory / Install method
type -a hermes            # 入口（wrapper ~/.local/bin/hermes → <install>/venv/bin/python <install>/hermes）
```
新版会用**隔离的 staged runtime venv**（`~/.hermes/installs/<hash>/environments/<hash>/venv`），
`hermes doctor` 会写 `Runtime venv staged (...)(active in this process)`。
⇒ 升级后不要再假定某一个固定 venv 路径就是运行环境，以 `hermes doctor` 的输出为准。

## 1. 只读预演

```bash
hermes update --plan
```
输出里要确认三件：安装方式、涉及的 profile、**要被重启的服务**。gateway 在列表里 = 本次升级会断当前会话。

## 2. 动手前检查

```bash
git -C ~/.hermes/hermes-agent status --porcelain      # 必须为空（非空会被 stash）
git -C ~/.hermes/hermes-agent config --get-regexp '^url\.'   # 看有没有 mirror insteadof
```

## 3. 取上游（镜像代理下）

镜像探活（快）：
```bash
for m in <m1> <m2> <m3>; do printf '%s ' "$m"; \
  curl -s -o /dev/null -w '%{http_code}\n' "$m/<owner>/<repo>/info/refs?service=git-upload-pack"; done
```
用返回 200 的镜像（repo 级配置）：
```bash
git -C ~/.hermes/hermes-agent config --local url."<mirror>/https://github.com/".insteadof "https://github.com/"
```
对账「本地 vs 上游真实差距」（api.github.com 通常直连可达，是最可靠的对照源）：
```bash
curl -s https://api.github.com/repos/<owner>/<repo>/commits/main   # 上游最新 sha/时间
```
抓取：
```bash
git -c http.sslVerify=false fetch     --depth=1 origin main    # 绕镜像的陈旧 pack 缓存
git log --oneline HEAD..origin/main | wc -l                    # 落后提交数
```
⚠️ 浅取会让历史变 grafted，`git diff HEAD..origin/main --stat` 会显示海量文件 —— 那是浅边界造成的，
不是真实变更量。要看真实变更按提交数/关键文件看。

## 4. 执行升级

```bash
setsid hermes update --backup --yes > /tmp/hermes_update.log 2>&1 &
tail -f /tmp/hermes_update.log
```
日志里的健康信号：`Pre-update snapshot: ...` → `Pre-update backup: ...zip`（记下回滚点）→
`Found N new commit(s)` → `Updating Python dependencies` → `Config format updated (vX → vY)` →
`Update complete! (旧 → 新)` → `Syncing bundled skills to all profiles`。
`Fast-forward not possible (history diverged), resetting to match remote` 是正常分支，不是错误。

## 5. 升级后核对

```bash
hermes --version                  # 版本与 upstream sha 是否变新
hermes doctor                     # Config version up to date / runtime venv staged / 无安全公告
```
回滚点：`~/.hermes/backups/pre-update-*.zip`，还原用 `hermes import <zip>`。
可选：`hermes sessions optimize-storage`（gateway 重启后再跑）。

## 6. 生效与收尾

- 新代码**要 gateway 重启才生效**；update 会先 drain（可能等到 ~30 分钟才强制重启，日志显示剩余秒数）。
- gateway 不能从自身进程内重启 ⇒ 要提前生效就在**进程外**终端执行，并提前告知用户会话会断。

## 判据速查

| 现象 | 含义 | 动作 |
|---|---|---|
| `unable to access '<mirror>/...'` 403 | 镜像已死 | 探活换 200 的镜像 |
| ls-remote 新、fetch 后 origin/main 旧 | 镜像 pack 缓存陈旧 | `git fetch --depth=1 origin main` |
| `-c` 覆盖镜像规则后仍 403 | 改写键名写错，覆盖未生效 | 键名必须与 `git config --get-regexp '^url\.'` 输出一字不差 |
| 升级中途中断 | update 与 gateway 同进程树 | 用 `setsid` 分离运行 |
| 升级完行为没变 | 未重启 gateway | 进程外重启 |
| doctor 报 `Could not validate model/provider config` | 配置校验器对新格式的一处解析告警 | 功能实测可用则不阻塞；记下待上游修 |
