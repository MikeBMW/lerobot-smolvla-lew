# Z-MAX 效率提升方案 · Efficiency Boost

> 三体协作优化 · 2026-07-12

## 🔴 当前瓶颈

| 瓶颈 | 影响 | 耗时 |
|------|------|:---:|
| 等待回复 | 三人串行沟通 | 分钟~小时 |
| 接口不明确 | 反复确认格式 | 重复沟通 |
| Git PR流程 | mac→review→merge | 循环等待 |
| 测试依赖真机 | Orin不在线 | 阻塞测试 |

## 🟢 解决方案

### 1. 约定接口标准 (一次定义, 永远使用)

```
Sys-0 → Sys-1: POST /sys1/infer  {joints:[6], camera:b64} → {action:[6], gripper:float}
Sys-1 → Sys-2: POST /sys2/infer  {observation, task} → {action:[6], confidence:float}
Sys-0 → GUI:  GET  /health         → {status, checks:[5]}
```

### 2. 并行开发 (三人同时推进)

```
之前 (串行): 小芳做→xspace审→web改→循环
现在 (并行): 
  xspace: Sys-1/11/12 框架 (不依赖小芳)
  web:    Sys-2 训练 + 前端 (不依赖xspace)
  小芳:   测试用例 + 仿真 (不依赖web)
  
  汇合点: 接口约定好后, 各自开发, 最后集成
```

### 3. 自动化同步

```bash
# 每个分身完成一个任务后自动:
1. git commit -m "feat: XXX"
2. git push origin [branch]
3. @ 通知其他人
4. 其他人 git pull (自动化)
```

### 4. 预定义数据格式

小芳已提供: `robot-status.json`, `hardware-tree.json`
xspace需提供: Sys-1 API 响应格式
web需提供: Sys-2 API 请求/响应格式

### 5. 仿真优先

| 阶段 | 环境 | 速度 |
|:---:|------|:---:|
| 开发 | 纯仿真 (Mac) | 秒级 |
| 联调 | 仿真+API模拟 | 分钟级 |
| 验证 | 真机 (Orin) | 小时级 |

---

## ⚡ 建议立即执行

| 行动 | 负责人 | 预计 |
|------|:---:|:---:|
| 确认 Sys-1 接口格式 | xspace | 即刻 |
| 确认 Sys-2 接口格式 | web | 即刻 |
| 发布接口规范文档 | xspace | 10分钟 |
| 三人并行开发 | 全体 | 持续 |
| 每日同步一次 | 全体 | 5分钟 |

---

> 接口一次定义 → 三人并行开发 → 仿真验证 → 集成测试
