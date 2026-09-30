# 真机运动控制 —— 2026-09-27 现场硬知识（插孔往返闭环实战）

## 一、铁律（血换的）
1. **回执不可信，只有 TCP 真值可信**：命令回「受理: 已下发」≠ 机器人收到。
   任何"成功"判定必须读 `/robot/tcp_pose` 真值，再算偏差。
2. **禁止并发/秒级连发指令**：控制器 move_line 是「到某目标」语义，后一条顶掉前一条，
   且残留指令会继续执行（曾差点撞台架、被用户急停）。
   ⇒ **一条一条发，等到位、核实真值，再发下一条。**
3. **到位判据 = 「到达目标且停住」**（|偏差|<容差 且 连续采样不再变），
   不是「动过」。判「动过」会在动作途中发下一条，踩预占。
4. **每步做方向断言**：离目标必须变近，否则立刻停手。曾因把回程腿当去程发，臂反向跑。
5. **零运动干跑验证新技能**：授权置 `enabled=false` ⇒ 闸门拦下发，但执行器照样把
   每阶段真实目标打进日志 ⇒ 可在臂不动的情况下验证技能解析。
   **新技能一律先干跑，再上真机。**

## 二、L2 执行器（l2_daemon）多阶段语义 —— 关键
- **一条技能只能有一个点位**（技能级 `point`），每阶段只能用**偏移**：
  `local_mm`（工具系）/ `dz_mm`（世界 z）。
- **阶段里的 `to` 会被忽略**（多点位串一条技能不成立）。铁证：干跑日志三阶段全报
  `点=insert_pose`。
- `op` 字段**只用于 service 阶段**（如调 `/lissajous_force_search`）；移动阶段写 `op` 会让
  执行器崩（`not enough values to unpack (expected 4, got 3)`）。
- 字段白名单：`stage / to / dz_mm / local_mm / dwell_s / tol_mm / timeout_s / guard / note`
  （**无步骤级 `speed`**）。
- **速度不在技能里**：由请求自带（`{"skill":...,"speed":500}`），技能只有 `speed_max` 上限。
  上限会静默压速（曾因 `speed_max=30` 以为"臂慢"，实为被压到 3mm/s）。
- 正确形态示例（一号位→插槽口，2 阶段）：
  ```
  point = insert_mouth_up (插槽口正上方)
  阶段1: dz_mm = 0        → 对角横移到插槽口正上方(一条腿)
  阶段2: dz_mm = -105.378 → 竖直下降到插槽口
  ```
  之后交 `L2.lissa_insert`（point=insert_pose: 阶段1 local(0,0,-60)=槽口,
  阶段2 local(0,0,0)=插入位, 阶段3 服务力控）；其起点距 insert_pose 仅 60mm ⇒ 过守卫。

## 三、里萨如力控插入（Orin 服务）
`/lissajous_force_search`（`interfaces/srv/LissajousForceSearch`）参数：
6N 工具 Z 压 · 6mm@3Hz + 4mm@2Hz · 盒 ±10mm/8s · `use_current_pose_as_box_origin=true` ·
`cartesian_stiffness [6000,6000,0,300,300,100]` · `max_vel [0.1,0.1,0.01,5,5,5]` ·
`calibrate_force_sensor=true` · `settle 0.1s`。
- **臂必须先站到插槽口**（盒以当前位姿为原点，否则搜不到）。
- `success=True` 只代表「找到孔并滑入」，**≠ 插到底**：力控落点比示教终点差约 24.5mm，
  需补推（`L2.forward`，慢速 3mm/s）。
- 落点可重复（两次完全一致 0.773815/0.228038/0.190392）。

## 四、急停后的「收请求不执行」排查顺序
1. 读 `/robot/tcp_pose` 确认臂真的没动（不是判据错）。
2. 读 `/robot_status`（自报 idle/on/no_error？）+ 调 `/rokae_recover_estop`
   （急停恢复服务，会回「不在急停状态」或恢复反馈）。
3. 检查**下发通道**：重启执行器重建通道（通道会变僵尸，见下）。
4. 检查**承载机负载**：`clear` 无关；`uptime` 看 load。本次 load **37.8 连续 3 天**
   ⇒ motion / robot_driver 被饿死 ⇒ 症状=服务全在、请求收得下、不执行不回执。
5. 重启承载机（SSH 非交互执行特权命令**必须 `sudo -S` 从 stdin 喂密码**，
   否则报「需要 a terminal」而**静默失败**——本次就因此误以为已重启）。
6. 承载机重启后**机器人栈不自启**，必须手工拉起：
   目录 `/home/tashan/0810/tashan_robot_so_20260807_174920_6983506_aarch64`；
   source `/opt/ros/humble/setup.bash` + `install/setup.bash`；后台常驻 launch
   `launch/start.launch.py project:=sr5_guangmokuai_400gAOI-BL launch_config:=start.launch.yaml`。
   节点：robot_driver / gripper_driver / motion / robot_state_publisher。
   （**启动前先 `readlink /proc/<pid>/cwd` + 读 cmdline 抓现场**，否则重启后拉不起来。）

## 五、命令通道僵尸（高频故障）
- 症状：`ssh` 活着但不干活；回执全说「已下发」而 TCP 一路不变。
- 判据太松会自己骗自己（把「受理」当成功）⇒ **只按 TCP 真值判**。
- 临时解：重启执行器重建通道（看 `✅ ssh 探针通过` / `🔌 命令通道已建立 (pid=…)`）。
- 根治：每条指令独立通道，或存活判据真发一次探针。

## 六、方向符号（实测确认）
`L2.forward`=+X · `L2.backward`=−X · `L2.left`=+Y · `L2.right`=−Y · `L2.lift`=+Z · `L2.lower`=−Z。
一号位(0.6488,0.4983) ↔ 插孔(0.7508,0.2279)：去程 forward+right，回程 backward+left。

## 七、安全层（两层，不可越）
- 慢层 VL（20s/轮，带意图序号）+ 快层本地 CV（5Hz/0.2s，判镜头遮挡/糊化）。
- 闸门在 `l2_daemon.chan_send()` 唯一下发收口点；缺失/过期/不安全 ⇒ 拒发（fail-closed）；
  急停/复位白名单永远放行。
- 人工一次性授权**只越慢层，快层永不可越**，限时限量限动作，每笔写审计。
- **授权 scope 必须同时含技能名与点位名**（多阶段路径报的是点位名，只写技能名会不匹配而干等）。
