# Orin 真机工序知识库

> 2026-07-13 · 小芳现场采集 · 100G AOI 光模块产线

## 工序 Pipeline 速查

### 1. 抓取位姿识别
```
JointAndPoseServer → QuatAndEuler(q2e) → MechVisionClient(192.168.23.26) → QuatAndEuler(e2q) → CollectionResponse
```

### 2. 取料
```
PoseTranslateLocalOffset → BuildMoveSequence → MoveSequence → SetGripperPosition
```

### 3. 力控插入 (核心竞争力)
```
GetTaughtPose(pose_9) → Z-0.06m预插入 → MoveSequence → LissajousForceSearch
  - Fz=6N, XY刚度6000, Z轴柔顺=0
  - 3Hz×2Hz 利萨如曲线, ±10mm搜索框
  - 超时2s, 力稳定0.1s
```

### 4. 拔出+AOI
```
Z-0.12m拔出 → mid_pose24 → mid_pose14(拍照位) → MoveSequence
→ HTTP POST 192.168.23.26:10082/capture_detect
```

### 5. AOI 6工位检测
```
AOI_1→6 逐检 + NG标志位累计
最终: flags>0 → AOING分拣, else OK
```

### 6. 容错机制
```
抓取: 触觉力<5N → 开爪重试 → 3次报错
插入: 深度<0.75m → 二次尝试
AOI: 单工位失败 → 标志位+继续
NG: 双料盘轮换 (manual_pose_25/26)
```

## 关键IP
| 设备 | IP | 端口 |
|------|------|:---:|
| 珞石控制器 | 192.168.23.160 | 8051 |
| Orin主控 | 192.168.23.10 | — |
| Orin虚拟IP | 192.168.23.66 | — |
| Mech-Mind视觉 | 192.168.23.26 | 10082 |
| Mac监控 | 192.168.23.1 | — |

## 安全阈值
| 参数 | 值 |
|------|:---:|
| 力控Fz | 5N 急停 / 6N 插入目标 |
| 夹爪力 | 40N |
| 触觉抓取力 | >5N 合格 |
| 插入深度 | >0.75m |
| 运动速度 | 4000mm/s |
| 关节限位 | ±3.0 rad |
