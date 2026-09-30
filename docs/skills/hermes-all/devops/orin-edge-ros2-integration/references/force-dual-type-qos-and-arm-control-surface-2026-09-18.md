# 力信号双类型话题 / QoS 坑 + 珞石机械臂控制面（2026-09-18 实测）

## 1. `/robot/force_torque` 是「同名双类型」话题 —— 力信号一直收不到的真因
现场该话题上同时有 **JointState** 与 **WrenchStamped** 两个发布者。

### 坑 A: 同一个 rclpy node 不能对同一话题名建两个不同类型的订阅
第二条订阅直接抛错（实测日志原文）:
```
>>> [rcutils|error_handling.c:108] rcutils_set_error_state()
This error state is being overwritten:
  'create_subscription() called for existing topic name rt/robot/force_torque with incompatible type
   geometry_msgs::msg::dds_::WrenchStamped_, at ./src/subscription.cpp:146'
with this new error message:
  'invalid allocator, at ./src/rcl/subscription.c:219'
rclpy._rclpy_pybind11.RCLError: Failed to create subscription: invalid allocator
```
⇒ 仓库旧注释把这条记成"本镜像的 WrenchStamped typesupport 建订阅即报 invalid allocator"是**误判**。
`invalid allocator` 只是第二层错误信息，真因是**同 node 同话题名不同类型的第二次订阅**。
（单独一个容器只订 WrenchStamped 完全正常 → 反证。）

后果（本次自伤记录）：把两条都加上 → tap 进程退出 → `ss-remote-tap.service` (Restart=always)
进 crash-loop（重启计数 18，~5s 一次）。修法 = **只留 WrenchStamped 一条** +
`systemctl reset-failed ss-remote-tap.service && systemctl restart ss-remote-tap.service`。

### 坑 B: QoS 必须 BEST_EFFORT
发布者 BEST_EFFORT；订阅写 RELIABLE 时 rclpy 只打一条警告就静默 0 条：
```
[WARN] [ft_probe]: New publisher discovered on topic '/robot/force_torque', offering incompatible QoS.
No messages will be received from it. Last incompatible policy: RELIABILITY
```
实测对照：RELIABLE → **0 条/4s**；BEST_EFFORT → **198 条/4.00s = 49.5Hz**。

### 判据与读法
- `ros2 topic hz /robot/force_torque` → `Cannot echo ..., as it contains more than one type` 类报错，**测不出频率**；
  一律**显式给类型**：`ros2 topic echo --once /robot/force_torque geometry_msgs/msg/WrenchStamped`
- `ros2 topic info -v /robot/force_torque` 能看到两个 SUBSCRIPTION 端点 + 各自 QoS → 先看这个再改代码
- 结论已落地 `tools/ss_remote_tap.py`：只订 `WrenchStamped(BEST_EFFORT)`；JointState 那条实测 **零发布消息**。
  将来若改回 JointState 发布，UI 会如实显示"缺(无发布者)"，不会填假值。

## 2. 只读探针（可直接复用；本机 Docker，Orin 零安装）
```bash
# 力信号 / 位姿 / 状态 三合一（BEST_EFFORT 显式类型）
cat > /tmp/probe.sh <<'EOS'
#!/bin/bash
export ROS_DOMAIN_ID=0; source /opt/ros/humble/setup.bash
python3 - <<'PY'
import json, rclpy, time
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from std_msgs.msg import String
from geometry_msgs.msg import PoseStamped, WrenchStamped
rclpy.init(); n = Node("probe"); out = {}
n.create_subscription(String, "/robot_status", lambda m: out.__setitem__("st", m.data),
    QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT, history=HistoryPolicy.KEEP_LAST))
n.create_subscription(PoseStamped, "/robot/tcp_pose",
    lambda m: out.__setitem__("pose", (m.pose.position.x, m.pose.position.y, m.pose.position.z, m.header.frame_id)),
    QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT, history=HistoryPolicy.KEEP_LAST))
n.create_subscription(WrenchStamped, "/robot/force_torque",
    lambda m: out.__setitem__("ft", (m.wrench.force.x, m.wrench.force.y, m.wrench.force.z,
                                     m.wrench.torque.x, m.wrench.torque.y, m.wrench.torque.z)),
    QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT, history=HistoryPolicy.KEEP_LAST))
t0 = time.time()
while time.time() - t0 < 5 and len(out) < 3:
    rclpy.spin_once(n, timeout_sec=0.2)
print(json.dumps(out, ensure_ascii=False, default=str)); rclpy.shutdown()
PY
EOS
sudo docker run --rm --network host -e ROS_DOMAIN_ID=0 -v /tmp/probe.sh:/probe.sh:ro ros:humble-ros-base bash /probe.sh
```
实测输出（2026-09-18）:
`tcp_pose=(0.74714, 0.08113, 0.44026, 'base_link')` · `ft=(3.801, 2.227, 1.446, 0.204, -0.244, 0.971)` ·
`robot_status={success, robot_mod=rokae, power_state=on, operation_state=drag, has_error=false,
 error_code="", error_reason="", estop_detected=false, collision_detected=false, collision_source="", stamp}`

## 3. 珞石 XMS5-R800 控制面盘点（只读核实，未下发任何运动命令）
| 项 | 值 |
|---|---|
| 驱动工作区 | Orin `~/0810/tashan_robot_so_20260807_174920_6983506_aarch64/install/`（另有 `tashan_hmi_so_*`）；**只有 install 产物**，src 为空 |
| 包 | robot_driver · motion · trajectory_planning · gripper · interfaces · external_comm · camera · vision · vision_pointcloud · vision_tag · robot_description · calibration_tools · tactile_force_bringup · obstacle_panel |
| 节点 | `/robot_driver` `/motion` `/gripper_driver` `/vision*` `/tactile_force_node` `/tower_light` `/hmi_v1_tashan_bridge` …（共 ~17） |
| 位姿真值 | `/robot/tcp_pose` PoseStamped, `frame_id=base_link`, **49.8Hz** |
| 关节 | `/real_joint_states` 100.2Hz · `/robot/joint_states` 44.8Hz |
| 力 | `/robot/force_torque` WrenchStamped **49.5Hz**（见 §1） |
| 状态 | `/robot_status` String(JSON) ~2Hz |
| 夹爪 | 服务 `/gripper_driver` (interfaces/srv/GripperSrv: target_pos/speed/force/acc/push_length/push_speed → curr_pos)；`/gripper_pos` 是**同名双类型**(Float32/Float64)，直订要显式类型，读数长期 1000.0 可疑占位 |

### 运动服务（robot_driver 提供，`interfaces/srv`）
`/move_pose` `/move_line` `/move_joint` `/joint_and_pose` `/real_joint_and_pose` `/sim_joint_and_pose`（均 `TargetPose`：
`float32 speed` + `sensor_msgs/JointState` + `geometry_msgs/Pose` → `success/message/error_code`）·
`/move_sequence`(`MoveSequence`: move_types[] + poses[] + joint_states[] + speeds[] + zones[]) ·
`/robot_stop`(Trigger) · `/rokae_recover_estop`(Trigger) ·
**力控插装** `/rokae_insertion_force_search`(RokaeInsertionForceSearch: frame_type/load/cartesian_stiffness/
cartesian_max_vel/lissajous_*/search_force/search_box/calibrate_force_sensor) 与 `/lissajous_force_search`。
（另有 motion 侧状态机入口 `/run_single_state` `/run_graph_unit` `/execute_external_task` `/start_with_external_cmd`
`/state_machine/*` `/target_joint_state` `/target_relative_joint(s)` —— 产线自己的编排层，别乱调。）

### SDK
ROKAE xCore SDK python 桩可直读（非 .so，是 `.pyi`）：
`…/robot_driver/lib/python3.10/site-packages/robot_driver/rokae/xcoresdk_python/Release/linux/xCoreSDK_python/`
`{__init__, model, motioncontrolRT, planner, servo, utility, RtSupportedFields}.pyi`
关键方法：`PyRTmotioncontrol6.MoveL(speed, start: CartesianPosition, target)` / `MoveJ` / `MoveC` ·
`setControlLoop(callback)`（Joi/Car/Tor 三种，可做实时伺服）· `setCartesianImpedance` ·
`setCartesianImpedanceDesiredTorque` · `setLoad` · `setCollisionBehaviour` · `setFcCoor` · `setEndEffectorFrame`。
⚠️ 驱动本体 `main.cpython-310-aarch64-linux-gnu.so` 是编译过的，**读不到业务逻辑源码**，只能靠 srv/msg 契约与 pyi 反推。

### 安全姿势（老倪红线 + 本次现场状态）
- `/robot_status` 的 `operation_state`：`idle` = 空闲可动；**`drag` = 有人正在手动拖动示教** → 此刻下发运动命令会跟人抢。
- 首次打通用 **zero-risk 路径**（`/sim_joint_and_pose` / sim_mode 通道）证明命令链路通；
  再经**用户明确 GO** 发微小可逆真动作（如 `move_line` 沿 z 1mm 再回原位），现场按住急停。
- 端口扫描**不是**连通性判据：8055/8056/9000/30001 全 closed，但 SDK 连接已由 robot_driver 占用
  （判据 = `ping`/`ip neigh` REACHABLE + `/robot/tcp_pose` 有 50Hz 真值）。
- 我方（4060）只做 DDS 只读订阅；执行永远在 Orin 侧收口。

## 4. 服务语义提醒（本次踩到）
「状态文件还在被写」**不等于**服务在跑：crash-loop 期间 `~/zmax_ss_remote/status.json` 仍显示上一进程留下的计数，
`state_*.jsonl` 的 mtime 也会停在死前那一秒。判据：
`systemctl status <unit> | grep -E "Active|Result|Main PID"` + `sudo docker ps -a` + 计数是否**在增长**。
