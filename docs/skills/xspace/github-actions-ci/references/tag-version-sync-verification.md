# 发版前核验: tag 内版本文件必须同步 (2026-09-08 v5.3.0 发版实锤)

## 事故
v5.2.0 已发布 (exe/macOS 都挂 Release), 但 GUI 内版本号一直是 v5.1.0 — 版本 bump 只改了
分支 + tag, **tag 提交里 studio.py/update_checker.py 等根本没同步** (CURRENT_VERSION 落后一版,
exe 内"检查更新"判断错乱; 下次发版才补同步 5.1.0→5.3.0 一次跨两版)。

## 铁律
打 tag **前**核验分支文件; 打 tag **后**核验 tag 内容 (分支可能在你 commit 后又被别的分身推进):
```bash
git show v5.3.0:tools/gui/update_checker.py | grep CURRENT_VERSION   # 必须 = 新 tag
git show v5.3.0:tools/gui/studio.py | grep -c 'v5\.3\.0'             # 应 ≥3 (QLabel/窗口标题×2/changelog)
```

## Z-MAX Console 版本号位置清单 (五处, 仓库 VERSION.md 头部为权威, 2026-09-08 从三处扩到五处)
1. tools/gui/studio.py — `ver = QLabel("Z-MAX vX.Y.Z")` (品牌版本小字, ~L642)
   + `setWindowTitle(... vX.Y.Z ...)` (~L9755/9763, 两处) + changelog 巨型注释前缀 (~L9766)
2. tools/gui/update_checker.py — `CURRENT_VERSION = "vX.Y.Z"` (~L10, 决定检查更新逻辑)
3. tools/gui/version_sync.py — `zmax_ver = "X.Y.Z"` (~L316)
4. tools/gui/docs_sync.py — `"version"` + `"zmax_version"` 两键 (~L193/197)
5. VERSION.md — 历史表新行 + 变更摘要
zmax_gui_launch.py 是 studio.py 软链 (改一处即可, grep 会重复命中属正常)。

## 相关教训
- 大版本发布前 `git log origin/main..HEAD --oneline` 数清未推送提交 — 本地超前 N 个 ≠ 已发布
  (2026-09-08 曾 13 提交积压后才发 v5.3.0; 先确认要发布的内容全进了 tag 再打 tag)。
- 版本号字符串残留检查: `grep -rn 'v5\.1\.0\|"5\.1\.0"' tools/gui/*.py` 应为 0 (排除 changelog 历史)。
- 发布后必做资产核验 (大小 + sha256 digest 对比 + file 类型), 方法见 github-actions-ci SKILL.md
  "Release 资产版本号"节 — 不要只看 CI 绿。
