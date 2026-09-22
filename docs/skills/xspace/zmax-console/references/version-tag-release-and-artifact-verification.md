# 版本迭代 → 打 tag → 出 Windows/macOS 包 → 独立核验 (2026-09-22 一手)

场景: 老倪说「**小版本迭代, 发布 windows 和 mac 版本**」。踩过一个"版本号改了但一直没有安装包"的真坑, 这里记全流程。

## A. 先查真原因: 有没有**打过 tag**
CI 构建是 **tag 触发**的 (`.github/workflows/build-win-exe.yml`: `on: push: tags: ['v*']` → 并行 job `Windows .exe` + `macOS .app`,
两个产物挂到**同一个** GitHub Release)。所以:
```bash
git tag -l 'v5.11*'          # ← 只有 v5.11.1, 但代码里已经写着 v5.11.3
git log --oneline -6 | cat   # 找到 "release v5.11.2 / v5.11.3" 的提交
```
实测结论: **v5.11.2 / v5.11.3 只有提交、从没打 tag** ⇒ CI 从未构建 ⇒ 用户"没有 windows/mac 版本"。
⇒ 任何"版本升了但没包"的报障, **第一步永远是 `git tag -l`**, 别先去翻 CI 日志。
另外: 分支**领先 origin 的提交不会自己构建**, 必须 push 且 tag 必须推到远端。

## B. 版本号要改**多处** (以 VERSION.md 为准, 漏一处 = 版本面板/更新检查不一致)
| 位置 | 字段 |
|---|---|
| `tools/gui/studio.py` | 品牌小字 `QLabel("Z-MAX vX.Y.Z")` · 窗口标题 `Z-MAX vX.Y.Z [W-01]`(**多处**) · `__init__` 里的 changelog 注释段(新条目加在最前) |
| `tools/gui/update_checker.py` | `CURRENT_VERSION = "vX.Y.Z"` |
| `tools/gui/version_sync.py` | `zmax_ver = "X.Y.Z"` |
| `tools/gui/docs_sync.py` | `"version"` / `"zmax_version"` 两个键 |
| `VERSION.md` | 「版本历史」表首行(新行插在表头下) |
```bash
grep -n 'Z-MAX v' tools/gui/studio.py | head -4          # 确认所有出现点
grep -n 'CURRENT_VERSION' tools/gui/update_checker.py
grep -n 'zmax_ver' tools/gui/version_sync.py
grep -n '"version"\|"zmax_version"' tools/gui/docs_sync.py
```
语义: 主=架构重构 · 次=功能模块 · 补丁=修复/小优化; 老倪口中的"小版本迭代"= 补丁级。
changelog 注释写法沿用本仓库风格: `# vX.Y.Z: <emoji> **标题** — 老倪: 「原话」 ①… ②…` + 只写"做了什么 + 根因", 不写过程。

## C. 发布步骤
```bash
git add -A && git commit -F - <<'MSG'
release vX.Y.Z: <一句话>
版本号 5 处同步 + VERSION.md 变更行
MSG
git tag vX.Y.Z && git push origin main && git push origin vX.Y.Z   # ★ tag 必须推
```

## D. 独立核验产物 (别只信 CI 日志 / Release 页面文字)
`gh` 在这台机上**没装** ⇒ 用 GitHub API + `~/.git-credentials` 里的 token (只读出来用, 别打印):
```python
cred = open("/home/ubuntu/.git-credentials").read().strip()
tok = re.search(r"://([^:]+):([^@]+)@", cred).group(2)
# GET /repos/<owner>/<repo>/releases/tags/vX.Y.Z → assets[].name/size
```
再对 `browser_download_url` 发**范围 GET** 取文件头验真:
```bash
curl -sL --max-time 40 -r 0-262143 -o /tmp/_t "<browser_download_url>" -w "HTTP %{http_code} %{size_download}B\n"
head -c 2 /tmp/_t | xxd -p     # exe → 4d5a ("MZ" PE) · zip → 504b ("PK")
```
实测 (v5.11.4): `Z-MAX_Console.exe` 156.7 MB HTTP 206 `4d5a` ✅ · `Z-MAX_Console-macOS.zip` 122.7 MB HTTP 206 `504b` ✅。

## E. 两个仓库级坑
- **`*.log` 被 .gitignore 忽略** (`reports/*.log` 等) ⇒ 取证日志要复制成 `.txt` (或放到 tracked 目录) 才能进仓; 否则
  `git add reports/xxx.log` 静默不生效, 你以为提交了其实没有。
- CI 里 `Create Release and Publish to PyPI` **skipped 是正常的** (上游 huggingface/lerobot 专属, 与本仓库无关);
  另外两个 workflow (`Simulink 模型验证 CI` / `Build & Push Console Docker Image`) 会同时起, 别被吓到。

## F. 长构建怎么等
构建 ~10 分钟 ⇒ 用后台脚本轮询 API 直到 conclusion, 再打产物清单 (本仓库现成: `~/.hermes/scripts/watch_release_build.py <tag>`),
不要前台干等; 收尾一定要回场核验(D), 因为"构建成功"≠"产物可用"。
