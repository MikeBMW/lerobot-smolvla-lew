# 边缘机零程序：主机侧远程只读订阅（2026-09-16 实测配方）

## 触发 / 红线（用户原话）
- 「**不要在orin上增加新程序。orin是生产设备，不能被干扰。你先只是转发orin的感知信号**」
- 「你不要在orin上安装新软件啊」

⇒ 结论：边缘机(Orin)侧 **零自研程序、零自启项、零写回**。
采集 = **主机侧远程只读订阅**；执行收口留给产线自身（我方不参与）。
此前部署过的影子节点/边缘节点/守护脚本/crontab 自启 **已全部回滚**（序列见下），
备份留在主机 `/tmp/ss_orin_backup.tar.gz`。

## 为什么可行（本次实测，不是推测）
主机(4060) 本地无 ROS2，但容器 `ros:humble-ros-base --network host` + `ROS_DOMAIN_ID=0`
在同一网段直连(0.5ms RTT)下能直接看到并订阅 Orin 的**全部生产话题**——不需要边缘机跑任何桥。

实测 25s 窗口（值与频率都是真的）：
| 话题 | 类型 | 频率 | 备注 |
|---|---|---|---|
| `/robot/tcp_pose` | geometry_msgs/PoseStamped | **49.786 Hz** | 真机笛卡尔位姿，frame=`base_link`，x=0.66391 y=−0.02925 z=0.29355 |
| `/real_joint_states` | sensor_msgs/JointState | **100.432 Hz** | 6 关节 |
| `/robot/force_torque` | **同名双类型** | 空闲无发 | JointState + WrenchStamped 两个发布者 |
| `/gripper_pos` | std_msgs/Float64 | 空闲无发 | 机器空闲时无发布者 |
| `/motion/active_states` | std_msgs/String | 空闲无发 | 机器空闲时无发布者 |

采集节点自证：`self_publishers = ['/parameter_events']`（ROS 每个节点自带，关不掉），
`enable_rosout=False` 已关掉 `/rosout` ⇒ 域内**没有任何数据/控制发布端点**。

## 起才采集（主机侧容器，read-only）
```bash
sudo docker run -d --name ss-remote-tap --network host \
  -e ROS_DOMAIN_ID=0 -e SS_OUT=/out -e SS_INFER_URL=http://127.0.0.1:8790/infer \
  -v /home/ubuntu/<repo>:/repo:ro -v /home/ubuntu/<out_dir>:/out \
  ros:humble-ros-base bash -c \
  "source /opt/ros/humble/setup.bash && exec python3 /repo/tools/ss_remote_tap.py --rate 10"
```
systemd（**主机**侧，允许）：`Type=simple` + `User=root` +
`ExecStartPre=-/usr/bin/docker rm -f <name>` + `ExecStopPost=-/usr/bin/docker rm -f <name>` +
`Restart=always` + `Requires=docker.service` + `After=network-online.target`。
（模板见仓库 `tools/systemd/`；本次为 `ss-remote-tap.service`。）

## 先探再写订阅代码
```bash
docker run --rm --network host -e ROS_DOMAIN_ID=0 ros:humble-ros-base bash -c \
 "source /opt/ros/humble/setup.bash; ros2 topic list; ros2 topic type /robot/force_torque; \
  ros2 topic info -v /motion/active_states; timeout 20 ros2 topic hz /robot/tcp_pose"
```
- `ros2 topic hz` 无输出 = 当前**没有发布者**（机器空闲），不是网络/订阅写错。
- 读产线话题用 **BEST_EFFORT** QoS（`ReliabilityPolicy.BEST_EFFORT`）。

## 坑（本次真踩）
1. **同名双类型话题**：`/robot/force_torque` 上同时有 JointState 与 WrenchStamped 发布者
   （`ros2 topic info -v` 会列出两个 Type）。在本镜像里对 WrenchStamped 建订阅直接失败：
   `RCLError: Failed to create subscription: invalid allocator, at ./src/rcl/subscription.c:219`
   （拆成两个 node 也一样失败，不是同节点冲突）。⇒ 用 `ros2 topic type` 确认后再订；
   只订能建的那一路，并把"订阅数 + 实际收包数"一起记录，**别把 0 收包当链路故障**。
2. **`rclpy` Node 没有 `get_publisher_names_and_types()`**（只有 `..._by_node` / `get_service_names_and_types`）。
   写进主循环会让进程崩，`Restart=always` 变成崩溃循环（表现：status 文件时间戳冻住、journal 每 5s 一条 traceback）。
   自证端点用 `getattr(node, "_publishers", [])`（取 `topic_name`）+ `node.count_publishers(topic)`；
   取证字段一律 try 包住，别让它搞死主循环。
3. **`enable_rosout=False`**（Node 构造参数）不开会往产线 domain 发 `/rosout`；
   开 `start_parameter_services=False` 也关不掉 `/parameter_events`（rclpy 必建）。
   如实报告端点："仅 ROS 自带参数事件通道"。
4. **远程 `pkill -f` 会杀掉自己这条 ssh 会话**：命令串任何位置出现明文进程名就中招
   （实测同一条命令里带 `rm -f ~/.zmax/ss_shadow.log`、`tar … ss_edge.py` 都会命中自己的 `bash -c` 行，
   症状：输出中断、exit 255 / -15）。
   正解：① 锚定模式 `pgrep -f "^python3 .*ss_"`（自己那条以 `bash -c` 开头，不匹配）；
   ② 先 pgrep 列 PID 再按 PID `kill`；③ 别把含进程名的路径写进同一条命令。
5. `ss-bridge` 那类"会写回边缘机"的桥必须 `systemctl disable --now`——**只许转发出来，不许写回**。

## Orin 侧回滚序列（已执行，可复用）
1. **先备份再删**：`tar czf /tmp/<name>_backup.tar.gz -C ~ <我建的文件…>`，scp 回主机（本次 2.2MB）。
2. 停进程（锚定，不自杀）：`for p in $(pgrep -f "^python3 .*ss_"); do echo "kill $p"; kill $p; done`
   ——顺带清 `^python3 /tmp/check_bag_motion.py` 之类残留。
3. 清自启：先 `crontab -l | sed 's/^/OLD: /'` 留证，再
   `crontab -l | grep -v <我加的每一行> > /tmp/ct.new && crontab /tmp/ct.new`。
4. 删文件：`rm -f ~/.zmax/{start,daemon,*.log}` / `rm -rf ~/.zmax/<link> ~/.zmax/<shadow>` /
   `rm -f ~/zmax_state_space/tools/{ss_edge.py,ss_shadow.py}`。
5. **复核必须给证据**：`pgrep -af "^python3 .*ss_"` 空 · `crontab -l` 空 ·
   `ros2 topic list | grep <项目前缀>` = 0 · `curl 127.0.0.1:8765/health` = online ·
   `ros2 node list | wc -l` = 18（产线自带）· uptime 恢复正常。
6. 主机侧同步：`systemctl disable --now ss-bridge`；数据落**主机**（`~/<项目>_remote/{state,proposal}_<日期>.jsonl` + `status.json`）。

## 缺失标定时的诚实口径（z7 示例，可推广）
引擎口径 `z7 = [手/头−目标(3), 手/头−光模块(3), 夹持(1)]`：
- "手/头" 有真值：`/robot/tcp_pose` 远程可读；
- "目标/光模块" 属**现场几何，必须现场示教**（示教工具跑在主机容器里即可，边缘机不用装东西）⇒
  `--record peg_head/goal` 记 TCP 到 json，含 `by/note/时间`，校验不过则推理端拒用；
- 几何缺失时：`z7 = null` + 状态里写"**拒算，不编造**"；推理端做范围检查（|值|>2m → HTTP 409 refuse）
  + 提供严格模式（`*_STRICT=1` 拒绝占位兜底）；
- 汇报必须同时说清两件事：**模型每帧真被调用**（GPU 0.8~1.5ms/帧）与 **input_map=placeholder_v0 表示口径未标定**，不是可用决策。
