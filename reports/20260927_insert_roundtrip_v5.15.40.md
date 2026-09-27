# 2026-09-27 真机插孔闭环 —— 现场记录与小版本迭代 v5.15.40

## 一、当天交付（全部真机实测，非仿真）
1. **插入往返闭环**：一号位 → 安全高度 → 插槽口 → 里萨如力控插入 → 推到底 → 沿轴拔出 → 回一号位。
   落位精度 **≤0.0016mm**（一号位 0.648836 / 0.498292 / 0.110378）。
2. **插入终点示教**：`insert_deep = (0.7938166, 0.2280350, 0.1903924)`；
   力控搜索自身落点 `(0.773815, 0.228038, 0.190392)`（两次完全一致 ⇒ 可重复）。
3. **力控插入**：调用 Orin 的 `/lissajous_force_search`（`interfaces/srv/LissajousForceSearch`）
   6N · 6mm@3Hz + 4mm@2Hz · 搜索盒 ±10mm/8s · `use_current_pose_as_box_origin=true`
   （所以臂必须先站到插槽口）· 自动标定力传感器。三次回执均 `success=True`（11.4s / 15.3s / 15.3s）。
4. **安全层两层**（VL 慢层 + 本地 CV 快层）：闸门插在 `l2_daemon.chan_send()` 唯一下发收口点；
   fail-closed；人工一次性授权只越慢层、快层不可越、每笔写审计。
5. **新增点位**（taught_points.json）：`insert_deep` `hole_retract` `hole_retract_up` `slot1_up`
   `x_mid_up` `hole_up` `insert_mouth_up` `insert_mouth`。
6. **新增技能**：`L2.return_to_slot1`（4 阶段）、`L2.insert_from_slot1`（2 阶段，point=insert_mouth_up）。

## 二、踩出来的硬知识（今天真金白银换的）
1. **回执不可信，只有 TCP 真值可信**：命令回"受理: 已下发"≠ 机器人收到。
   判定必须读 `/robot/tcp_pose` 真值。
2. **并发发指令会互相顶掉**：控制器 move_line 是"到某目标"语义，1 秒内连发多条，
   后一条顶掉前一条（今天差点撞台架）。**必须一条一条发、等到位再发下一条。**
3. **判据必须"到达目标且停住"**，不是"动过"——只判"动过"会在动作途中发下一条，又踩预占。
4. **执行器多阶段语义 = 一个 point + 每阶段偏移**（`local_mm` 工具系 / `dz_mm` 世界 z）；
   **每阶段的 `to` 会被忽略**！多点位串一条技能不成立（这是 insert_roundtrip 崩溃与跑偏的根因）。
   移动阶段不要写 `op`（`op` 只给 service 阶段）。
5. **速度不在技能步骤里**，是请求带的（技能只设 `speed_max` 上限）。speed=100 ≈ 10mm/s。
6. **零运动干跑**：把授权置 `enabled=false` ⇒ 闸门拦下发，但执行器照样把每阶段真实目标
   打进日志 ⇒ 新技能上真机前先这么验。
7. **命令通道会变僵尸**（今天 3 次）：执行器的存活判据把死通道判成"活的"，回执全在骗人。
   绕过办法=重启执行器重建通道；根治=每条指令独立通道或真探针。
8. **急停后控制器可能"收请求不执行"**：本次根因是 Orin 负载 37.8、连续运行 3 天，
   把 motion / robot_driver 节点饿死。症状：`/robot_status` 自报健康（idle/on/no_error）、
   服务全在、就是不执行也不回执。处理：重启 Orin 主机（SSH 非交互下执行特权命令
   必须用 `sudo -S` 从标准输入喂密码，否则报"需要 a terminal"而静默失败）。
9. **Orin 上的机器人栈不自启**！主机重启后必须手工拉起（工作目录与命令如下）：
   目录 `/home/tashan/0810/tashan_robot_so_20260807_174920_6983506_aarch64`；
   先 source `/opt/ros/humble/setup.bash` 与 `install/setup.bash`；
   再以后台常驻方式 launch `launch/start.launch.py project:=sr5_guangmokuai_400gAOI-BL
   launch_config:=start.launch.yaml`。
   牵起的节点：robot_driver / gripper_driver / motion / robot_state_publisher。
10. **方向符号**（已实测确认）：`L2.forward`=+X · `L2.backward`=−X · `L2.left`=+Y ·
    `L2.right`=−Y · `L2.lift`=+Z · `L2.lower`=−Z。
    一号位(0.6488,0.4983) ↔ 插孔(0.7508,0.2279)：去程 = forward + right；回程 = backward + left。
    （今天把回程腿当去程发过一次，臂跑反方向，用户急停。）
11. **几何锚定**：仿真→真机不是纯平移！三点刚体解残差 7.1 / 20.4 / 25.7mm，等效转角 164°。
12. **通道只许 10082/10083**（禁 10084/10085）。

## 三、待办
- `L2.insert_roundtrip`：按"一个 point + 偏移"重建（当前停用，改名 __DISABLED_需修）。
- `L2.return_to_slot1` / `L2.insert_from_slot1`：**已建但未实跑**（干跑已验字段与目标解析），
  下次上真机首用，跑通才算数。
- 命令通道僵尸：根治（独立通道，或存活判据改真探针）。
- Orin 机器人栈加自启（systemd unit）—— 需老倪授权（Orin 政策：只读遥测，禁装包）。
- 笔记本相机外参：仅 1 组对应点，叠加副本仍待 3 个标定位。
