---
name: ros2-cross-machine-control-loop
description: "Use when splitting robot control loop across edge and host."
version: 1.0.0
author: Hermes Agent
license: MIT
tags: [ros2, robot, edge, deployment, control-loop, docker]
platforms: [linux]
---

# 跨机机器人控制闭环（边缘采集/收口 ↔ 主机推理）

**触发**: 现场机器人（Orin 等边缘机）与训练/推理主机在同一局域网，要把「采集 + 执行」放边缘、
「模型推理」放主机；或用户问"能不能做成两个 ROS2 节点"。2026-09-16 在 Z-MAX（Orin XMS5-R800 ↔ 4060）实测落地。

## When to Use
- 要把一个**已经在跑的产线机器人系统**接上自己的模型，但**不能接管**它（先旁路/影子）。
- 边缘机与主机同网段（实测 0.5ms RTT），想让 DDS 直接跨机，而不是绕公网 relay。
- 需要给"模型输出 → 机器人动作"加一道**收口闸门**（阶段白名单 / 方向 / 幅值 / 超时）。

## 0. 先确认的三条硬约束（不确认就白做）
1. **边缘机上能不能装软件？** Z-MAX 现场红线 = **不在 Orin 装新软件**（主机可随意装）。
   ⇒ 边缘节点只能用已装的 `rclpy`；想用 `rclcpp` 得先确认 `ls /opt/ros/<distro>/include/rclcpp` 在，
   否则 `apt-get install ros-humble-rclcpp-dev` 这类包可能根本不存在（实测该源 `E: 无法定位软件包`）。
2. **两边 ROS 发行版/OS**：边缘常见 JetPack/22.04 + Humble；主机可能是 24.04 + 无 ROS。
   ⇒ 零兼容风险做法 = 主机用 **Docker `ros:humble-ros-base` + `--network host`** 当 ROS 桥，
   **模型留在主机 venv**（torch/CUDA 不动），两边只通过 `127.0.0.1` HTTP 说话。
   不要在主机上装另一个发行版去和边缘跨版本对话。
3. **`ROS_DOMAIN_ID` 两边必须一致**（现场常为 **0**）。用错的 domain 只会看到 `/rosout`，
   极易误判成"机器人驱动没起"。先两边各跑 `ros2 node list` 确认能看到对方节点名。

## 1. 拓扑（实测可跑）
```
边缘(Orin)  ss_edge                                主机(4060/工作站)
 订阅真机信号(只读)                                 ┌─ ss-bridge  跑在容器 ros:humble-ros-base --network host
 ──/xxx/state (std_msgs/String, JSON, 10~20Hz) ──▶ │   收 state → HTTP 127.0.0.1:8790/infer
 ──/xxx/action (同类型, 回程) ◀─────────────────────┤   → 发 action
 闸门判决 + jsonl 记录（默认只记录不下发）           └─ infer server 跑在 venv（真权重, GPU）
```
- **话题类型用 `std_msgs/String` 装 JSON**：跨机/跨发行版最省事、字段可演进，不必自定义 msg（要装包 + codegen）。
- 状态报文带**产线阶段/序号/时间戳**；回程报文**回带 stage + 输入口径字段**，
  这样边缘闸门才能判阶段白名单，也能一眼看出"这份提案基于什么口径算出来的"。
- 命名空间隔离（`/<项目>/state`、`/<项目>/action`）本身就是"只读"的证明方式之一。

## 2. CPU 代价模型（Python rclpy，实测 60s 稳态，单核口径）
| 配置 | CPU |
|---|---|
| 只订阅不动（无回调处理） | ≈13.7% |
| 全量 5 路（关节 49.5Hz + 力 50Hz + 夹爪 12Hz + 状态 2Hz + 阶段 1Hz）+ 20Hz 上行 | ≈18.2% |
| MIN 订阅（关节 + 夹爪 ≈62 msg/s）+ 20Hz 上行 | ≈12.9% |
| MIN 订阅 + 10Hz 上行 | ≈10.0% |
- **开销主要在 DDS 逐条派发 ≈0.15% 单核 / 每 msg/s**；`raw=True` 与普通订阅只差 3~4 个点，
  把反序列化挪到低频 tick 只省 ~0.3 个点 ⇒ **降载只能靠"少订阅 / 降上行频率"**，优化回调代码没用。
- 若现场有"我方服务 <8% 单核"这类红线：① 让产线侧发一个 ≤10Hz 的聚合状态话题（最省）
  ② 只订阅必需的一两路 ③ C++ 重写（需 rclcpp 头）。
  **红线没达标要如实上报，并给出"占几核机器百分之几"的换算**，别偷偷放过。

## 3. 必踩的坑（都实测过）
1. **高频话题用 `raw=True`**：回调只存字节，`deserialize_message(bytes(m), Type)` 放到低频 tick。
2. **ssh 里起后台进程必须先 source ROS**：漏了会得到 `ModuleNotFoundError: No module named 'rclpy'`
   （极易误读成"ROS 坏了"）。把启动写成脚本（`start_*.sh`）scp 过去，别在引号里现编。
3. **rclpy 被 SIGTERM 抛 `ExternalShutdownException`（不是 KeyboardInterrupt）** →
   `except (KeyboardInterrupt, ExternalShutdownException)`，退出时 `if rclpy.ok(): rclpy.shutdown()`，
   否则日志被 `rcl_shutdown already called` 噪声刷屏。
4. **pkill 自匹配**：只要**同一条命令行里别处**出现明文进程名（典型：同一条命令里带
   `python3 tools/xx_node.py` 的启动/查看语句），即使写了 `[x]` 方括号技巧**照样命中自己** →
   ssh 退出码 255、后续命令全不执行。⇒ **杀与起必须分两次调用**；量 pid 用
   `ps -eo pid,comm,args | awk '$2=="python3" && /xx_node/ {print $1}'` 过滤掉 bash 自己。
5. **`ssh host 'bash -lc "…"'` 里的 echo 不能带括号/花括号**（`echo === 自检 (dry) ===` 直接 bash 语法错误）。
   远程复杂逻辑 → 写成脚本文件 scp 过去再跑。
6. **同名节点别跑两个**（手工实例 + daemon 实例）：DDS 会合并、订阅开销翻倍、日志互相污染。
7. **幂等守护脚本**：`daemon.sh` 里 `pgrep -f "[x]x_node.py"` 命中就跳过；`setsid nohup … > log 2>&1 < /dev/null &`。
   kill 后要等 3~5s 再调 daemon，否则它会看到"没死透"的进程而跳过启动（实测踩过）。

8. **订阅到 0 帧先想 QoS**：边缘机上的 `/robot/tcp_pose`、图像话题多为 **`BEST_EFFORT`**；
   主机侧默认 RELIABLE 订阅 ⇒ **一帧都收不到**。`rclpy` 里显式
   `QoSProfile(reliability=ReliabilityPolicy.BEST_EFFORT)`。判活不能只看 `ros2 topic list`。
9. **话题列得出但 0 帧（BEST_EFFORT 也是 0）⇒ 查边缘节点进程是否已死**：
   边缘 `launch.log` 里 `process has died ... exit code -11`（实测相机节点段错误）。
   此后话题名/类型都还在、数据永远不会来 ⇒ 结论落在"重启那个节点"，不是继续调订阅参数。

## 3.5 让边缘一次走完整条轨迹：`/move_sequence`（别逐段调服务）
循环放边缘之后，"为什么中间还要停一下"的答案在协议：**每段一次 service 调用 = 每段一次握手**，
实测每次 3~10s 的空档，用户看到的就是"停顿"。要连续就**一次请求带整串路点**：
- `/move_sequence`(`interfaces/srv/MoveSequence`): `move_types[]`(**只认 `'line'` / `'pose'`**，
  传 `'move_line'` 直接拒) · `poses[]` · `joint_states[]`(**长度必须与 move_types 相同**，
  空项放空 `JointState()`) · `speeds[]` · **`zones[]`(过渡圆角 = blend，连续性的来源)**。
- **服务必须在装了消息包的机器上调**(边缘的源码环境)。主机容器里调会报
  `The passed service type is invalid` —— 不是服务不在，是主机没装 `interfaces`。
- **至少 2 段，且首段要有真实位移**：单段序列、或"位置相同只改姿态"的段会被驱动**整段跳过** ——
  现象是臂不动/调用挂住而日志一切正常。原地改姿态走 `/move_pose`。
- 边缘服务内 `wait_until_idle` 只等 **30s**：长轨迹会先回 `success=False (ROBOT_IDLE_TIMEOUT)`
  **而动作继续走完** ⇒ **只按真值(机器人 TCP)判完成，绝不重发**(重发 = 叠第二个动作)。
- 实测口径：一条请求 4~5 段、单腿 12.5~14.0s、落点偏差 0.01~0.46mm、20 腿零重试。
- payload 模板 / 逐腿路点 / 客户端形态：`references/move-sequence-continuous-motion.md`

## 4. 旁路（影子）运行：只记录、绝不下发
先跑通"只读链路"再谈控制（纪律 + 安全）：
- 边缘节点只订阅真机话题，**不发布任何控制话题、不调用任何服务**；
- 回程提案**只落 jsonl + 日志**，字段里显式写 `executed=False`；
- 证明只读：`ros2 node info <edge_node>` 的 Publishers 只应有自身 telemetry + `/rosout` + `/parameter_events`；
- 顺带确认产线话题没被扰动（如 `/robot/joint_states` 仍 49.8Hz）。

## 5. 执行闸门（收口在最下层）
原则：**上层只给意图，执行由最下层收口，可行域逐层收窄**；闸门放在**离执行最近的边缘机**，主机只发提案。
判据（env 可配）：
- 阶段白名单 `*_STAGES`（如 接近/对位/转移）—— 下降/抓取/插入/拔出 交回执行层；
- 方向一致度 `cos ≥ *_COS_MIN`（0.9；实测 0.5~0.85 仍会滑脱）；
- 幅值上限 `≤ *_MAX_MAG × 参考`（收窄不放大）；
- 提案超时 `> *_STALE_MS`（300ms）→ 否决（陈旧提案比不动更危险）；
- **真机静止（|v|≈0）时不允许非零提案**（无可信参考 ⇒ `veto_noref`）；
- **默认 `*_ARM=0`（disarmed）= 只判决不下发**；放权显式开，每条记录带 `executed=False`；
- verdict 分类计数（`disarmed/pass_no_exec/veto_stage/veto_dir/veto_mag/veto_stale/veto_shape/veto_noref`）逐条落 jsonl。
- **判据必须可被确定性验证**：写注入器往 action 话题喂构造提案（正常 / 方向反向 / 幅值×20 / 时间回溯 5s /
  阶段越界 / 维度不足），再从 jsonl 汇总"用例 → verdict"是否逐条命中。现场机械臂静止时方向/幅值判据
  **没有参考**，需要"仅测试用"的参考注入钩子（如 `*_REF_VEL`，默认不设）。
- **循环里的检查必须硬中止**：任何"抬升/到位没达标"的分支都要 `exit 1` 停手，绝不"打印警告继续跑" ——
  实测那样会让后续横移在**小高度上扫过相邻工装**，造成真碰撞（控制器报关节外力超限 / 柔顺停止）。
  带疑点往下走比停手危险得多。
- **判据要与动作同源**：纯姿态动作拿"位置 == 目标"当判据会**永远为真**（位置本来就不变）；
  姿态动作必须比 `quat`。假 ✅ 比没有判据更坏。
- **走位路线由最下层写死"升 → 安全高度横移 → 竖直下落"**：不要生成"当前位置 → 目标"的低空斜线 ——
  实测低空斜线把相邻工装带倒。起点在孔口/插口内时还要先**沿轴后退退开再升**。

## 6. 诚实标注纪律（不许伪装成已标定）
- 模型输入若依赖现场缺失的量（如 TCP 笛卡尔位姿、现场几何），就用**可用真机量按固定位置投影**填，
  但必须：① 响应/记录回传 `input_map: "placeholder_v0"` 这类口径字段；② 映射**只集中在一个函数**
  （标定完成后只改它）；③ 报告明说"放权前必须先做这步标定"。
- "真权重前向" ≠ "可用决策"：数值是真的，口径没标定就不能当控制用 —— 两句话要同时说清楚。

## 7. 服务化 / 自启
- 主机侧：`ss-<x>-infer.service`（User=<user> + venv python）与 `ss-<x>-bridge.service`
  （`Requires=docker.service` + `--network host` + `ExecStartPre=-docker rm -f <name>`），
  单元落库到仓库 `tools/systemd/`；`systemctl enable --now` 后复核 `is-active` + 容器日志确有回传帧。
- 边缘侧：`crontab @reboot … <x>_daemon.sh`（幂等）+ 记录目录 `~/.<项目>/<链路>/{state,action,gate}_<日期>.jsonl`。
- 启动/守护脚本都要落库或落盘，避免"只有现场那台机器能跑"。

## 关联
- 直连边缘机局域网的网络层配置（USB 网卡/静态 IP/不放默认路由/地址表）见 `orin-lan-direct-access`。
- 同族闸门思路在"模型直驱"路径的等价实现（阶段白名单 + cos 门槛 + 否决步交回引擎）见 zmax-console
  的「L4 档直驱收口闸」章节。
