# 发版坑补充: 多并行会话撞版本号 + docs_sync 版本号易落后 (2026-09-10 实测)

## 坑 A — 多并行会话同仓库发版会撞版本号
Z-MAX 仓库 (lerobot-smolvla-lew) 常有多个会话并行工作 (CLI + 飞书 gateway)。
2026-09-10 实测: CLI 侧查 `git tag | tail` 看到 v5.5.6, 于是发 v5.5.7 (含 3D 修复);
几乎同时飞书侧会话把 studio.py 版本号改到 v5.5.8 → v5.5.9 并推了 tag。
后果: Release 资产按 tag 分裂, 用户拿到哪版说不清。

**发版前必做** (防撞号):
```bash
git fetch origin --tags      # 先同步远端 tag/分支, 别只看本地
git tag | tail -8            # 远端最新版本号
git log origin/main --oneline -3   # 远端 main 是否已被其它会话推进
```
再决定新 tag。若发现远端已 > 本地提交, 先把本地改动 rebase/合到最新 main 再打 tag。

## 坑 B — docs_sync.py 版本号最容易落后
版本号四文件里, `docs_sync.py` 的 `"version"` / `"zmax_version"` 常被漏更
(实测: 其它三文件已在 v5.5.7 时, docs_sync 还停在 **v5.5.0** — 差了 7 个版本)。
发版脚本务必一次 grep 全部四文件核对:
```bash
grep -nE "v?5\.[0-9]+\.[0-9]+" tools/gui/studio.py tools/gui/update_checker.py \
  tools/gui/version_sync.py tools/gui/docs_sync.py | grep -iE "CURRENT_VERSION|zmax_ver|setWindowTitle|Z-MAX v|\"version\"|zmax_version"
```
(注意: studio.py 的 changelog 注释里会出现历史版本号, 只改 UI 字面量 `Z-MAX vX.Y.Z` 与
`setWindowTitle`, 别把历史注释一起替换 — 用 `Z-MAX v5.5.X` 这种带前缀的精确串替换。)

## 坑 C — workflow_dispatch 重触发同 tag 无需改号
若某平台构建挂过 (如 v5.5.8 因 CI 验证行 `metaworld.__version__` AttributeError 双平台 fail),
修好 CI 后用 workflow_dispatch 重触发**同 tag** 即可 (`upload-release-action` overwrite:true),
不必 incremented 版本号。
