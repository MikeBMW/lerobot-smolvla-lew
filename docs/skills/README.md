# Z-MAX Avatar Skills Sync

> 分身技能同步目录 — 小芳(Mac M1) ↔ xspace/静静(WSL2)  
> 通过 Git 仓库共享技能，确保两个分身的技能集保持一致

## 目录结构

```
docs/skills/
├── README.md           # 本文件
├── manifest.json       # 技能清单（自动生成）
├── 小芳/               # 小芳的专属/核心技能 SKILL.md
├── xspace/             # xspace的专属/核心技能 SKILL.md
└── shared/             # 双方都需要的关键技能
```

## 同步流程

1. **导出**: 各自用 `hermes skills list` 列出技能，更新 `manifest.json`
2. **对比**: 识别对方有而自己缺失的技能
3. **安装**: 安装缺失技能（`hermes skills install`）
4. **通知**: 飞书群 @对方 告知更新

## 安装对方技能

```bash
# 从共享目录安装（本地文件）
cp docs/skills/shared/<skill-name>/SKILL.md ~/.hermes/skills/<category>/<name>/SKILL.md

# 或从 GitHub 安装（如果已推送到远程）
hermes skills install https://raw.githubusercontent.com/MikeBMW/lerobot-smolvla-lew/main/docs/skills/shared/<skill-name>/SKILL.md
```

## 版本

- 创建: 2026-07-11
- 维护: 小芳 & xspace/静静
