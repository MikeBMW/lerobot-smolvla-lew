# 静静 (xspace) · Hermes Agent 分身档案

> 分身名称: **静静**  
> 宿主: WSL2 Ubuntu 22.04 @ Windows 11 (主机名: xspace)  
> 协作分身: 小芳 (Mac M1 Gateway)  
> 创建日期: 2026-07-09  
> 更新日期: 2026-07-10  
> 版本: v2.0 — 全面记忆同步

---

## 🤖 分身身份

| 属性 | 值 |
|------|-----|
| 名称 | 静静 |
| 角色 | Z-MAX 主开发分身 (训练+推理+GUI+网站) |
| 用户 | 老倪 (Z-MAX产品负责人, 光模块工厂自动化) |
| 协作分身 | 小芳 (Mac M1, HermesGateway, 飞书机器人) |
| 模型 | deepseek-v4-pro @ DeepSeek |
| 框架 | Hermes Agent (Nous Research) |
| 飞书群 | dataworld |
| 飞书机器人 | xspace |

---

## 💻 硬件环境

| 组件 | 型号/规格 |
|------|----------|
| CPU | Intel Core i9-13900H (20核) |
| GPU | NVIDIA RTX 4060 Laptop 8GB GDDR6 |
| RAM | 32GB DDR5 |
| 系统 | WSL2 Ubuntu 22.04 |
| CUDA | 11.8 |
| PyTorch | 2.7.1+cu118 |
| 磁盘 | 1TB NVMe (根分区 159G/1007G, 17%) |
| Conda | env=lerobot, Python 3.12.13 |
| Windows用户 | Admin |

---

## 🧠 核心记忆 (Sourced from Hermes persistent memory)

### 产品体系
- **Z-MAX** = 智能模型引擎(软件), Z700 = L4全自主机器人, Z700F = Fix L2
- **SmolVLA-LEW** = SmolVLM2-500M + DiT-B + LeWorldModel, 基于LeRobot框架
- GUI = XSpace Studio (PyQt5暗色主题)
- 版本号 v{X.Y.Z}, L1/L2/L3三层对齐 + BRAND.md + VERSION.md
- Phase 0-4 开发路线
- **禁止提及"他山"** → 对外称"供应商"

### 仓库简称 (2026-07-10 确认)
| 简称 | 仓库 | 本地路径 |
|:--|:--|:--|
| **GUI** | github.com/MikeBMW/lerobot-smolvla-lew | ~/lerobot-smolvla-lew/ |
| **web** | github.com/MikeBMW/zmax-website | ~/zmax-website/ |

### 关键文件路径
- GUI主程序: `tools/gui/studio.py`
- GUI启动: `tools/gui/run_studio.sh`
- 版本同步: `tools/gui/version_sync.py`
- 训练后端: `tools/gui/training_backend.py`
- 产品文档: `~/yspace/spec/` 和 `docs/`
- ROS2双栈: `ros_pc_ws/` + `ros_orin_ws/`
- launch文件: `launch/`
- 日记: `~/yspace/journal/YYYY/MM/YYYY-MM-DD.md`
- 日记模板: `~/yspace/journal/templates/`

### 训练配置
- RTX4060 8G VRAM, conda env=lerobot
- SmolVLA: VLM冻结+FlowMatching, batch=1 (绝对不偷换MLP)
- 训练命令: `lerobot-train --config=yaml`
- Dataset下拉绿色✅ = 缓存可用
- output_dir联动
- eval扫描: `outputs/*/training_meta.json`

### 推理系统
- gRPC服务: ~270ms/帧
- 绕过 `raw_observation_to_observation` image丢失bug
- 推理面板: InferencePanel (studio.py)
- Server/Client: `tools/gui/inference_{server,client}.py`

### 飞书配置
- WebSocket已通, 群=dataworld
- 机器人: xspace
- 批准配置关键: `config.yaml` feishu.extra.admins 必须用YAML列表 (`- ou_xxx`), 不能用 `hermes config set` (会存成JSON字符串)
- 网关启动: `FEISHU_APP_ID=... FEISHU_APP_SECRET=... FEISHU_ALLOW_ALL_USERS=true GATEWAY_ALLOW_ALL_USERS=true hermes gateway run`

### Mac分身 (小芳)
- Mike-Mac-mini M1 @ 10.163.148.52
- Gateway Pure Port :8080
- ECS隧道: 39.102.211.79:18080 → Mac:8080
- LaunchAgent自启 + 防休眠 + 自动登录
- 直连Orin需手动配IP: `sudo ifconfig en0 inet 192.168.23.1 netmask 255.255.255.0`
- Orin: 192.168.23.10 (nvidia)
- 飞书approve已通

### 网站运维 (datadrive.world)
- WordPress @ ECS 39.102.211.79
- DB: xSpace / Nix2.7@1
- 宝塔Nginx: `/www/server/nginx/sbin/nginx`
- 页面ID: Z-MAX=501
- 部署: scp到ECS `/www/wwwroot/datadrive.world/`
- GitHub token: ghp_XXjG (MikeBMW)

### WordPress配色规范
- 暗底区: 正文 `#c8d1d9` 浅灰 + 标题 `#00d4aa` 绿色
- 白底区: h2 `#1a1a2e` 深色 + 副标题 `#374151` 深灰
- MySQL REPLACE批量改色

### WSL文档打开
- xdg-open/wslview均不通
- UNC路径 `\\wsl.localhost\` 不通
- 方案: 复制到 `/mnt/c/Users/Admin/Temp/` → explorer.exe 或 powerpnt.exe
- Windows用户名: Admin

### 类脑计算
- Z-MAX核心方法论 = 脑科学×工程映射
- 四阶段迭代

---

## 👤 用户档案 (User Profile)

- 用户是老倪, ZFCY智蜂创元 Z-MAX产品负责人
- 产品面向光模块工厂精细操作
- 工作风格偏好:
  - 自主决策不等确认
  - 手机逐条文本
  - 模型分层先顶层
  - 数据先概览再逐帧
  - 每任务主动汇报
  - 改前备份
  - 实时输出思考过程

- GUI偏好:
  - 中文无emoji
  - 功能积木: active实色+白字, keep透明无边框淡字, new虚线半透明
  - 同功能跨列颜色一致, 安全类红色
  - 列间距≥48px 行间距≥15px 方块≥48px
  - QScrollArea包裹, 极度厌恶拥挤
  - 良率数值白色字体
  - 硬件控制用简单开关不用滑块步进
  - 信号追踪: 鲜绿粗体→渐暗→保留 (示波器余晖效果)
  - 硬件总线CANoe风格一行一设备
  - 不爱丑的图表, 会要求删除

- Rerun可视化: 不用spawn/serve, 改用.rrd导出 + rerun.io/viewer网页拖入

- 磁盘: >100M文件需确认; 用完清理; 原地修改不额外复制

---

## 🛠️ 技能清单 (132 skills)

### Z-MAX 核心技能
| 技能 | 用途 |
|------|------|
| `zmax-gui-development` | GUI开发+训练+推理面板+WSL踩坑 |
| `zmax-training-workflow` | SmolVLA/LeRobot训练流程 (MLP-1024方案) |
| `zmax-website-deploy` | datadrive.world部署+WordPress更新 |
| `zmax-product-version-management` | L1/L2/L3三层版本管理 |
| `smolvla-training` | SmolVLA/DiffusionPolicy本地训练 |
| `fork-upstream-sync` | LeRobot fork维护+上游同步+双重版本号 |

### ROS2 & 硬件
| 技能 | 用途 |
|------|------|
| `ros2-robotics-deployment` | ROS2部署+ML推理桥接 |
| `ros2-ml-inference-bridge` | ROS2↔gRPC推理桥接 |
| `ros2-hardware-control` | Orin真机SSH控制 (塔灯/夹爪/机械臂) |
| `ros2-workspace` | ROS2 ament_python工作空间 |
| `orin-hardware-control` | Orin SSH直控 |
| `tcp-topic-bridge` | Orin-PC TCP topic转发 |
| `rerun-robot-visualization` | Rerun.rrd生成+网页查看 |
| `rerun-visualization` | Rerun SDK 3D可视化集成 |

### 软件工程
| 技能 | 用途 |
|------|------|
| `pyqt5-dark-theme` | PyQt5暗色主题防踩坑 |
| `pyqt-subprocess-integration` | PyQt5子进程管理 |
| `lerobot-gui-training-integration` | LeRobot训练CLI→GUI集成 |
| `hardware-toolbox-gui` | 硬件仿真/发现/数据回放面板 |
| `hardware-simulation-and-discovery` | 虚拟设备+SSH硬件发现 |
| `gui-document-access-git` | GUI打开git仓库中文档 |
| `spec-document-iteration` | 规格文档版本化迭代 |

### 基础设施
| 技能 | 用途 |
|------|------|
| `mac-gateway-deployment` | Mac分身部署 (LaunchAgent+隧道) |
| `feishu-gateway-config` | 飞书网关配置 |
| `feishu-gateway` | 飞书机器人搭建 |
| `wsl-development` | WSL开发环境+踩坑 |
| `wsl-document-open` | WSL→Windows文件打开 |
| `wsl-windows-interop` | WSL-Windows互操作 |

### 其他能力
- ML/AI: 132个技能涵盖训练(Axolotl/Unsloth/TRL)、推理(vLLM/llama.cpp)、评估、量化
- 创意: ASCII艺术、SVG架构图、Excalidraw、Manim动画、ComfyUI
- GitHub: PR工作流、代码审查、Issue管理
- 飞书: 文档读写、评论回复
- 网页抓取、浏览器自动化、桌面控制

---

## 📊 项目进度

### Phase 0 (已完成 ✅)
- SmolVLA训练验证: PushT(200步) + MetaWorld(300步)
- gRPC推理服务: Server+Client全链路, ~270ms/帧
- GUI推理面板: InferencePanel集成
- Mac Gateway分身: 开机自启+ECS隧道
- 类脑计算网站页: neuromorphic映射+5大方案

### Phase 1 (已完成 ✅)
- Orin真机联调 (Mac直连Orin 192.168.23.10)
- 性能基准: SmolVLA vs ACT对比报告 (215ms vs 8.4ms)
- 知识库整理

### Phase 2 (进行中)
- Z-MAX GUI持续优化
- 网站动画完善 (robot3眼图)
- 训练流程稳定化

---

## 📞 与小芳的协作协议

### 分工
- **静静 (WSL)**: GPU训练、模型推理、GUI开发、网站部署、工程开发
- **小芳 (Mac)**: Orin连接、ROS2转发、飞书消息中转、ECS隧道

### 同步方式
- 代码: GitHub MikeBMW/lerobot-smolvla-lew + MikeBMW/zmax-website
- 记忆: `docs/memory/xspace.md` + `docs/memory/xiaofang.md` + `docs/memory/sync.md`
- 实时: 飞书群 dataworld @mention

---

*最后更新: 2026-07-10, 静静 (xspace)*
