# Orin 零程序 · 只转发感知 (2026-09-16 老倪红线 + 标定桥真口径)

老倪原话: 「**不要在orin上增加新程序。orin是生产设备, 不能被干扰。你先只是转发orin的感知信号**」

## 1. 红线落地 (Orin 侧 = 零自研程序)
- 移除我此前放在 Orin 的一切: `ss_edge.py` / `ss_shadow.py` / `ss_infer_service.py` / `~/.zmax/*` 启动脚本 /
  **crontab 的 `@reboot` 自启项** (自启项也算"新增程序", 必须清)。
- 清完的取证三连 (缺一不可):
  ```bash
  ssh tashan@192.168.23.66 'pgrep -af "^python3 .*ss_" || echo 无'
  ssh tashan@192.168.23.66 'crontab -l | grep -v "^#" || echo 无'
  ssh tashan@192.168.23.66 'source /opt/ros/humble/setup.bash; ros2 topic list | grep -c zmax_ss'   # 期望 0
  ```
  另确认生产不受影响: `curl 127.0.0.1:8765/health` → `{"online":true}` + Orin 本机 `ros2 node list` = 18 个生产节点。
- **只在 4060 侧跑、只在 4060 侧装** (Docker/venv 随便装), Orin 只作为 DDS 话题的**发布方**被远程订阅。

## 2. 关键发现: 跨机 DDS 直读 — Orin 上连"转发程序"都不用跑
4060 的 Docker `ros:humble-ros-base --network host` + `ROS_DOMAIN_ID=0` **可以直接订阅 Orin (192.168.23.66) 的
生产话题** (同一 domain 跨 192.168.23.x 直连网段; 先决条件 = ARM/机器人侧 DDS 未被限回环):

```bash
sudo docker run --rm --network host -e ROS_DOMAIN_ID=0 ros:humble-ros-base \
  bash -c "source /opt/ros/humble/setup.bash; timeout 25 ros2 topic list"
# 实测: 40 个话题可见 (含 /robot/tcp_pose /real_joint_states /robot/force_torque /motion/active_states ...)
```
频率实测 (25 s 窗口, 直读真值): `/robot/tcp_pose` **49.79 Hz** · `/real_joint_states` **100.43 Hz**。
健康例外探测 (⚠️ 别把"机器空闲"误判成"链路不通"): `/gripper_pos`、`/motion/active_states` 空闲时 **0 publisher**;
`/robot/force_torque` 是**同名双类型**话题 (`sensor_msgs/JointState` + `geometry_msgs/WrenchStamped`),
**本镜像订 WrenchStamped 直接报 `RCLError: Failed to create subscription: invalid allocator`** (实测) → 只订 JointState。

## 3. 采集节点纪律 = 只订阅, 零发布 (自证可查)
`tools/ss_remote_tap.py` (4060 侧, 跑在容器里):
- `Node("ss_remote_tap", enable_rosout=False, start_parameter_services=False)` — 关掉 rosout;
  **`/parameter_events` 是 rclpy 每个节点自带的, 关不掉** (实测两参数都关仍在), 如实写进证据别谎报"零端点"。
- 订阅 5 条 (BEST_EFFORT depth=1), **不调用任何 `create_publisher`**; 把自证写进 `status.json`:
  `self_publishers` (运行时实体表) / `self_subscriptions` / 每个话题的**外部发布者数** `count_publishers(topic)`。
- 产物全落 4060 本机: `state_YYYYMMDD.jsonl` / `proposal_YYYYMMDD.jsonl` / `status.json`; systemd 单元
  `ss-remote-tap.service` (Restart=always) 常驻; **会写回 Orin 的 `ss-bridge.service` 一律 `disable --now`** (只出不进)。

## 4. 标定桥: z7 真口径 + "缺几何就拒算, 绝不编造"
引擎口径 `z7 = [手/头 − 目标(3), 手/头 − 光模块(3), 夹持(1)]`:
- **手/头** = 真机 `/robot/tcp_pose` (50 Hz, frame `base_link`) — 已可直接读 (样例 x=0.6639 y=−0.0293 z=0.2935)。
- **目标点 / 光模块 peg 点** = 现场几何, **必须现场示教**, 不许写估计值:
  `tools/ss_geom_calib.py --record peg_head|goal --note "谁在哪示教"` (可在 4060 容器内跑 → 不动 Orin),
  产物 `real_cell_geometry.json` 带 `by/note/updated_at` + 校验 (两点距离 20~600 mm、z 合理、点数齐) → `validated`。
- 推理端 `tools/ss_local_infer_server.py`: 有 `state["z7"]` (7 维且 |值|≤2 m) → `input_map=tcp_pose_v1`;
  几何缺失 → `z7=null` + `geom=缺失…拒算`; `SS_INFER_STRICT=1` 时无真 z7 直接 **409 拒绝**, 不用 placeholder 兜底。
- **诚实口径**: 示教前模型仍每帧被真调用 (GPU 0.8~1.5 ms), 但 `input_map=placeholder_v0` **逐条落盘** —
  汇报必须说"这不是真口径在驱动", 别让"模型在跑"听起来像"模型接上了"。

## 5. 数据归档 (不进 git, 但可溯源)
`tools/ss_archive_remote_data.py` → `~/zmax_data/ss_remote/<时间戳>/`:
一致性快照 (逐行 JSON 校验, 半行/坏行剔除并计数 → `state.jsonl.gz`/`proposal.jsonl.gz`) + `status.json` + `MANIFEST.md`
(条数/坏行/时间跨度/字段非空计数/input_map 取值/sha256/git rev/工具 sha256) + `archive.json`。
实测首批: state 11991 条 / proposal 11963 条 / 坏行 0 / 跨度 1377.8 s / input_map 全为 `placeholder_v0`。

## 6. 两个必须记住的坑
1. **ssh 上 `pkill -f` 会自杀**: 模式串只要出现在**自己这条命令行**里 (例如命令里还要 `rm ~/.zmax/ss_edge.log`),
   bash -c 的整条命令行就匹配 → pkill 杀完目标把 shell 也杀了, **后续命令全不执行** (本次实测 exit 255, 清理只做了一半)。
   正解二选一: ①方括号技巧 `pkill -f "ss_[e]dge.py"`; ②**锚定法** `pgrep -af "^python3 .*ss_"` (远程 shell 命令行以
   `bash -c` 开头, 锚 `^python3` 必不匹配自己) → 再 `kill <pid>`, 且**按 PID 逐个 kill 而不是 pkill**。
2. **`/tmp` 里的备份会消失**: Orin 整改前的运行态打包 `/tmp/ss_orin_backup.tar.gz` 数十分钟后被 `/tmp` 清理机制删除。
   要留档就写 `~/zmax_data/...` (或仓库外的持久目录), 并且**当场核对文件存在** (`ls -la`) — 别把"我打过包"当"备份还在"。
