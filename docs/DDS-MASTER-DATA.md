# Z-MAX 具身智能主数据空间设计 v1.0

> 2026-08-02 · 小芳(硬件系统) · 工厂精细操作为核心场景

## 1. 主数据定义（Master Data）

**主数据 = 跨任务、跨时间稳定、被多方引用的权威数据。**
在工厂精细操作（光模块400G AOI插拔）场景，主数据分 6 类：

### M1 本体主数据（机器人）
```json
{
  "robot": {
    "id": "SR5-6DOF",
    "dh_params": "...",          // DH参数
    "joint_limits": [[-3.14,3.14], ...],  // 6关节限位
    "max_speed": 2.0,            // rad/s
    "max_accel": 5.0,
    "tcp_offset": [0,0,0.15],
    "gripper": {"type": "electric", "stroke": [0, 25], "max_force": 80}
  }
}
```

### M2 工位主数据（布局）
```json
{
  "workcell": {
    "id": "400gAOI-BL",
    "slots": {                    // 治具插槽 (状态机"移动到治具插槽"目标)
      "AOI_1": {"pose": [x,y,z,rx,ry,rz], "device_id": "AOI_1"},
      "AOI_2": {"pose": [...], "device_id": "AOI_2"}
    },
    "tray_pose": [x,y,z,...],     // 料盘位置
    "scan_pose": [x,y,z,...]      // 扫码位置
  }
}
```

### M3 工件主数据（光模块）
```json
{
  "part": {
    "id": "400g-module",
    "dimensions": [88, 18, 12],   // mm
    "mass": 0.12,
    "grasp_points": ["top_center"],
    "grasp_force": 25,            // N
    "insert_depth": 8.0,          // mm
    "insert_force_max": 30        // N (超限=插入失败)
  }
}
```

### M4 状态机主数据（流程定义）
```json
{
  "state_machine": {
    "id": "抓取放置",
    "start": "初始化循环",
    "states": [27个状态],         // 料盘识别/取料/扫码/插入/AOI_1-6...
    "transitions": {...},         // 转移表
    "entry_points": ["抓取位姿识别", "抓取放置"]  // ExecuteExternalTask 合法入口
  }
}
```

### M5 技能主数据（原子技能库）
```json
{
  "skills": {
    "取料":     {"stage": "取放", "type": "atomic", "params": {"grasp_force": 25}},
    "扫码":     {"stage": "取放", "type": "atomic", "params": {"scanner": "honeywell"}},
    "尝试插入": {"stage": "插入", "type": "atomic", "params": {"depth": 8, "force_max": 30}},
    "AOI检测":  {"stage": "检测", "type": "atomic", "params": {"project": "10082"}},
    "等待测试": {"stage": "完成", "type": "atomic", "timeout": 30}
  }
}
```

### M6 标定主数据（视觉/力）
```json
{
  "calibration": {
    "hand_eye": "相机到机器人变换矩阵",
    "camera_intrinsic": {...},
    "force_tare": [0.5, 0.2, -2.0]   // 力传感器零点
  }
}
```

## 2. 数据分层（主数据 vs 过程数据）

```
┌─────────────────────────────────────────────────────┐
│  L1 知识层 (Master Data, 版本化)                      │
│  M1本体 M2工位 M3工件 M4状态机 M5技能 M6标定           │
│  权威源: 07171产线配置 + 数据库, 修改需版本评审        │
├─────────────────────────────────────────────────────┤
│  L2 感知层 (实时过程数据, 水流式)                     │
│  关节/位姿/力/相机/夹爪/扫码/急停 — 持续刷写          │
│  存储: 时间序列, 采样 2Hz-30Hz                       │
├─────────────────────────────────────────────────────┤
│  L3 事件层 (执行结果)                                │
│  状态转移/任务完成/失败/耗时/力曲线峰值               │
│  存储: 事件日志, 保留全部历史                        │
├─────────────────────────────────────────────────────┤
│  L4 衍生层 (训练产物)                                │
│  模型权重/推理报告/评估指标/对比基线                  │
│  存储: 模型库 + 指标表                               │
└─────────────────────────────────────────────────────┘
```

## 3. DDS 全局数据空间（水流式刷写实现）

### 快照结构 (dds_writer.py 每秒/每2秒刷写)
```json
{
  "meta": {"writer": "orin_dds", "ts": 1785684437, "cycle": 10},
  "nodes": {                       // L1 状态: 各服务健康
    "gateway": {"running": true, "health": true},
    "infer": {"running": true, "model_size": 87576920, "infer_count": 0},
    "camera": {"running": true},
    "snapshot": {"running": true}
  },
  "topics": {                      // L2 感知层最新值
    "real_joint_states": {"position": [6D], "ts": ...},
    "tcp_pose": {"position": [x,y,z], "ts": ...},
    "force_torque": {"force": [3D], "torque": [3D]},
    "gripper_pos": {"pos": 0.0},
    "active_states": {"states": [27态], "current": "等待测试结果"},
    "active_transition": {"from": "AOI_6", "to": "等待测试结果"},
    "initialization_complete": {"value": true},
    "physical_estop": {"active": false}
  },
  "skills": {                      // L1 技能激活状态 (27个原子技能)
    "取料": {"stage": "取放", "active": false},
    "等待测试": {"stage": "完成", "active": true}
  },
  "flow": [                        // L3 水流轨迹 (最近50条)
    {"time": ..., "states": [...], "current": "AOI_3"},
    {"time": ..., "states": [...], "current": "等待测试结果"}
  ]
}
```

### 水流式刷写机制
```
Orin dds_writer.py (2s周期)
  ├── 订阅12个ROS2话题 (BEST_EFFORT QoS)
  ├── 采集6个服务状态 (gateway/infer/camera/snapshot/...)
  ├── 维护27个原子技能激活状态
  ├── 记录状态机流转历史 (flow, 最多50条)
  └── POST → ECS /api/dds/write (每2秒, 像水流持续刷写)
        ↓
ECS 存储: 最新快照 (L1) + 时间序列 (L2/L3)
        ↓
控制台 cicd.html: 实时渲染 (节点健康/感知值/技能灯/水流轨迹)
```

### 主数据管理方式
```
修改主数据 (M1-M6) → 走版本评审:
  1. 改配置 → 2. 本地验证(仿真) → 3. 推git → 4. 通知三方pull
  5. 部署前校验 (schema检查) → 6. 部署 → 7. DDS标记新版本
```

## 4. 原子技能 + 条件（映射到状态机）

| 阶段 | 原子技能 | 触发条件 | 前置条件 |
|:---|:---|:---|:---|
| 识别 | 料盘识别 | 初始化完成 | 视觉在线 |
| 识别 | 工件识别 | 料盘就位 | MechMind 200 |
| 取放 | 取料 | 识别成功 | 夹爪开 |
| 取放 | 扫码 | 抓取成功 | 扫描枪在线 |
| 插入 | 尝试插入 | 扫码完成 | 力传感器正常 |
| 插入 | 插入完成 | 力<30N&深度8mm | 无 |
| 检测 | AOI_1-6 | 插入完成 | AOI程序10082/10083 |
| 完成 | 等待测试 | AOI完成 | 无 |

## 5. 与三端职责对齐

| 端 | 主数据责任 | 过程数据 |
|:---|:---|:---|
| **小芳(Orin/Mac)** | M1本体/M2工位/M6标定维护, DDS聚合器 | 感知数据采集 |
| **xspace(4060)** | M4状态机/M5技能定义, 训练参数 | 训练产物 |
| **web(ECS)** | M3工件管理, DDS存储/控制台渲染 | 队列流转 |
