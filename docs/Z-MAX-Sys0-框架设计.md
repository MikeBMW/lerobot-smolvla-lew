# Z-MAX Sys-0 · L2基线版框架设计

> 总工: @xspace 静静 | 审核: @xspace | 版本: v1.0.4

## 一、定位

Z700F固定式精密插拔产线。纯ROS2 Service规则引擎，无AI模型。Orin Nano 8GB部署。

## 二、架构

```
┌─────────────────────────────────────────────┐
│              Sys-0 规则引擎                   │
│                                             │
│  Orin Nano (Jetson, 40TOPS, 8GB)            │
│  ├── ROS2 Domain 23                         │
│  │   ├── /zmax/sys0/insert_sequence (Service)│
│  │   ├── /zmax/sys0/emergency_stop (Service) │
│  │   ├── /zmax/sys0/light_curtain (Topic)   │
│  │   └── /zmax/sys0/tower_light (Topic)     │
│  ├── MCU TC397 (ASIL-D safety)              │
│  └── 双臂机械臂 (珞石SR5-C, 6-DOF×2)         │
└─────────────────────────────────────────────┘
```

## 三、通信协议

### 3.1 插拔工序Service

```
Service: /zmax/sys0/insert_sequence
Request:
  string module_type    # "800G_OSFP" | "400G_QSFP" | "100G_QSFP28"
  int32  slot_number    # 1-12
  bool   auto_scan      # 是否自动扫码
Response:
  bool   success
  string barcode        # 扫码结果
  float32 insertion_force_n  # 插入力(N)
  float32 duration_s         # 耗时(s)
```

### 3.2 紧急停止Service

```
Service: /zmax/sys0/emergency_stop
Request: (empty)
Response: bool success  # 所有电机断电 <10ms
```

### 3.3 光幕Topic

```
Topic: /zmax/sys0/light_curtain
Type: std_msgs/Bool
Frequency: 50Hz
True → 有人进入 → 降速 → 停机
False → 安全区域
```

### 3.4 塔灯Topic

```
Topic: /zmax/sys0/tower_light
Type: std_msgs/Int8
0=关机, 1=运行(绿), 2=待机(黄), 3=故障(红闪)
```

## 四、接口规范

### 4.1 与Sys-1接口

```
Sys-0 → Sys-1: ROS2 Action /zmax/sys1/invoke
  goal: {engine: "act"|"vtla"|"groot", task: json}
  feedback: {progress: 0-1.0, status: string}
  result: {action: float[7], success: bool}
```

### 4.2 与仿真桥接口

```
仿真桥 → Sys-0: gRPC (orin_sim_bridge.py)
  /send_joint_cmd → 关节控制
  /get_joint_state → 关节反馈
  /get_force_torque → 力传感器
```

## 五、硬件映射

| 硬件 | ROS2 Topic | 接口类型 |
|:--|:--|:--|
| 光幕 | /zmax/sys0/light_curtain | Topic 50Hz |
| 急停 | /zmax/sys0/emergency_stop | Service |
| 塔灯 | /zmax/sys0/tower_light | Topic 1Hz |
| 机械臂 | /left_arm/joint_states, /right_arm/joint_states | Topic 100Hz |
| 夹爪 | /left_gripper/state, /right_gripper/state | Topic 50Hz |
| Realsense | /camera/color/image_raw | Topic 30Hz |
| IO | /io/status | Topic 10Hz |
| 传送带 | /conveyor/control | Topic 10Hz |

## 六、安全层级

| 层级 | 机制 | 响应时间 | 触发条件 |
|:--|:--|:--|:--|
| L1 | 双路急停按钮 | <10ms | 人工按下 |
| L2 | 光幕联动 | <50ms | 人员进入 |
| L3 | 力控阈值 | <1ms | 插入力>5N |
| L4 | 软件限位 | <1ms | 关节超限 |
| L5 | MCU独立监控 | <1ms | 任何异常 |

## 七、验收标准

- 急停响应 <10ms ✅
- 光幕联动 <50ms ✅
- 插拔精度 ±0.05mm
- 单次节拍 <25秒
- 连续运行 8h 无故障

## 八、代码位置

- 规则实现: `hermes_gateway_mac/sys0_safety.py`
- 仿真桥: `hermes_gateway_mac/orin_sim_bridge.py`
- ROS2节点: (小芳Orin端)
