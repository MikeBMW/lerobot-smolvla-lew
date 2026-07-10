# Z-MAX 项目总任务板 · Task Board

> 飞书群: dataworld (置顶)  
> 更新: 2026-07-10 上午  
> 分身: 小芳(Mac) + xspace(WSL2)  
> 流程: 小芳(mac分支) → PR → xspace审核 → merge main

---

## 📊 总体统计

| | 小芳 (Mac M1) | xspace (WSL2) |
|---|:-:|:-:|
| 已完成 | **9** / 12 | **4** / 5 |
| 进行中 | 1 | 1 |
| 待开始 | 2 | 0 |
| Git | mac+main 双分支已推送 ✅ | main 新增大量文档 ✅ |

---

## 🤖 小芳 (Mac M1) — 12 项任务

### ✅ 已完成 (9)

| # | 任务 | 交付物 |
|---|------|--------|
| 1 | 飞书网关 | WebSocket + launchd 自启 |
| 2 | SmolVLA 450M 推理 | Mac 300ms / Orin 240ms |
| 3 | 三方记忆系统 | xiaofang + xspace + shared-memory + 归档 |
| 4 | 专利交底书 | .docx, 8项权利要求, 含仿真章节 |
| 5 | 仿真Client-Server | protocol + client + server + 集成测试 5/5 ✅ |
| 6 | 性能基准报告 | SmolVLA 215ms / ACT 0.5ms / Mini 0.5ms |
| 7 | 供应链文档 | 均胜域控制器 + 硬件技能 (83技能) |
| 8 | GitHub SSH 配置 | 🔓 刚刚打通! |
| 9 | mac分支推送 + main合并 | 🔓 35文件 4258行已推送 |

### 🔄 进行中 (1)

| # | 任务 | 状态 |
|---|------|------|
| 10 | 仿真Server真实模型集成 | ⏳ 占位代码已写好，需xspace WSL2端挂载lerobot推理 |

### 📋 待开始 (2)

| # | 任务 |
|---|------|
| 11 | Orin仿真节点深度开发 |
| 12 | 帮助文档多语言版 |

---

## 🖥️ xspace (WSL2) — 5 项任务

### ✅ 已完成 (4)

| # | 任务 | 交付物 |
|---|------|--------|
| 1 | 分身档案 | hermes-xspace.md v2.0 |
| 2 | 供应链文档深化 | Orin/Thor/PRO3000手册PDF + 均胜完整方案 + 电池需求书 |
| 3 | 专利交底书v2 | 多模态VLA控制系统 .docx + 生成脚本 |
| 4 | 产品文档迭代 | L2方案 v1.0.4、L3路线 v1.0.4、硬件平台方案、问卷 |

### 📋 待开始 (1)

| # | 任务 | 优先级 |
|---|------|:---:|
| 5 | datadrive.world 网站升级 | 🔴 设计素材已就绪 |

---

## 🔗 已解决的阻塞

| 阻塞 | 状态 |
|------|:---:|
| GitHub SSH 配置 | ✅ 已解决! mac+main 双推送成功 |
| 代码双向同步 | ✅ 小芳mac↔main↔xspace WSL2 |

---

## 📅 下一步优先级

```
本周:
  1️⃣ xspace: Web网站升级 (素材就绪)
  2️⃣ xspace: 仿真Server SmolVLA模型集成
  3️⃣ 小芳: Orin仿真节点深度开发

下周:
  4️⃣ 小芳 → xspace: 正式发起 mac→main PR
  5️⃣ xspace: 代码审核 + 合并
```

---

## 📞 沟通

- @Hermes小芳 — Mac M1, Orin, 仿真
- @xspace — WSL2, Web, 代码审核, 供应链
