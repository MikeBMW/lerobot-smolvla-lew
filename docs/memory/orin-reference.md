# Orin 完整硬件&软件参考

> 离线开发用快照 — 2026-07-11 更新 (真机关节数据验证)

## 硬件

| 项目 | 值 |
|------|-----|
| 型号 | NVIDIA Jetson AGX Orin |
| CPU | 6核 ARM Cortex-A78AE |
| GPU | 2048 CUDA cores, 64 Tensor cores |
| 内存 | 7.4GB LPDDR5 |
| 磁盘 | 233GB NVMe |
| 相机 | Intel RealSense D435 (480×640, 30fps) |
| 机器人 | XMS5-R800-W4G3B4C (6轴协作机械臂) |
| IP | 192.168.23.10 |
| 用户 | nvidia |

## 软件

| 项目 | 值 |
|------|-----|
| OS | Ubuntu 22.04 aarch64 |
| Kernel | 5.15.148-tegra |
| ROS2 | Humble (Domain ID 23) |
| Python | 3.10.12 |
| CUDA | 12.6 |
| PyTorch | 2.5.0a0+872d972e41.nv24.08 |
| 工作空间 | ~/0615/tashan_robot_so_20260630_163849_f98c30a_aarch64 |
| 启动命令 | `bash ~/run.sh` (项目: sr5_guangmokuai_100gAOI) |

## 6轴关节

| 关节 | 典型位置 |
|------|------|
| XMS5-R800-W4G3B4C_joint_1 | 0.1602 |
| XMS5-R800-W4G3B4C_joint_2 | -0.0614 |
| XMS5-R800-W4G3B4C_joint_3 | -2.5455 |
| XMS5-R800-W4G3B4C_joint_4 | 1.4469 |
| XMS5-R800-W4G3B4C_joint_5 | 0.4349 |
| XMS5-R800-W4G3B4C_joint_6 | -0.6977 |

## 完整话题列表 (73个, 机器人运行时)

### 关节/运动
/real_joint_states, /joint_states, /sim_joint_states, /sim_joint_trajectory,
/motion/active_states, /motion/active_transition, /motion/execution_result,
/motion/initialization_complete, /motion/node_runtime, /robot/joint_states

### 末端/位姿
/robot/tcp_pose, /ee_target, /CurRealPose, /goal_pose, /ControlMove

### 夹爪
/gripper_pos, /gripper_cmd, /brake_ctrl

### 相机 (RealSense D435)
/realsense/color/camera_info, /realsense/color/image_raw,
/realsense/depth/image_rect_raw, /realsense/points

### 力控/触觉
/robot/force_torque, /tactile_sensor

### HMI/事件
/hmi/events, /emergency_stop, /emergency_stop/event,
/physical_estop, /physical_estop/event, /usb_estop, /usb_estop/event

### 底盘
/chassis_status, /chassis_velocity, /RobotState, /RobotPower, /RobotEvent

### 障碍物
/obstacle_box_state, /obstacle_boxes, /obstacle_boxes_array

### 点云/激光
/ply_pointcloud, /points_raw, /scan

### 视觉
/visualization_marker_array, /foundationpose/tray_reference/debug_image

### 系统
/robot_description, /robot_status, /execution_mode_real,
/parameter_events, /rosout, /tf, /tf_static, /client_count, /connected_clients

### 外设
/barcode_scanner/status, /tower_light/status, /tower_light/command,
/honeywell_scanner, /tactile_sensor

### 导航/建图
/nav_system_state, /slam_status, /mapping_progress, /initialpose,
/clicked_point, /cancel_action, /stop_move

### 场景
/scene_mesh_delete, /scene_mesh_import,
/scene_mesh_marker_server/feedback, /scene_mesh_marker_server/update,
/obstacle_marker_server/feedback, /obstacle_marker_server/update

### Cloud通信
/CloudToRobotManageMapArea, /CloudToRobotMapInfo, /CloudToRobotMapInfo,
/RobotChassisLogLevel, /RobotToCloudManageMapArea,
/RobotToCloudMapInfoReq, /RobotToCloudPosture

## 关键消息类型

| 话题 | 类型 |
|------|------|
| /real_joint_states | sensor_msgs/JointState |
| /joint_states | sensor_msgs/JointState |
| /gripper_pos | std_msgs/Float32 |
| /realsense/color/image_raw | sensor_msgs/Image |
| /realsense/depth/image_rect_raw | sensor_msgs/Image |
| /robot/force_torque | geometry_msgs/WrenchStamped |
| /robot/tcp_pose | geometry_msgs/PoseStamped |
| /chassis_status | robot_common/ChassisStatus |
| /emergency_stop | std_msgs/Bool |
| /hmi/events | interfaces/HmiEvent |
| /tactile_sensor | interfaces/TactileSensor |

## 自定义接口 (interfaces包)

路径: ~/0615/history/tashan_robot2/install/interfaces/share/interfaces/
- msg/TactileSensor.msg
- srv/GripperSrv.srv
- srv/TargetPose.srv
- srv/MoveSequence.srv
- srv/VisionServer.srv
- 等20+服务定义

## 自定义消息 (robot_common包)

- robot_common/MoveByAction, Posture, PowerStatus, ChassisStatus
- robot_common/NavSystemState, SlamStatus

## Realsense相机参数

- 分辨率: 480×640 (color), 匹配深度
- 帧率: 30fps
- 编码: bgr8 (color), 16UC1 (depth)
- frame_id: XMS5-R800-W4G3B4C_base (joint states)
- 数据流: ~30KB JPEG (quality 70)

## 控制器

- 品牌: 珞石 (ROKAE) xMate SR5
- 型号: XMS5-R800-W4G3B4C
- 6轴协作机械臂
- EtherCAT总线
- 项目名: sr5_guangmokuai (光模块AOI检测)

## Mac连接

```bash
# 配网
sudo ifconfig en0 inet 192.168.23.1 netmask 255.255.255.0
# SSH
ssh nvidia@192.168.23.10
# 启动机器人
bash ~/run.sh
```

---

## 🤖 真机关节校准数据 (2026-07-11)

> 手动模式, 电机使能, 静止状态  
> 来源: `/real_joint_states` topic

| 关节 | 名称 | 位置 (rad) | 约合角度 | 速度 | 力矩 |
|:---:|------|:---:|:---:|:---:|:---:|
| J1 | XMS5-R800-W4G3B4C_joint_1 | **+0.1602** | +9.2° | 0 | 0 |
| J2 | XMS5-R800-W4G3B4C_joint_2 | **-0.0614** | -3.5° | 0 | 0 |
| J3 | XMS5-R800-W4G3B4C_joint_3 | **-2.5455** | -145.9° | 0 | 0 |
| J4 | XMS5-R800-W4G3B4C_joint_4 | **+1.4469** | +82.9° | 0 | 0 |
| J5 | XMS5-R800-W4G3B4C_joint_5 | **+0.4349** | +24.9° | 0 | 0 |
| J6 | XMS5-R800-W4G3B4C_joint_6 | **-0.6977** | -40.0° | 0 | 0 |

### 机器人运行时话题 (验证通过)

| 话题 | 状态 |
|------|:---:|
| `/real_joint_states` | ✅ 真关节数据 |
| `/robot/joint_states` | ✅ |
| `/gripper_pos` | ✅ 夹爪位置 |
| `/robot/force_torque` | ✅ 六维力 |
| `/robot/tcp_pose` | ✅ 末端位姿 |
| `/robot_status` | ✅ 状态 |

### 控制器连接

| 项目 | 值 |
|------|-----|
| 控制器IP | 192.168.23.160 |
| 延迟 | 0.2ms |
| 模式 | 手动 |
| 电机 | 使能 |
