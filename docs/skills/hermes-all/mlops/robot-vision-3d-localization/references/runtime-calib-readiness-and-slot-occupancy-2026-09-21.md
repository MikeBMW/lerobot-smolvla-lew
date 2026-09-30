# 运行时标定就绪性 + 槽位占用判定 + 夹爪读数坑 (2026-09-21 实测)

老倪现场要求：**"通过感知判断一号位和二号位哪个有光模块，有就开始抓取"** —— 结论：感知链**没接通**，
断点在运行时标定文件，不在检测器。下面是当天真实取证与替代路径。

## 一、运行时标定就绪性（规划前必查，一条命令）

| 检查 | 命令/文件 | 2026-09-21 实测 |
|---|---|---|
| 运行时标定配置 | `models/real_cam_calib.json` | `ready=true`，但 `T_base_cam = null`、`plane_z = null`（只有 K + dist） |
| 解算报告 | `~/zmax_data/calib_report_20260919_065943.json` | `已标定 = False`、`手眼 = None`、`留出残差px = None` |
| 计划文档声称 | 动作计划里写 `calibration/cgb020/camera_extrinsic.yaml` ✅在位 | **该文件全盘 find 不存在**（`find / -name "*cgb020*"` 只命中计划 md 自身） |
| 会话采集 | `~/zmax_data/handeye/20260919_*`（11+ 组） | 采集目录在，但解算没成功 → 采集 ≠ 可用 |

⇒ 教训：**计划文档与"已验证"的 references 会过期**；判据只能是运行时配置字段本身。

## 二、缺外参时怎么判"哪个槽位有工件"（零外参替代路径）

eye-in-hand + `槽位示教点 = 抓持工件那一刻的 TCP 位姿` ⇒ **站到该槽位上方取帧，工件必落画面中心附近**。
- 判据：到 A 位正上方（示教点 +30mm）取帧 → 检测器判有无 → 有就抓、无就去 B 位。
- 真机实测（当天）：YOLO 在役权重 `models/yolo_peg_live.pt`，`cam_rs.png` 640x480，帧龄 ~1.3s，
  检出 **1 个模块 conf 0.77 框 [379.5, 12.0, 428.5, 130.8]**（09-20 同场景曾检出 2 个 → 数量要按当场帧算，
  不能引用旧值）。落盘：`~/zmax_data/ss_bypass/yolo_detections.json`。
- 已知不可用的两条岔路（当天试过）：
  * 拿画面方向硬凑槽位编号 → 现场画面 180° 翻转 + 无外参 = 纯猜（禁用）。
  * 读产线 `/camera_driver/module_status`（type `camera_driver/msg/CameraModuleStatus`，pub=1）→
    `camera_driver` 包**不在** Orin 工作空间（`install/` 里只有 `camera`），source 该工作空间后
    `ros2 topic echo` 仍报 "message type is invalid"，find 不到 `.msg` ⇒ 发布者在别的机器上，
    要读得先拿到该包的 msg 定义。

## 三、夹爪真值读法（这轮现场确认）

- 服务回执才是真值：`L2.grip_open` 下发后日志出现
  `interfaces.srv.GripperSrv_Response(curr_pos=1000.0)` ⇒ 松开成功（"已下发"三个字不算完成）。
- 读数话题有**双类型**坑：`/gripper_pos` 同时挂 `std_msgs/msg/Float32`（产线夹爪驱动）与
  `std_msgs/msg/Float64`（我们自己 tap 订的）→ 裸 `ros2 topic echo` 报
  "contains more than one type"，必须显式带类型：`ros2 topic echo --once /gripper_pos std_msgs/msg/Float32`。
  类型不匹配也是采集里 `recv.grip` 恒 0 的原因（不是没数据）。
- 口径（历史实测）：松开 = 1000；空载夹紧 ≈ 21；夹住光模块 ≈ 185。

## 四、当天的动作闸门状态（可复用为"发车前检查"）

- 三查 `/robot_status`：`power_state=on` / `operation_state=idle` / `has_error=false` ✓
- DRY-RUN 先给数（零指令）：`L2.slot1` 阶段1 → 目标 (0.6471, 0.5026, 0.1435)，
  Δ=(+163.1, +75.2, -127.7)mm ↓，直线 220mm，speed 30，到位上限 141s，位姿来源 direct。
- 未获"确认，动作"之前**不发真指令** —— 逐条请示是现场硬规矩。
