# `/move_sequence`: 连续无停顿多路点运动 (payload 模板 + 逐腿路点 + 客户端形态)

用途: 现场要求"中间不能有停顿 / 不要走一下停一下"。逐段调 `/move_line` 时**每段一次服务握手**
(实测 3~10s)就是用户看到的"停顿"，是协议决定的，不是脚本在等。

## 接口 (从边缘机源码环境读)
```
$ ssh <user>@<orin> 'cd <ws> && source /opt/ros/humble/setup.bash && source install/setup.bash && \
    ros2 interface show interfaces/srv/MoveSequence'
  string[] move_types                  # 'line' | 'pose' ('joint' 需该段 joint_states 非空)
  geometry_msgs/Pose[] poses
  sensor_msgs/JointState[] joint_states  # 长度必须与 move_types 相同
  float32[] speeds                     # 每段速度(与 /move_line 同量纲, 见速度标定表)
  float32[] zones                      # 每段过渡圆角(blend) —— 连续性的来源
  ---
  bool success
  string message
```
- ⚠️ 只能在**装了 `interfaces` 包的机器**上调。主机容器里调报 `The passed service type is invalid`,
  是缺消息包，不是服务不在。
- ⚠️ `'move_line'` 非法 → `第 N 段 type 非法`; `joint_states` 个数不匹配 → `数组长度必须一致`。

## 最小 payload
```bash
JS="{name: [], position: [], velocity: [], effort: [], header: {stamp: {sec: 0, nanosec: 0}, frame_id: ''}}"
ros2 service call /move_sequence interfaces/srv/MoveSequence \
"{move_types: ['line','line'],
   poses: [{position: {x: 1.0, y: 2.0, z: 3.0}, orientation: {x: qx, y: qy, z: qz, w: qw}},
           {position: {x: 1.1, y: 2.0, z: 3.0}, orientation: {x: qx, y: qy, z: qz, w: qw}}],
   joint_states: [$JS, $JS], speeds: [500.0, 300.0], zones: [0.002, 0.002]}"
```
- 同一条腿里**所有路点用同一个四元数**(照抄当前 TCP 的 quat) ⇒ 纯平移不转姿态。
- `speeds` 与 `/move_line` 的 `speed` 同量纲(≈0.1mm/s 每单位: 500 ≈ 50mm/s)。
- 长腿(>30s)先回 `success=False (ROBOT_IDLE_TIMEOUT)` **而臂继续走完** ⇒ 只看 TCP 真值, 绝不重发。

## 逐腿路点模板: (退)升 → 移 → 落
```
去目标位(起点在孔口/插口里时含"先沿轴后退"):
  [起点x-0.050, 起点y, 起点z] → [起点x-0.050, 起点y, SAFE] → [目标x, 起点y, SAFE]
  → [目标x, 目标y, SAFE] → [目标x, 目标y, 目标z]           (5 段)
回起点(到位即停, 不推进):
  [目标x, 目标y, SAFE] → [起点x, 目标y, SAFE] → [起点x, 起点y, SAFE] → [起点x, 起点y, 起点z]  (4 段)
```
- 所有横移都发生在 `SAFE` 高度上，末段才是纯竖直下落 —— **绝不走低空斜线**(实测会把相邻工装带倒,
  控制器报碰撞/柔顺停止)。
- 所有路点给**绝对坐标**，不要相对位移累加(相对累积会漂)。

## 两种客户端形态
- **循环放边缘机**(一个 ssh 会话里发 N 条请求, 比本机逐条 ssh 快一个量级)：循环里自己订阅机器人 TCP 判到位
  —— `QoSProfile(reliability=ReliabilityPolicy.BEST_EFFORT)`(这类话题是 BEST_EFFORT, 默认 RELIABLE 收不到)。
- **本机脚本发单腿**: 到位轮询 0.4~0.5s, 超时预算按距离算(别写死小值), 不达标**立即 `exit 1`**, 带疑点不往下走。
- 到位判据要与动作同源: 平移看位置, **姿态看 quat**(纯姿态动作拿位置当判据永远为真 = 假 ✅)。
