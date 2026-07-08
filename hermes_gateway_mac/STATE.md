# Hermes Gateway — 运行状态 & 离线恢复指南

> 最后更新: 2026-07-08 22:30 CST
> 此文件供 Hermes Agent 离线恢复时自动读取

---

## 网络拓扑

```
┌─────────────────────────────────────────────────────────┐
│ Mac M1 (Mikes-Mac-mini)                                 │
│   以太网 en0 MAC: 14:98:77:38:d4:42                     │
│   Wi-Fi  en1 MAC: 14:98:77:40:86:87                     │
│                                                         │
│   Gateway Pure 运行在 :8080                              │
│   SSH Key: ~/.ssh/id_rsa → 已授权 Orin                  │
│   飞书 Hermes 网关已连接                                 │
├─────────────────────────────────────────────────────────┤
│                    SSH (免密)                            │
│                    ↓                                     │
├─────────────────────────────────────────────────────────┤
│ Orin (nvidia-desktop)                                   │
│   IP: 192.168.23.10                                     │
│   User: nvidia                                          │
│   OS: Ubuntu 22.04 (aarch64, Linux 5.15.148-tegra)      │
│   ROS2 Humble 运行中                                     │
│   机器人: XMS5-R800-W4G3B4C (6-DOF 机械臂)              │
└─────────────────────────────────────────────────────────┘
```

## 连接信息

| 项目 | 值 |
|------|-----|
| Mac IP | 通过 `ifconfig` 获取，以太网 en0 |
| Mac SSH 公钥 | `~/.ssh/id_rsa.pub` |
| Orin IP | `192.168.23.10` |
| Orin 用户 | `nvidia` |
| Gateway API | `http://localhost:8080` |
| 飞书 Hermes | 已连接 (WebSocket 模式) |

## 启动 Gateway

```bash
# 在 Mac 终端运行
cd /Users/mikeni/lerobot-smolvla-lew/hermes_gateway_mac
source venv/bin/activate
python3 gateway_pure.py --orin-host 192.168.23.10 --port 8080

# 检查是否在运行
curl http://localhost:8080/
# → {"service":"Hermes Gateway (Pure)","orin":"192.168.23.10","status":"online"}
```

## API 端点 & 数据格式

### `GET /` — 服务状态
```json
{"service": "Hermes Gateway (Pure)", "orin": "192.168.23.10", "status": "online"}
```

### `GET /status` — 完整状态快照
```json
{
    "joint_names": [
        "XMS5-R800-W4G3B4C_joint_1",
        "XMS5-R800-W4G3B4C_joint_2",
        "XMS5-R800-W4G3B4C_joint_3",
        "XMS5-R800-W4G3B4C_joint_4",
        "XMS5-R800-W4G3B4C_joint_5",
        "XMS5-R800-W4G3B4C_joint_6"
    ],
    "joint_positions": [6个float],
    "gripper_pos": null,
    "sim_joints": null,
    "last_update": <timestamp>,
    "error": null
}
```

### `GET /joints` — 关节名称→位置映射
```json
{
    "joints": {
        "XMS5-R800-W4G3B4C_joint_1": 0.160,
        "XMS5-R800-W4G3B4C_joint_2": -0.061,
        "XMS5-R800-W4G3B4C_joint_3": -2.545,
        "XMS5-R800-W4G3B4C_joint_4": 1.447,
        "XMS5-R800-W4G3B4C_joint_5": 0.435,
        "XMS5-R800-W4G3B4C_joint_6": -0.698
    }
}
```

### `GET /gripper` — 夹爪位置
```json
{"gripper_pos": null}  // null = 未连接
```

### `GET /topics` — Orin ROS2 话题列表
返回约50个话题。关键话题:

| 话题 | 类型 | 说明 |
|------|------|------|
| `/real_joint_states` | JointState | 实际关节状态 (Gateway 订阅) |
| `/gripper_pos` | Float64 | 夹爪位置 (Gateway 订阅) |
| `/joint_states` | JointState | 关节状态 |
| `/robot/tcp_pose` | - | TCP 位姿 |
| `/ee_target` | - | 末端目标 |
| `/real_sense/color/image_raw` | - | RealSense 彩色图 |
| `/real_sense/depth/image_rect_raw` | - | RealSense 深度图 |

### `POST /cmd` — 发送指令
```json
// Request
{"command": "回零"}
{"command": "gripper_open"}
{"command": "gripper_close"}

// Response
{"command": "回零", "result": "ok"}
```

### `WS /ws` — WebSocket 实时推送
每秒推送一次:
```json
{"type": "state", "joints": {...}, "gripper": null, "ts": 1783523019.16}
```

## Orin SSH 操作

```bash
# 直接 SSH
ssh nvidia@192.168.23.10

# 执行远程命令 (免密)
ssh nvidia@192.168.23.10 "source /opt/ros/humble/setup.bash && ros2 topic list"

# 查看关节状态
ssh nvidia@192.168.23.10 \
  "source /opt/ros/humble/setup.bash && ros2 topic echo --once /real_joint_states"
```

## 机器人信息

- **型号**: XMS5-R800-W4G3B4C (6-DOF 协作机械臂)
- **ROS 域 ID**: 23
- **6 个关节**: joint_1 到 joint_6
- **夹爪**: 通过 `/gripper_pos` 话题，当前未连接 (null)
- **急停**: `/emergency_stop`, `/physical_estop`, `/usb_estop`
- **传感器**: RealSense 深度相机, 力/扭矩传感器, 触觉传感器
- **运动控制**: `/motion/active_states`, `/motion/active_transition`

## 飞书连接

| 项目 | 值 |
|------|-----|
| 网关状态 | 运行中 |
| 连接模式 | WebSocket |
| App ID | cli_aac4912eb6389bc2 |
| 用户 open_id | ou_d82fe4c9f90c4e9337235d04b2241070 |
| 命令 | `hermes gateway status` / `hermes gateway restart` |

## 恢复步骤（离线后重新上线）

1. **确认 Mac Gateway 运行**
   ```bash
   curl http://localhost:8080/
   # 如果没响应:
   cd /Users/mikeni/lerobot-smolvla-lew/hermes_gateway_mac
   source venv/bin/activate
   python3 gateway_pure.py --orin-host 192.168.23.10 &
   ```

2. **确认 Orin 可达**
   ```bash
   ssh -o ConnectTimeout=5 nvidia@192.168.23.10 hostname
   ```

3. **确认飞书网关运行**
   ```bash
   hermes gateway status
   # 如果没运行:
   hermes gateway restart
   ```

4. **确认关节数据流**
   ```bash
   curl http://localhost:8080/status | python3 -m json.tool
   # 检查 joint_positions 非空, last_update 在变化
   ```

## Git 信息

- 仓库: https://github.com/MikeBMW/lerobot-smolvla-lew.git
- 分支: main (领先 origin 2 commits)
- 本地路径: /Users/mikeni/lerobot-smolvla-lew
