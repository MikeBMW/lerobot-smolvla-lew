---
name: git-history-slimming
description: Use when a git repo is bloated or user wants 精简/不要什么都上传.
---

# Git 仓库瘦身（filter-repo）

Trigger: 用户说"为什么那么大""要精简""不要什么都上传"，`.git` 超 50MB，克隆慢。

## 老倪铁律（本用户核心偏好，先记住）
- git 仓库**只放代码和文本文档**（md/py/yaml/工作流）
- 大文件一律不上传：zip/pptx/pdf 交付件(>1MB)、rosbag/mcap 采集数据、模型权重(.pt/.safetensors → HF Hub)、视频 → 放网盘/数据服务器
- 合并他人分支前先 diff 检查：CI 工作流(.github/workflows/)、核心模块常被误删或版本回退；`:Zone.Identifier` Windows 垃圾文件常被带上

## 诊断
```bash
du -sh .git
git count-objects -vH | grep size-pack
# 历史最大 blob TOP20（瘦身前必跑）
git rev-list --objects --all | git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize) %(rest)' | awk '/^blob/ {print $3, $4}' | sort -rn | head -20
# 垃圾文件
git ls-files | grep -i "zone.identifier"
```

## 清理（filter-repo）
```bash
pip3 install --break-system-packages git-filter-repo   # pip3 直接装即可（PEP668 需 --break-system-packages）
git filter-repo --invert-paths \
  --path-glob 'docs/*.zip' --path-glob 'docs/**/*.zip' \
  --path-glob 'docs/*.pdf' --path-glob 'docs/**/*.pdf' \
  --path-glob 'data/mcap/*' --path-glob 'models/*.pt' \
  --path-glob '*:Zone.Identifier' --force
git remote add origin <url>   # ⚠️ filter-repo 会删掉 origin remote！
git push -f origin main mac   # 历史重写必须 force push
```

## Pitfalls（实测踩过）
- **glob 不匹配顶层**：`docs/**/*.pdf` 不匹配 `docs/` 根下文件，`docs/*.pdf` 不匹配子目录 → 两个都要写，跑完复查剩余大文件
- **filter-repo 会移除 origin remote**（设计如此），push 前必须重新 add
- **历史重写让所有协作者 clone 失效**（小芳 mac 分支）→ force push 前先沟通
- 合并分支前检查是否误删：`git diff --stat main origin/<branch> -- .github/` 看 CI 是否被删；mac 分支曾误删 build-win-exe.yml（exe 自动构建）和版本号回退 → `git checkout main -- <file>` 恢复后提交再合并
- 删除带引号/转义路径的文件：`git ls-files -z | tr '\0' '\n' | grep Zone.Identifier | while read f; do git rm --cached -- "$f"; done`（`git rm` 直接吃路径会 fatal）

## 防再犯（.gitignore 追加）
```
*.zip
*.pptx
docs/**/*.pdf
data/mcap/
models/
*:Zone.Identifier
.venv/
.venvs/
```
