# Z-MAX 端侧部署管线 · Edge Deployment Pipeline

> 小芳负责 · Mac M1 → Orin Nano/AGX  
> 配合 xspace(Sys0/1框架) + web(Sys2云端)

## 部署架构

```
云端 (web/4090)          WSL2 (xspace/4060)       Mac (小芳/M1)         Orin (端侧)
┌──────────────┐       ┌──────────────┐       ┌──────────────┐       ┌──────────────┐
│ Sys-2        │  API  │ Sys-1 ACT    │  SSH  │ Sys-0 安全    │  ROS2 │ XMS5-R800    │
│ VTLA/GR00T   │◄─────►│ 51.6M 底座   │◄─────►│ 仿真桥       │◄─────►│ 6轴 + 传感器  │
│ (4090训练)   │       │ Sys-11/12    │       │ leRobot抽象   │       │ RealSense    │
└──────────────┘       └──────────────┘       └──────────────┘       └──────────────┘
```

## 部署步骤

### Phase 1: Mac 端侧验证 (小芳)
```bash
# 1. 启动仿真桥
python3 hermes_gateway_mac/orin_sim_bridge.py --http-port 8081

# 2. 加载 Sys-0 安全
python3 hermes_gateway_mac/sys0_safety.py

# 3. 启动 leRobot 抽象 (仿真模式)
python3 -c "
from robot_zmax_orin import ZMaxOrinRobot, ZMaxOrinConfig
config = ZMaxOrinConfig(level='L3', use_sim=True)
with ZMaxOrinRobot(config) as robot:
    obs = robot.get_observation()
    robot.send_action({'target_joint_positions': [0,0,0,0,0,-0.1745]})
"

# 4. 连接 xspace Sys-1/Sys-2 API (待xspace提供端点)
```

### Phase 2: Orin Nano 部署
```bash
# 同步代码到 Orin
rsync -avz ~/lerobot-smolvla-lew/ nvidia@192.168.23.10:~/xspace/lerobot-smolvla-lew/

# Orin上启动
ssh nvidia@192.168.23.10 "
  sudo ip addr add 192.168.23.66/24 dev enP8p1s0
  cd ~/0615/tashan_robot_so_20260630_163849_f98c30a_aarch64
  source /opt/ros/humble/setup.bash && source install/setup.bash
  export ROS_DOMAIN_ID=23
  ros2 launch launch/start.launch.py project:=sr5_guangmokuai_100gAOI
"
```

## 接口约定

| 层 | 提供方 | 接口 | 消费方 |
|:---:|------|------|------|
| Sys-0 | 小芳 | `sys0_safety.ok_to_move()` | Sys-1 |
| Sys-1 | xspace | `POST /act/infer` (待定) | 小芳 |
| Sys-2 | web | `POST /sys2/infer` (待定) | Sys-1 |

## 当前状态

| 模块 | Mac M1 | Orin |
|------|:---:|:---:|
| Sys-0 安全 | ✅ | ✅ |
| 仿真桥 | ✅ | ✅ |
| leRobot抽象 | ✅ | ⏳ |
| Sys-1 ACT | ⏳ 待xspace | ⏳ |
| Sys-2 VTLA/GR00T | ⏳ 待web | ⏳ |
