# Z-MAX 项目总任务板 · Task Board

> 飞书群: dataworld (置顶)  
> 更新: 2026-07-10  
> 分身: 小芳(Mac) + xspace(WSL2)  
> 流程: 小芳(mac分支) → PR → xspace审核 → merge main

---

## 📊 总体统计

| | 小芳 (Mac M1) | xspace (WSL2) |
|---|:-:|:-:|
| 已完成 | 7 项 | 待确认 |
| 进行中 | 3 项 | 待确认 |
| 待开始 | 2 项 | 4 项 |
| Git commits | 21 (mac分支, 待推送) | — |

---

## 🤖 小芳 (Mac M1) — 任务清单

### ✅ 已完成

| # | 任务 | 交付物 | 日期 |
|---|------|--------|------|
| 1 | 飞书网关搭建 | WebSocket连接, launchd自启 | 0708 |
| 2 | SmolVLA 450M 推理验证 | Mac MPS ~300ms, Orin CUDA ~240ms | 0708 |
| 3 | 三方记忆系统 | 小芳+xspace档案 + shared-memory | 0710 |
| 4 | 专利交底书(实用新型) | .docx, 8项权利要求, 含仿真章节 | 0710 |
| 5 | 仿真Client-Server系统 | protocol+client+server+test, 5/5测试通过 | 0710 |
| 6 | 性能基准报告 | SmolVLA/ACT/Mini 三模型对比 | 0710 |
| 7 | 供应链文档 | 均胜电子控制器硬件方案 | 0710 |

### 🔄 进行中

| # | 任务 | 状态 | 阻塞 |
|---|------|------|------|
| 8 | GitHub SSH配置 | ❌ push被拒 | 需添加公钥到GitHub |
| 9 | mac分支→PR | ⏳ 21 commits待推送 | 阻塞于#8 |
| 10 | 仿真Server真实模型集成 | ⏳ 占位代码已写好 | 需xspace集成lerobot推理 |

### 📋 待开始

| # | 任务 | 依赖 |
|---|------|------|
| 11 | Orin仿真节点深度开发 | 仿真Server联通后 |
| 12 | 帮助文档多语言版 | — |

---

## 🖥️ xspace (WSL2) — 任务清单

### ✅ 已完成

| # | 任务 | 状态 |
|---|------|------|
| 1 | 分身档案创建 | hermes-xspace.md v2.0 |

### 🔄 进行中 / 待开始

| # | 任务 | 优先级 | 依赖 |
|---|------|:---:|------|
| 2 | **datadrive.world 网站升级** | 🔴 高 | 设计简报已就绪 |
| 3 | 仿真Server端SmolVLA推理集成 | 🔴 高 | — |
| 4 | 审核小芳mac分支PR | 🟡 中 | 小芳SSH配置 |
| 5 | 供应链文档审阅 & 同步 | 🟡 中 | — |

### 📋 Web网站升级 (详细)

| 子任务 | 内容 |
|--------|------|
| 2a | 首页重构 (公司简介 + Z-MAX产品 + 技术栈) |
| 2b | 仿真标签页 (架构图 + 性能表 + 启动命令) |
| 2c | 专利标签页 (专利卡片 + 创新点 + 标准) |
| 2d | 保留现有动画 + 文字介绍 |

> 素材: `docs/memory/web-design-brief.md` + `docs/memory/web-simulation-patent-content.md`

---

## 🔗 协作阻塞项

| 阻塞 | 影响 | 解决 |
|------|------|------|
| GitHub SSH未配置 | 小芳21 commits无法推送, xspace无法审核 | **添加公钥到 https://github.com/settings/keys** |
| Mac↔WSL2网络 | 仿真Client-Server联通测试 | 确认局域网IP可达 |

---

## 📅 建议优先级

```
本周必做:
  1️⃣ GitHub SSH配置 (小芳 + 用户)
  2️⃣ Web网站升级完成 (xspace)
  3️⃣ 仿真Server模型集成 (xspace)

下周:
  4️⃣ mac分支PR → xspace审核 → merge main
  5️⃣ Orin仿真节点深度开发
  6️⃣ 供应链文档双向审阅
```

---

## 📞 沟通

- 飞书群 dataworld
- @Hermes小芳 (Mac M1 问题)
- @xspace (WSL2 问题 + 代码审核)
