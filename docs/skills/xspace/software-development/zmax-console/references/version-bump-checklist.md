# 版本小升级检查清单 (2026-09-01 v3.4.0→v3.4.1 实测)

老倪验收流程: "保存数据，记忆，技能，小版本升级；推送代码" — 每次功能验收后走一遍。

## 版本号位置 (VERSION.md 规范 = 三处)
1. `tools/gui/studio.py` — `ver = QLabel("Z-MAX vX.Y.Z")` (品牌版本小字)
2. `tools/gui/studio.py` — `setWindowTitle("XSpace Studio — Z-MAX vX.Y.Z [W-01]")` × 2 处 (正常 + ⚠️非调试模式)
3. `git tag vX.Y.Z` + push

## 两处易漏 (2026-09-01 实测踩坑)
- **`VERSION.md` 版本历史表缺条目**: 实测 v3.4.0 条目从未写入, 表头从 v3.2.3 直接跳 v3.4.1。
  升级时检查上一版条目是否在表里, 缺则补。
- **窗口标题摘要注释头部停旧版**: `_QTimer.singleShot(2000, self._maybe_warn)` 那行的注释
  是变更摘要, 实测停在 v3.3.5 (v3.4.0 摘要从未写入)。规范 = 最新版本摘要追加到最前,
  格式 `# vX.Y.Z: 变更点1+变更点2 | v上一版: ...`。

## 验收命令
```bash
grep -n "vX.Y.Z" tools/gui/studio.py   # 应恰好 3 处版本号 + 1 处摘要注释
python3 -c "import ast; ast.parse(open('tools/gui/studio.py').read())"  # 语法
git add VERSION.md docs/skills/xspace/zmax-console/SKILL.md tools/gui/studio.py
git commit -m "docs(vX.Y.Z): ..."
git tag vX.Y.Z && git push origin main --tags
git log origin/main --oneline -2 && git ls-remote --tags origin | grep vX.Y.Z  # 验证
```
版本升级 = 三处版本号 + VERSION.md 条目 + 摘要注释 + tag + push 全做齐才算完。

## 相关
- 技能同步: zmax-console SKILL.md 改完要同步 docs/skills/xspace/zmax-console/SKILL.md 副本
  (飞书端 gateway agent 也会读它)。
- 记忆同步: 关键教训压缩进 memory (有字符上限, 先删后加)。
