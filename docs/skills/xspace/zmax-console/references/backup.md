# 记忆备份到仓库

## 流程

1. 收集当前 Hermes memory + user profile 内容（从系统 prompt 的 MEMORY/USER PROFILE 段落）
2. 写入 `zmax-website/backups/mem_YYYYMMDD.md`
3. `git add + commit + push`

## 文件名规范

`mem_YYYYMMDD.md` — 例如 `mem_20260730.md`

## 内容模板

```markdown
# Hermes Memory Backup · YYYY-MM-DD

## Memory (个人笔记)

**系统状态:**
- ...

**项目:**
- ...

## User Profile

- ...

## 版本

- Z-MAX v1.x.x
```

## 注意事项

- memory 存在内部数据库，不可直接读文件。从系统 prompt 的「MEMORY」和「USER PROFILE」段复制内容。
- 只保存持久性事实，不保存任务进度或临时状态。
- git push 需要 GitHub token 已配置（MikeBMW）。
