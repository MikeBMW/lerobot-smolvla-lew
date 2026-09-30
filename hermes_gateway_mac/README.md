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
| `gateway_pure.py` | 纯Python版（推荐，零ROS2依赖） |
| `gateway_node.py` | ROS2版（需ROS2 Humble） |
| `api_server.py` | FastAPI HTTP接口 (配合ROS2版) |
| `hermes_gateway_sdk.py` | WSL端SDK |
| `mac_autostart.sh` | Mac开机自启动安装脚本 |
| `requirements.txt` | Python依赖 |
| `launch.sh` | 一键启动 (ROS2版) |

## 场景: 无显示器去现场

### 前置准备 (在家做好)

```bash
# 1. Mac设置自动登录 (必须！)
# System Settings → Users & Groups → Login Options → Automatic login: ON

# 2. 安装开机自启动
bash mac_autostart.sh install

# 3. 配置SSH免密连接Orin (到现场第一次连)
ssh-keygen -t rsa -f ~/.ssh/id_rsa -N ""
ssh-copy-id nvidia@192.168.23.10
```

### 到现场后

```bash
# 1. 通电 → Mac自动启动 → Gateway自动运行

# 2. 从手机/其他设备检查Mac IP
# (Mac会在终端显示IP，或看路由器DHCP列表)

# 3. 飞书告诉Hermes Mac的IP
# 静静，Mac在 192.168.x.x，连上Orin

# 4. Hermes通过飞书下发指令
```

### 通电后自动启动清单

| 进程 | 说明 |
|------|------|
| `caffeinate` | 防休眠 |
| `gateway_pure.py` | HTTP API :8080 |
| `launchd KeepAlive` | 崩溃自动重启 |
