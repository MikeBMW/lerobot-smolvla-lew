# Z-MAX LeRobot Fork 同步工作流

本文档说明如何在保留 Z-MAX 定制代码的同时，同步 LeRobot 官方仓库的更新。

## 仓库结构

```
origin: https://github.com/MikeBMW/lerobot-smolvla-lew (你的 fork)
upstream: https://github.com/huggingface/lerobot (官方主仓库)
```

## 核心原则

1. **所有 Z-MAX 定制代码放在独立目录**
   - `src/lerobot/policies/smolvla_lew/` - 自定义策略
   - `tools/gui/` - GUI 工具
   - `scripts/` - 辅助脚本
   - `docs/` - Z-MAX 项目文档（避免与官方 docs/source 冲突）

2. **尽量不修改官方代码**
   - 如果需要修改官方代码，在代码中添加注释标记：`# [Z-MAX 定制]`
   - 这些修改在同步时需要手动处理冲突

3. **定期同步上游更新**
   - 建议每周或每月同步一次
   - 重要版本发布后立即同步（如 v0.5.0 → v0.6.0）

## 同步步骤

### 方法一：使用同步脚本（推荐）

```bash
cd ~/xspace/lerobot-smolvla-lew
./scripts/sync-upstream.sh
```

脚本会自动：
1. 检查工作区是否干净
2. 从 upstream 获取最新更新
3. 显示即将合并的更新数量和内容
4. 执行合并
5. 推送到 origin

如果遇到冲突，脚本会提示解决步骤。

### 方法二：手动执行

```bash
# 1. 确保工作区干净
git status
git add .
git commit -m "WIP: my changes"  # 如果有未提交的更改

# 2. 从 upstream 获取更新
git fetch upstream

# 3. 查看有多少新提交
git log --oneline HEAD...upstream/main | wc -l

# 4. 合并到当前分支
git merge upstream/main --no-ff -m "Sync with upstream $(date +%Y-%m-%d)"

# 5. 如果有冲突，解决后继续
# git status
# 编辑冲突文件
# git add <冲突文件>
# git commit

# 6. 推送到你的 fork
git push origin main
```

## 冲突处理指南

同步时可能会出现三类冲突：

### 1. Z-MAX 独立文件（不会冲突）
```
src/lerobot/policies/smolvla_lew/  ✓ 无冲突
tools/gui/                          ✓ 无冲突
scripts/                            ✓ 无冲突
docs/Z-MAX*.md                      ✓ 无冲突
```

### 2. 注册文件（可能冲突）
```
src/lerobot/policies/__init__.py    ⚠️ 需要手动合并
```

**解决方法：**
- 保留 upstream 的所有官方 policy 注册
- 确保你的 smolvla_lew 注册也在里面
- 添加你的注册代码在文件末尾，并加注释：
  ```python
  # [Z-MAX 定制] Z-MAX policies
  from .smolvla_lew.configuration_smolvla_lew import SmolVLALewConfig as SmolVLALewConfig
  ```

### 3. 官方文件修改（极少见）
```
src/lerobot/utils/...               ⚠️ 如果你修改了官方工具代码
src/lerobot/datasets/...            ⚠️ 如果你修改了数据集代码
```

**解决方法：**
- 优先保留 upstream 的版本（接受上游更新）
- 如果你的修改是必要的，在合并后重新应用
- 考虑将修改移到独立文件，通过扩展/继承实现

## Z-MAX 代码保护清单

以下文件永远不会被 upstream 修改，可以安全编辑：

```
# 策略代码
src/lerobot/policies/smolvla_lew/
src/lerobot/policies/zmax_*/

# GUI 工具
tools/gui/

# 辅助脚本
scripts/

# Z-MAX 项目文档
docs/Z-MAX*.md
docs/Z-MAX*.pptx
docs/*.pdf
docs/具身机器人*.md

# GitHub Actions（自定义）
.github/workflows/sync-upstream.yml
```

## 自动化同步（可选）

如果你想让 GitHub 自动创建同步 PR，可以启用 GitHub Actions：

```bash
# 复制 workflow 文件
mkdir -p .github/workflows
cp ../sync-upstream-workflow.yml .github/workflows/sync-upstream.yml

# 提交
git add .github/workflows/sync-upstream.yml
git commit -m "ci: add upstream sync workflow"
git push
```

然后在 GitHub 设置中启用该 workflow，每周会自动创建同步 PR。

## 常见问题

### Q: 多久同步一次？
A: 建议每周检查一次 `git log HEAD...upstream/main | wc -l`，如果有重要更新就同步。

### Q: 同步后我的代码会丢失吗？
A: 不会。只要你的代码在独立目录，merg e 会自动保留。只有注册文件（`__init__.py`）可能需要手动合并。

### Q: upstream 删除了某个文件，我的代码会受影响吗？
A: 如果官方删除了你依赖的文件，合并时会有冲突提示。你需要修改代码适配新结构。

### Q: 如何查看 Z-MAX 专属的文件列表？
```bash
git diff --name-only upstream/main...main | grep -v "^src/lerobot/" | grep -v "^tests/"
```

## 示例：完整同步流程

```bash
# 1. 检查工作区
cd ~/xspace/lerobot-smolvla-lew
git status
# On branch main
# nothing to commit, working tree clean

# 2. 运行同步脚本
./scripts/sync-upstream.sh

# 输出示例：
# =========================================
# Z-MAX LeRobot Sync Script
# =========================================
#
# ✓ 工作区干净
#
# 正在从 upstream (huggingface/lerobot) 获取更新...
# ✓ 获取完成
#
# upstream 有 30 个新提交
#
# 即将合并的新提交（前10个）：
# a1b2c3d feat(policies): add new policy
# d4e5f6g fix(datasets): update format
# ...
#
# 是否继续合并？(y/n) y
#
# 正在合并 upstream/main...
# ✓ 合并成功
#
# 正在推送到 origin...
# ✓ 推送成功
#
# =========================================
# ✓ 同步完成！
# =========================================

# 3. 验证同步结果
git log --oneline -5
# a1b2c3d Merge: Sync with upstream huggingface/lerobot (2026-07-04)
# 0530dd9 chore(infra): remove requirements files (#3925)
# 698d2a0 feat(policies): add EVO1 policy (#3908)
# ...

# 4. 检查你的代码是否还在
ls src/lerobot/policies/smolvla_lew/
# configuration_smolvla_lew.py  modeling_smolvla_lew.py  ...
```

---

**最后更新:** 2026-07-04  
**维护者:** Z-MAX Development Team
