# Hermes Gateway — Mac分身

Hermes Agent的ROS2+HTTP分身，运行在Mac M1上，作为WSL本体与Orin机器人之间的桥梁。

## 架构

```
┌─ Mac M1 ────────────────────────────────────────┐
│                                                  │
│  gateway_node.py (ROS2)                          │
│    ↓ /real_joint_states (Orin →)                 │
│    ↓ /gripper_pos                                │
│    ↓ /hmi/events                                 │
│    ↑ /hermes_cmd, /hermes_target_pose            │
│                                                  │
│  api_server.py (HTTP :8080)                      │
│    GET  /status    → JSON状态                    │
│    GET  /joints    → 关节位置                    │
│    POST /cmd       → 发送指令                    │
│    WS   /ws        → 实时推送                    │
└──────────────────┬───────────────────────────────┘
                   │ HTTP/SSH
┌──────────────────▼───────────────────────────────┐
│  WSL (Hermes Agent)                              │
│  → 查询状态, 发送指令, 飞书交互                   │
└──────────────────────────────────────────────────┘
```

## 快速开始

### 前置条件

1. **ROS2 Humble** (Mac M1)
   ```bash
   brew install ros-humble-desktop
   # 或从源码编译
   ```

2. **Python 3.10+**
   ```bash
   # 创建虚拟环境(推荐)
   python3 -m venv venv
   source venv/bin/activate
   ```

### 安装启动

```bash
# 1. 克隆项目
git clone https://github.com/MikeBMW/lerobot-smolvla-lew.git
cd lerobot-smolvla-lew/hermes_gateway_mac

# 2. 安装依赖
pip install -r requirements.txt

# 3. 启动 (需要先source ROS2环境)
source /opt/ros/humble/setup.bash
bash launch.sh
```

启动后访问: `http://localhost:8080`

## API使用

### Hermes本体(WSL)操作

```bash
# 查询机器人状态
curl http://mac-ip:8080/status

# 查询关节位置
curl http://mac-ip:8080/joints

# 发送回零指令
curl -X POST http://mac-ip:8080/cmd \
  -H "Content-Type: application/json" \
  -d '{"command":"回零"}'

# 发送目标位姿
curl -X POST http://mac-ip:8080/target_pose \
  -H "Content-Type: application/json" \
  -d '{"names":["joint_1","joint_2"],"positions":[0.5,-0.3]}'
```

### 实时监控 (WebSocket)

```python
import asyncio, websockets, json

async def monitor():
    async with websockets.connect("ws://mac-ip:8080/ws") as ws:
        async for msg in ws:
            data = json.loads(msg)
            print(f"Joints: {data.get('joints')}")
            print(f"Gripper: {data.get('gripper')}")

asyncio.run(monitor())
```

## 文件说明

| 文件 | 说明 |
|------|------|
| `gateway_node.py` | ROS2节点：订阅Orin话题，发布指令 |
| `api_server.py` | FastAPI HTTP接口 + WebSocket |
| `requirements.txt` | Python依赖 |
| `launch.sh` | 一键启动脚本 |
