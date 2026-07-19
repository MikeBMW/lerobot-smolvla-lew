# Z-MAX LeRobot · Release v2.3.0

**发布日期**: 2026-07-19  
**代码基线**: `main` branch, commit `512bc9e4`  
**标签**: `v2.3-merge-0719`

---

## 概述

Z-MAX 数据闭环系统 v2.3 版本，实现 Orin 真机 → MAC 跳板 → 4090 云端训练的全链路自动化。本版本合并了 web、mac、main 三个分支的工作成果。

---

## 新增功能

### 硬件心跳与命令通道 (@web)
- HTTP 心跳端点 `POST /api/mac/heartbeat`，MAC 每 5 秒轮询
- 命令队列机制 `PENDING_COMMAND`，4090 下发指令 → MAC 心跳应答获取
- 实时状态：`mac_connected`、`orin_online`
- Nginx 上传限制提升至 500MB

### 自动训练与磁盘管理 (@web)
- 数据上传后自动触发 `train_h_jepa.py` 训练
- `POST /auto-train` 切换自动训练开关
- `cleanup_disk()` 自动清理：保留最新 5 个 `.npz`，删除原始 MCAP，清理 7 天前 W&B 缓存
- 每周日 03:00 定时清理

### H-JEPA ZFlow 模型 (@xspace)
- 三层 z 流架构：z1(256) → z2(256) → z3(128) → gate → 14×7 动作
- 2.68M 参数量，11MB 权重
- Energy 正则化训练，收敛至 loss=0, energy=-23.26
- W&B 集成：https://wandb.ai/xspace/zmax-hjepa

### ComfyUI 前端 v3.8 (@web)
- 世界坐标系缩放（Ctrl+滚轮），节点选择正常
- 📊 仪表盘：右侧面板显示 Orin→MAC→4090 实时流水线状态
- 顶部状态栏：🖥 → 💻 → 🧠 实时连接指示
- 🔗 连接按钮：一键检测硬件在线状态，绿色边框显示
- 三阶段流水线：Orin MCAP 采集(绿闪) → MAC 转发(绿闪) → 4090 训练(红闪)
- 硬件分组：🔩 硬件(4) + 📊 可视化(1) + 🔌 集成(2)
- 版本号 + 日期显示在工具栏

### MAC 数据转发 (@Hermes小芳)
- MAC 守护服务，常驻后台运行
- 心跳上报 datadrive.world，每 5 秒一次
- Orin 数据拉取、格式转换、转发至 4090
- MCAP → NPZ 自动转换

### Orin 真机采集 (@xspace)
- ROS2 bag record 30 秒 MCAP 数据采集
- RealSense D405 相机实时推流 (/orin_realtime.jpg)
- FastAPI 端点：/record/start、/record/status

---

## 数据管道

```
Orin Nano (192.168.23.x)
    │ ros2 bag record (30s MCAP)
    ▼
MAC (跳板机)
    │ 心跳 5s + 数据转发
    ▼
ECS (39.102.211.79) → SSH 隧道 → 4090
    │ HTTP API
    ▼
4090 训练节点
    │ H-JEPA 训练 → W&B
    ▼
ComfyUI 前端展示
```

---

## 文件变更

| 文件 | 来源 | 变更 |
|------|:--:|------|
| `comfyui_backend.py` | @web | 心跳+命令通道+自动训练+磁盘清理 |
| `train_h_jepa.py` | @xspace | H-JEPA 训练脚本 |
| `h_jepa_zflow.py` | @xspace | ZFlow VLA 模型定义 |
| `z_config.py` | @xspace | 模型超参配置 |
| `comfyui.html` | @web | 仪表盘+缩放+流水线+版本号 |
| `pipeline_config.json` | @web | 数据流水线配置 |
| MAC 守护脚本 | @Hermes小芳 | 心跳轮询 + 数据转发 |

---

## 已知限制

1. Ctrl+滚轮缩放后，节点选择坐标系偶有偏移
2. MCAP → NPZ 转换需 rosbags 库完整类型定义
3. Orin 直接连接仅限局域网

---

## 下一版本计划 (v2.4)

- [ ] MQTT 替代 HTTP 轮询 (降低延迟)
- [ ] Orin 本地缓存 + 断点续传
- [ ] Cosmos 物理仿真集成
- [ ] 多 Orin 节点支持
- [ ] 训练进度实时推流

---

*本 release 遵循 Z-MAX ASPICE V-Model 开发流程。*
