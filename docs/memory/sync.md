# Z-MAX 共享记忆 · 静静-小芳 同步区

> 本文档是静静(xspace)和小芳(Mac)的**共享知识区**  
> 任何一方更新后，另一方应立即同步学习  
> 更新日期: 2026-07-10  
> 版本: v2.0 — 全面记忆同步 | 产品版本: v1.0.4

---

## 🔗 仓库简称

| 简称 | 仓库 | 说明 |
|:--|:--|:--|
| **GUI** | github.com/MikeBMW/lerobot-smolvla-lew | Z-MAX SmolVLA-LEW 工程 |
| **web** | github.com/MikeBMW/zmax-website | datadrive.world 网站 |

---

## 🏷️ 产品体系

| 代号 | 定义 | 定位 |
|:--|:--|:--|
| **Z-MAX** | 智能模型引擎 (软件产品) | 核心AI推理引擎 |
| **Z700** | L4全自主机器人 | 光模块工厂精细操作 |
| **Z700F** | Fix L2协作机器人 | 人机协作场景 |
| **SmolVLA-LEW** | SmolVLM2-500M + DiT-B + LeWorldModel | 视觉-语言-动作模型 |

---

## 📐 版本管理体系

- 版本号格式: `v{X.Y.Z}`
- 三层文档矩阵: **L1**(产品发布/Marketing) → **L2**(产品培训/Sales) → **L3**(技术路线/Engineering)
- 关键文件: `BRAND.md`, `VERSION.md`
- Phase 0-4 开发路线
- **禁止提及"他山"** → 对外一律称"供应商"

---

## 🌐 网络拓扑

```
[WSL xspace] ─── 飞书WS ─── [飞书服务器]
      │                          │
      │                    [ECS隧道 :18080]
      │                          │
      │                    [Mac M1 :8080]
      │                          │
      │                    [Orin 192.168.23.10]
      │                     ROS2 Domain 23
      │
[ECS 39.102.211.79]
  ├── WordPress (datadrive.world)
  ├── 宝塔Nginx (/www/server/nginx/sbin/nginx)
  └── DB: xSpace/Nix2.7@1
```

---

## 🔑 关键凭据速查

> ⚠️ 敏感: 仅供静静和小芳使用, 禁止外泄

| 资源 | 凭据 |
|:--|:--|
| GitHub | MikeBMW, token: ghp_XXjG |
| ECS SSH | root@39.102.211.79, Nix19789 |
| ECS MySQL | xSpace / Nix2.7@1 |
| Mac SSH | Mike-Mac-mini @ 10.163.148.52 |
| Orin SSH | nvidia@192.168.23.10 |

---

## 📁 关键路径

### GUI仓库 (~/lerobot-smolvla-lew/)
```
tools/gui/studio.py              ← GUI主程序
tools/gui/run_studio.sh          ← GUI启动脚本
tools/gui/version_sync.py        ← 版本同步
tools/gui/training_backend.py    ← 训练后端
tools/gui/inference_server.py    ← gRPC推理服务
tools/gui/inference_client.py    ← gRPC推理客户端
docs/memory/xspace.md            ← 静静记忆
docs/memory/xiaofang.md          ← 小芳记忆
docs/memory/sync.md              ← 本文件
docs/VERSION.md                  ← 版本号
docs/BRAND-品牌注册材料.pptx
```

### 网站 (~/zmax-website/)
```
robot.html    ← 产线动画
robot2.html   ← 老化箱动画
robot3.html   ← 眼图动画
```

### 文档 (~/yspace/)
```
spec/         ← 产品规格
docs/         ← 产品文档
journal/      ← 日记 (YYYY/MM/YYYY-MM-DD.md)
```

---

## 🎨 设计规范

### WordPress配色
- **暗底区域**: 正文 `#c8d1d9` + 标题 `#00d4aa`
- **白底区域**: h2 `#1a1a2e` + 副标题 `#374151`

### GUI规范
- PyQt5暗色主题
- 中文界面, 无emoji
- 积木间距: 列≥48px, 行≥15px, 方块≥48px
- active实色+白字, keep透明边框淡字, new虚线半透明
- 硬件控制用开关不用滑块
- 信号追踪: 鲜绿→渐暗→保留 (示波器余晖)

---

## 🤝 协作协议

### 沟通方式
- **主通道**: 飞书群 dataworld
- **@mention格式**: @xspace (静静), @Hermes小芳 (小芳)
- **实时协作**: 双方在线时通过飞书联合决策

### 任务分工
| 任务 | 静静 | 小芳 |
|:--|:--:|:--:|
| GPU训练 | ✅ | — |
| 模型推理 | ✅ | — |
| GUI开发 | ✅ | — |
| 网站部署 | ✅ | — |
| Orin连接 | — | ✅ |
| ROS2转发 | — | ✅ |
| 飞书中转 | ✅ | ✅ |
| ECS隧道 | — | ✅ |
| 记忆同步 | ✅ | ✅ |

### 供应链知识库 (2026-07-10)

| 供应商 | 文档 | 关键产品 |
|:--|:--|:--|
| 均胜电子 | `docs/供应链/均胜电子...pdf` | Jetson Thor域控+MCU, 六维力, IMU, 立体相机, 电子皮肤, 灵巧手, 半固态电池, BMS |
| Orin域控 | `docs/供应链/Orin域控产品手册3.2 - CN.pdf` | 域控制器产品手册 |
| Thor域控 | `docs/供应链/Thor-域控产品手册1.0 - CN.pdf` | 新一代域控制器 |
| 智微工业 | `docs/供应链/智微工业_智擎系列.pdf` | 工业机器人部件 |
| PRO3000 | `docs/供应链/PRO3000使用文档.pdf` | 操作文档 |
| 智蜂电池 | `docs/供应链/智蜂--工业移动机器人双48V...doc` | 双48V可插拔电池包定制 |

硬件技能: 加载 `joyson-hardware-components` 技能获取均胜全部产品规格。

### 同步规则
1. **每次重大变更后**, 更新本方记忆文件 (`xspace.md` 或 `xiaofang.md`)
2. **共享信息变更后**, 更新本文件 (`sync.md`)
3. **更新后@对方**, 对方应在下次会话中 `git pull` 并加载最新记忆
4. **冲突以sync.md为准**, 因为这是双方协商后的共享共识

---

## 📊 当前进度 (2026-07-10)

| 阶段 | 状态 | 内容 |
|:--|:--|:--|
| Phase 0 | ✅ 完成 | SmolVLA训练验证 + gRPC推理 + GUI面板 + Mac分身 |
| Phase 1 | ✅ 完成 | Orin联调 + 性能基准 + 知识库 |
| Phase 2 | 🔄 进行中 | GUI优化 + 网站动画 + 训练稳定化 |
| Phase 3 | ⏳ 规划 | 真机部署测试 |
| Phase 4 | ⏳ 规划 | 产品发布 |

---

## 🌿 Git 分支策略 (2026-07-10)

| 仓库 | 主干 | 分支 | 负责人 | 内容 |
|:--|:--|:--|:--|:--|
| **GUI** | `main` | — | xspace (静静) | Z-MAX核心工程, 训练/推理/GUI |
| **GUI** | — | `mac` | 小芳 | Mac端侧配置, Orin操作脚本 |
| **web** | `main` | — | xspace (静静) | datadrive.world网站 |

### 工作流
1. **小芳**在 `mac` 分支上开发Mac/Orin相关内容
2. **小芳**完成后向 `main` 发起 Pull Request
3. **静静**审查并合并到 `main`
4. `main` 分支为唯一发布源

### 创建 mac 分支 (小芳执行)
```bash
git clone https://github.com/MikeBMW/lerobot-smolvla-lew.git
cd lerobot-smolvla-lew
git checkout -b mac
git push -u origin mac
```

---

## 🔄 互相学习清单

双方应互相了解对方的最新变化:

- [ ] 静静阅读小芳的 `xiaofang.md` 了解Mac侧最新状态
- [ ] 小芳阅读静静的 `xspace.md` 了解WSL侧最新状态
- [ ] 双方确认 `sync.md` 中的共享信息一致

---

*最后更新: 2026-07-10, 静静 (xspace) — 待小芳确认*
