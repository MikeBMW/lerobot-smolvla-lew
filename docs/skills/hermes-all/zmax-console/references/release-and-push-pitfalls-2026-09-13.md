# 发布到 GitHub 的两个坑 (2026-09-13 实测) — 补充/更新 `git-push-behind-gfw.md`

> 本文件补充并部分更新 `references/git-push-behind-gfw.md` (那份 08-25 写时还没有体积墙/凭证头两条)。
> 一键脚本: `scripts/push_via_ghproxy.sh` (显式认证头 → 依次试 3 个镜像 → ls-remote 核对, 成功才 exit 0)。

## 一、推送: 体积墙 + 凭证头 + 成功判据 (4 轮才通)

**症状 A**: `git push` 无任何输出, `timeout` 到点 rc=124 (ghproxy.net); 同提交在 gh-proxy.com 回 `HTTP 413`。
**根因**: 提交里带了 ~1MB 的 `reports/canvas_*.png` 截图。**同一提交去掉 PNG 后一次推送成功** (远端 SHA 核对一致)。
- 判据: `git show --stat HEAD` 看体积; > 几百 KB 先怀疑体积, 别怀疑网络。
- 纪律 (与老倪 Git 精简一致): **截图/PDF/视频/权重不进库**, 留本地 `reports/` 给老倪看, 提交信息里写清路径;
  已进库的旧图 `git rm --cached` 掉 (顺带让新提交变小)。本次先做了一个含 PNG 的提交 → 推送全失败 → 拆成纯代码提交才通。
- **别用 `git push … | tail -3` 看结果**: 管道退出码是 tail 的 0, 真失败被吞掉, 看起来像"没输出=也许成功了"。
  单独跑或 `; echo rc=$?` —— rc=124=超时(体积/网络), rc=1 且带 413=代理拒绝体积。

**症状 B**: 同上 (无输出, rc=124), 但与体积无关 —— **凭证取不到, git 在交互式等账号密码**。
`~/.git-credentials` 的条目 host 是 `github.com`, 而 push URL 的 host 是 `ghproxy.net` → credential.store 按 host 匹配失败 →
无 TTY 时永久挂起。正解 = 显式认证头 (token 不落配置文件/不进对话):
```bash
CRED=$(python3 -c "import re;print(re.search(r'https://([^/\s]+)@github\.com', open('$HOME/.git-credentials').read()).group(1))")
AUTH="Basic $(printf '%s' "$CRED" | base64 -w0)"
git -c http.sslVerify=false -c http.extraHeader="Authorization: $AUTH" push "<mirror-url>" HEAD:main
```

**成功判据只能靠 ls-remote**: 被墙下 fetch 也失败 → 本地 `origin/main` 引用**永远是陈旧的**,
`git status -sb` 显示 "ahead N" 不能当"没推上去"的证据 (本次实测: status 说 ahead 3, 远端其实已有其中 1 个提交)。
```bash
git -c http.sslVerify=false ls-remote "<mirror-url>" refs/heads/main   # 远端 SHA
git rev-parse HEAD                                                     # 本地 SHA; 相等才算成
```

**镜像现状 (2026-09-13 复测)**: ghproxy.net ✅ 可用 (读+push, 怕大提交) · gh-proxy.com ✅ 可 push (体积墙更硬, 413 明确) ·
ghfast.top ❌ 超时 · ghproxy.cc ❌ 证书过期 · hub.gitmirror.com ❌ DNS 不通 · github.com 直连 ❌ (TLS 中断)。

## 二、版本号升级: 禁止全局字符串替换 (会改错旧 changelog 标签)

**坑**: 上一个版本 bump 脚本为了图省事做 `s.replace("5.5.40", "5.5.41")` 全文件替换 —— 不只改了版本常量,
把 studio.py 里**旧 changelog 条目前的版本号也一起改名了** (v5.5.40 / v5.5.39 两条被标成 v5.5.41)。
后果: 变更历史错位, 与 VERSION.md 对不上。

**正解 = 精确模式替换 + 顺手修标签**:
```python
# 逐个精确锚点, 每处断言命中 1 次 (命中 ≠1 直接 assert 失败, 绝不静默)
sub1("tools/gui/studio.py", 'QLabel("Z-MAX v5.5.41")', 'QLabel("Z-MAX v5.5.42")')
sub1("tools/gui/studio.py", "XSpace Studio — Z-MAX v5.5.41 [W-01]", "XSpace Studio — Z-MAX v5.5.42 [W-01]")
sub1("tools/gui/update_checker.py", 'CURRENT_VERSION = "v5.5.41"', 'CURRENT_VERSION = "v5.5.42"')
sub1("tools/gui/version_sync.py",    'zmax_ver = "5.5.41"',           'zmax_ver = "5.5.42"')
sub1("tools/gui/docs_sync.py",       '"version": "v5.5.41"',          '"version": "v5.5.42"')
sub1("tools/gui/docs_sync.py",       '"zmax_version": "v5.5.41"',     '"zmax_version": "v5.5.42"')
# 再改错位的历史标签 (核对 VERSION.md 的版本历史行确认哪个是哪版)
sub1("tools/gui/studio.py", "        # v5.5.41: 🎯 **L4 INTACT 策略化", "        # v5.5.40: 🎯 **L4 INTACT 策略化")
# 新 changelog 条目插在上一版条目之前 (锚点 = 上一版 changelog 首行, 断言唯一)
```
- 五处同步点的权威清单在 `VERSION.md` 顶部 ("版本号位置") — 每次都照着它逐条替换 + `py_compile` 四文件。
- changelog 条目格式: `# vX.Y.Z: <做了什么 + 根因>` (不写过程); VERSION.md 表格插一行 (**版本 | 日期 | 内容**), 旧行保留。
- 近期版本**没有** `git tag` (仓库里只有 v5.5.8/v5.5.9/z700-deploy-v1.0) —— 别擅自补 tag, 除非老倪要求。
