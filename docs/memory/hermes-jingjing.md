# 静静 · Hermes Agent 分身档案

> 分身名称: **静静**  
> 宿主: WSL2 Ubuntu @ Windows 11  
> 协作分身: 小芳 (Mac M1 Gateway)  
> 创建日期: 2026-07-09  
> 版本: v1.0

---

## 🤖 分身身份

| 属性 | 值 |
|------|-----|
| 名称 | 静静 |
| 角色 | Z-MAX 主开发分身 |
| 用户 | 老倪 (Z-MAX产品负责人, 光模块工厂自动化) |
| 协作分身 | 小芳 (Mac M1, HermesGateway, 飞书机器人) |
| 模型 | deepseek-v4-pro |
| 框架 | Hermes Agent (Nous Research) |

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
| 磁盘 | 1TB NVMe (797G可用) |
| Conda | Python 3.12.13, env=lerobot |

---

## 🧠 核心记忆

### 用户档案
- 用户是老倪，ZFCY智蜂创元 Z-MAX产品负责人
- Z-MAX=智能化模型引擎(软件)，Z700=L4全自主机器人
- 产品面向光模块工厂精细操作
- 偏好：表格对比展示，自主决策不等确认，手机看消息用逐条文本
- 飞书群 dataworld，xspace机器人

### 项目技术栈
- SmolVLA-LEW (SmolVLM2-500M + DiT-B + LeWorldModel)
- 仓库: MikeBMW/lerobot-smolvla-lew @ GitHub
- GUI: XSpace Studio (PyQt5暗色主题)
- ROS2双栈: ros_pc_ws + ros_orin_ws
- Orin: 192.168.23.10 (nvidia), ROS2 Domain 23

### 训练铁律
- SmolVLA: VLM冻结+FlowMatching, batch=1, 绝对不偷换MLP
- 训练用 `lerobot-train --config=yaml`, 不要手写loop
- RTX4060 8GB, OOM了直说

### 推理系统
- gRPC服务: ~270ms/帧
- 绕过 `raw_observation_to_observation` image丢失bug
- 推理面板: InferencePanel(stu dio.py)
- Server/Client: tools/gui/inference_{server,client}.py

### Mac分身 (小芳)
- Mac M1 @ 10.163.148.52
- Gateway Pure Port 8080
- ECS隧道: 39.102.211.79:18080→Mac:8080
- LaunchAgent自启 + 防休眠 + 自动登录

### 网站运维
- datadrive.world WordPress @ ECS 39.102.211.79
- DB: xSpace/Nix2.7@1
- Nginx 宝塔版: /www/server/nginx/sbin/nginx
- 页面ID: Z-MAX=501, 类脑计算=504

### 文件关键路径
- 工程: ~/lerobot-smolvla-lew/
- 产品文档: ~/yspace/spec/ + docs/
- GUI: tools/gui/studio.py
- 日记: ~/yspace/journal/YYYY/MM/YYYY-MM-DD.md

---

## 🛠️ 核心技能

| 技能 | 用途 |
|------|------|
| `zmax-gui-development` | GUI开发+训练+推理面板+WSL踩坑 |
| `zmax-training-workflow` | SmolVLA/LeRobot训练流程 |
| `zmax-website-deploy` | datadrive.world部署 |
| `zmax-product-version-management` | L1/L2/L3版本管理 |
| `ros2-ml-bridge` | ROS2↔gRPC推理桥接 |
| `orin-hardware-control` | Orin真机SSH控制 |
| `mac-gateway-deployment` | Mac分身部署 |
| `wsl-development` | WSL环境模式 |
| `wsl-document-open` | WSL→Windows文件打开 |
| `pyqt5-dark-theme` | PyQt5暗色主题 |
| `ros2-robotics-deployment` | ROS2部署 |
| `smolvla-training` | SmolVLA训练 |

---

## 📊 最近项目进度

### Phase 0 (已完成)
- SmolVLA训练验证: PushT(200步) + MetaWorld(300步)
- gRPC推理服务: Server+Client全链路, ~270ms/帧
- GUI推理面板: InferencePanel集成
- Mac Gateway分身: 开机自启+ECS隧道
- 类脑计算网站页: neuromorphic映射+5大方案

### Phase 1 (进行中)
- Orin真机联调 (Mac直连Orin 192.168.23.10)
- 性能基准: SmolVLA vs ACT对比报告
- 知识库整理 (本文档)

---

## 📞 与小芳的协作协议

### 分工
- **静静 (WSL)**: GPU训练、模型推理、网站部署、工程开发
- **小芳 (Mac)**: Orin连接、ROS2转发、飞书消息中转

### 同步
- 代码: GitHub MikeBMW/lerobot-smolvla-lew
- 记忆: 本文件 (docs/memory/hermes-jingjing.md)
- 日记: ~/yspace/journal/

### 握手
- 小芳读本文件获取静静的最新状态
- 通过飞书群 dataworld 实时沟通

---

*最后更新: 2026-07-09, 静静*
