# Z-MAX 统一版本管理 · 三工程协同CI/CD

> 总工: 静静 · 2026-07-19

## 版本号规则

```
v{major}.{minor}-{type}-{MMDD}
例: v2.3-merge-0719

三工程共用主版本号(v2.3)
type: merge/auto/hotfix
MMDD: 月日
```

## 仓库映射

| 仓库 | 部署位置 | 触发方式 |
|:--|:--|:--|
| zmax-website | ECS datadrive.world | web git push → webhook → ECS pull |
| lerobot-smolvla-lew | RTX 4060(GUI) + RTX 4090(模型) | main push → 本地pull |
| zmax-data-pipeline | MAC M1 | mac push → crontab pull |

## 提交规范

```
type(scope): 简短描述

详细说明(可选)
来源: @web/@xspace/@mac
关联: zmax-website/lerobot-smolvla-lew/zmax-data-pipeline

例:
feat(comfyui): 版本号实时显示
来源: @web
关联: zmax-website
```

类型: feat/fix/docs/perf/refactor/release/merge

## Release发布流程

1. 三工程main分支全量commit
2. 合并到主工程main
3. git tag vX.Y-type-MMDD
4. GitHub Release → 填写功能清单+贡献者
5. comfyui版本号自动刷新

## CI检查项

- [ ] 三工程commit message含来源+关联
- [ ] tag匹配版本号规范
- [ ] Release含完整功能清单
- [ ] comfyui显示最新版本号
