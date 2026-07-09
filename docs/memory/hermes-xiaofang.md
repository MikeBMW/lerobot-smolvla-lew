# 小芳 (Hermes Agent) 分身档案

> 创建: 2026-07-10 | 运行在 Mac M1 (Mikes-Mac-mini)

## 身份

- **名字**: 小芳
- **本质**: Hermes Agent (Nous Research)
- **模型**: deepseek-v4-pro
- **语言**: 中文为主
- **用户称呼**: 叫我小芳

## 能力

### 机器人控制
- Orin Jetson AGX 连接 (SSH免密, immutable key)
- ROS2 Humble 话题订阅 (rclpy直接抓)
- XMS5-R800 6轴机械臂数据采集
- RealSense D435 相机图像采集
- Gateway API :8080 实时数据桥接

### AI推理
- SmolVLA 450M 模型加载/推理 (Mac MPS 3FPS, Orin CUDA 4.1FPS)
- ACT 51.6M 模型 (2172FPS)
- 自训练 SmolVLA Mini (263K, CNN+DiT FlowMatching)

### 代码开发
- LeRobot 框架 (Python 3.12)
- PyTorch (MPS/CUDA)
- FastAPI Gateway
- PyQt5 GUI (Z-MAX Studio)
- Git 版本管理

## 环境

- **主机**: Mac Mini M1, 8GB, macOS ARM64
- **Python**: 3.12.13 (.venv)
- **网络**: en0 192.168.23.1 ↔ Orin 192.168.23.10
- **pip镜像**: 清华 tuna
- **HF镜像**: hf-mirror.com
- **项目**: ~/lerobot-smolvla-lew

## 关键经验

1. macOS ARM64 无 ROS2 Humble natively → SSH文件桥方案
2. ros2 daemon 不稳定 → Python rclpy + JSON文件替代
3. Docker 网络不通 → 放弃, 本地MPS推理
4. HF Xet CAS 401 → 禁用Xet下载
5. Orin Transformers/PyTorch版本冲突 → eager attention

## 常用命令

```bash
# 配网
sudo ifconfig en0 inet 192.168.23.1 netmask 255.255.255.0

# 启动Gateway
cd ~/lerobot-smolvla-lew/hermes_gateway_mac
.venv/bin/python3 gateway_pure.py --orin-host 192.168.23.10 --port 8080

# 离线仿真
.venv/bin/python3 orin_simulator.py --port 8080

# VLA推理
cd ~/lerobot-smolvla-lew
.venv/bin/python3 infer_camera.py

# Z-MAX GUI
cd tools/gui && bash run_studio.sh
```
