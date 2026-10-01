# MoveIt2 只规划(plan-only)接入配方

适用: 画布上的 🧭 MoveIt 节点(`n_moveit`)该负责出轨迹, 但要**只规划不执行**, 并且能用真机目标位姿复算。

## 0. 先确认"它到底跑没跑过"
```bash
sudo docker ps -a --format '{{.Names}} | {{.Image}} | {{.Status}}'   # 有 moveit 容器吗
sudo docker images | grep -i moveit                                  # 镜像建过吗
find . -maxdepth 4 -iname "*moveit*"                                 # 配置/URDF/launch 齐吗
```
容器/日志/轨迹产物**三者都没有** ⇒ 结论是「从没跑过」, 别把"画布上有节点"当成"规划能力已在"。

本机形态(不动 Orin): 镜像是本机构建的 `docker/moveit/Dockerfile`(ros:humble + moveit2); 配置由
`tools/gen_moveit_config.py` 从**产线 URDF** 生成 SRDF / kinematics / joint_limits / OMPL +
`launch/plan_only.launch.py`(内含 `allow_trajectory_execution: False`)。

## 1. 起服务: 与产线 ROS 隔离 + 保证"不可能动"
```bash
sudo docker run -d --name zmax-moveit --network host \
  -e ROS_DOMAIN_ID=42 -e ZMAX_MOVEIT_CFG=/ws/moveit_cfg \
  -v <repo>/config/moveit_xms5:/ws/moveit_cfg:ro zmax-moveit:humble \
  bash -lc 'source /opt/ros/humble/setup.bash && exec ros2 launch /ws/moveit_cfg/launch/plan_only.launch.py'
```
- `ros2 launch` 可以直接吃**文件绝对路径**, 不需要做成 ROS 包。
- 参数里必须有 `allow_trajectory_execution: False` —— 这是"只规划"的硬保证, 报告里要明写。
- **另起一个 `ROS_DOMAIN_ID`**(产线是 domain0): 本地规划容器不必进产线 ROS 图。
- 就绪判据: 日志出现 `You can start planning now!` 且 `ros2 node list` 里有 `/move_group`。
- launch 里把 URDF 作为**字符串参数**注入时, mesh 的相对路径按进程 CWD 解析 ⇒ 注入前把
  `filename="meshes/…"` 换成**绝对路径**(否则 7 个 mesh 全报错)。

## 2. 取真机状态: 必须用 BEST_EFFORT 订阅
真机话题(`/robot/joint_states`、`/robot/tcp_pose`)发的是 **BEST_EFFORT**, 默认(reliable)订阅永远收不到,
日志只给 `offering incompatible QoS … Last incompatible policy: RELIABILITY`。
定式 = **两种 QoS 各订一次, 谁先到用谁**; 一次只订一种会得出"话题没数据"的假结论。

## 2b. 两个可复用入口(2026-09-29 已落仓库) + 容器写入坑
```bash
# ① 抓真机当前状态(跑在 **domain0 容器** ss-remote-tap / zmax-arm-raw; /repo = 仓库 tools/ 或仓库根)
sudo docker exec ss-remote-tap bash -lc 'source /opt/ros/humble/setup.bash && \
    python3 /repo/tools/moveit_real_state_probe.py --out /tmp/real_state.json --seconds 14'
sudo docker cp ss-remote-tap:/tmp/real_state.json reports/moveit/real_state.json

# ② 同源闸(跑在 zmax-moveit, domain42)
sudo docker cp tools/moveit_same_source_check.py zmax-moveit:/ws/
sudo docker cp reports/moveit/real_state.json zmax-moveit:/ws/real_state.json
sudo docker exec zmax-moveit bash -lc 'mkdir -p /ws/out; source /opt/ros/humble/setup.bash && \
    python3 /ws/moveit_same_source_check.py --state /ws/real_state.json \
      --rename-prefix XMS5-R800-W4G3B4C_ --out /ws/out/same_source_check.json'
sudo docker cp zmax-moveit:/ws/out/same_source_check.json reports/moveit/same_source_check.json
```
- **直接 `python3` 会 `ModuleNotFoundError: No module named 'rclpy'`** ⇒ 必须 `bash -lc 'source /opt/ros/humble/setup.bash && …'`。
- 🔴 **容器里的仓库挂载可能是只读**(实测 `OSError: [Errno 30] Read-only file system: '/repo/reports/…'`)
  ⇒ 容器内一律写 `/tmp`, 再用 `docker cp` 拷回宿主仓库; 别把"写不进去"当成权限/路径写错。
- 同源闸脚本产出**独立证据 JSON**(`pos_err_mm` / `ori_err_deg` / `verdict` / 真关节原值 + 来源),
  退出码 5 = 不同源 ⇒ 可直接被 CI/守护当门禁用。

## 3. 只规划用到的服务
| 目的 | 服务 | 关键参数 |
|---|---|---|
| 起点关节 | `/compute_ik` | 有真关节就直接喂真关节当起状态, 不要 IK 猜 |
| 规划 | `/plan_kinematic_path` (`GetMotionPlan`) | 目标给 position + orientation 约束, `planner_id=RRTConnect`, `allowed_planning_time=10`, 速度缩放 0.2 |
| 出 TCP 折线 | `/compute_fk` | 逐关节路点 FK ⇒ 折线交给叠加层画 |

可复用入口: `tools/moveit_plan_only.py`(`--start-joints` 喂真关节, `--rename-prefix` 做关节改名,
`--out` 落 JSON: 起/终点、关节轨迹、`tcp_path`、误差)。脚本内客户端一律命名 `*_cli`。

## 4. 三个必踩坑
- **关节名与真机不一致**: URDF 里常是带前缀的 CAD 名(`<robot>_joint_1..6`), 控制器报的是 `joint_1..6`。
  先加改名映射做**非侵入实验**, 但报告里要写明"配置尚未正式对齐"。
- **`compute_fk` 传未知关节名会把 `move_group` 打崩**(崩溃栈落在 `MoveGroupKinematicsService::computeFKService`),
  崩后 `ros2 service list` 只剩 `robot_state_publisher/*`。⇒ 任何一次服务调用失败后, **先查节点还在不在**再往下做。
- **方法名与客户端属性重名**: `self.ik = create_client(...)` 同时又有 `def ik(...)` ⇒ `TypeError: 'Client' object is not callable`。

## 5. 同源闸(用它的轨迹之前必做)
```
FK(真机关节角)  vs  真 /robot/tcp_pose
```
- 实测形态: 位置差 **261.5mm**、姿态差 **137.48°**(四元数夹角, 两次独立复现数值一致) ⇒ 该 URDF 与**控制器关节零位口径**不同源;
  此时规划会**成功**(实测 127 路点 / 终点误差 4.55mm / `plan_code=1`), 但轨迹是"它自己模型里"的 ⇒ 不能当真轨迹。
- 判据: **< 5mm** 才算同源, 才允许把它画到真机画面上。
- 修法: 采真机 (关节角, TCP) 配对(两路都是实时流即可), 拟合 6 个关节零位偏移(必要时再加基座变换), 复验 FK < 5mm。

## 6. 报告口径
分三段: ①它跑没跑起来(容器/镜像/日志) ②它能不能规划(`plan_code` / 路点数 / 终点误差)
③**它现在能不能当真轨迹**(同源闸结论)。未过闸就明说"架构上该由它出, 但当前出不来真轨迹",
并交代替代折线的真实身份(示教位姿 + 真机 TCP 推得), 不冒充规划结果。

## 7. 规划输出在哪 / xyzabc 怎么取 / action 接口的真相
用户会问「我要看到 `moveit_msgs/action/MoveGroup` 这个 topic, 我要在数据空间里看到它输出的
x y z a b c —— 在哪里? 搜什么?」。三个"位置"指的是同一件事, 但现在只有前两条在真跑:

| 出口 | 位置 | 状态 |
|---|---|---|
| 文件 | 宿主 `~/zmax_moveit_plan/live_plan_latest.json`(= 容器 `/ws/plans/`, 同一份) + `live_plan.jsonl` 历史流 | 每 3s 覆写一轮, **在用** |
| DDS | 话题 `zmax/ss_plan` —— 数据空间页搜索框搜 **`ss_plan`**(索引: 话题 key / 全名 / 类型 / 节点名 / 层名) | **在用**(镜像) |
| action | 容器内域 42: `/move_action`(`moveit_msgs/action/MoveGroup`) + `/execute_trajectory`, 服务端都是 `/move_group` | **Action clients: 0 —— 开着没人调** |

- 🔴 **规划结果不走 topic**: action 的 result 经 `.../get_result` **服务**返回(内容 = 关节轨迹 `RobotTrajectory`);
  topic 上只有 `/_action/feedback`(`*_FeedbackMessage`, 内容是 state/pipeline_stage)与 `/_action/status`
  ⇒ **逐点 xyzabc 永远不在 action topic 上**, 在那找是白找。
- 🔴 **域不是 0**: 规划容器用独立 `ROS_DOMAIN_ID=42` ⇒ 在默认域里 `ros2 topic/action list` 全空,
  会得出"根本没有 action"的假结论; action 的 topic 还要加 `--include-hidden-topics` 才列得出来。
- plan 文件里现成的量(取数先看这些, 别自己重算): `goal_xyz` `goal_quat`(目标位姿) · `joints_path`(6/点) · `n_points` ·
  `plan_code` · `end_err_mm` · `fk_start_pos_err_mm` · `gate_same_source` + `gate_reason` · `plan_time_s` · `tcp_path`。
- 🔴 **`tcp_path` 每点只有 3 个数(x y z), 姿态被生产者切掉了**: 生产端是
  `"tcp_path": [v for row in tcp for v in row[:3]]`, 而它调的 `fk()` **已经返回 7 个数**(x y z qx qy qz qw)
  ⇒ 姿态本来就算了, 只是没上报。要看逐点 `a b c` 就只改这一处(6/点: x y z a b c, 米/弧度, 与真机 `tcp_out` 同口径),
  `ss_daemon` → `SSPlan` → 数据空间面板**原样透传、一行不用动**; 但 DDS 字段名/类型一变,
  发布端与订阅端必须**同时重启**(不同步就一条都收不到) ⇒ 和别的 GUI 改动攒成一批重启。
- 现成取证探针(仓库内, 别每次现写): `tools/fk_pose_probe.py`(逐路点 FK → x y z a b c 表) ·
  `tools/fk_quat_angle.py`(四元数夹角核末点姿态)。跑法: `docker cp` 进容器 +
  `bash -lc 'source /opt/ros/humble/setup.bash; export ROS_DOMAIN_ID=42; python3 …'`;
  起点用真关节(不要 IK 猜), `RobotState` 从 `moveit_msgs.msg` 导入(`sensor_msgs.msg` 里没有)。
- 🔴 **比姿态用四元数夹角, 绝不用 RPY 三元组**: RPY 不唯一(同一姿态有多组解) ⇒ 直接比 a/b/c 会得出完全错误的结论
  (实测按 RPY 比"差 25°", 按四元数夹角只有 **2.29°**、位置差 **4.86mm** ⇒ 规划其实是合格的)。
  报告里位置差(mm)、姿态差(deg)、终点误差(`end_err_mm`)三者对齐着写, 别只给一个。
- 末点姿态差也要看:`end_err_mm` **只量位置** ⇒ 位置 5mm 而姿态差 40° 的规划照样能过 ——
  抓取类任务两个都要报。
