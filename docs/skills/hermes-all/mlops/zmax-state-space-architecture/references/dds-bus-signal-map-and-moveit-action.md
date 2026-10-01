# 数据空间(DDS 总线) 信号表 · MoveIt 规划 / action 取数地图

用于回答两类高频问题：「**这个值在数据空间哪里？搜什么？**」和「**MoveIt 输出的 action / topic 在哪？**」。

## 落盘文件（数据空间页读的就是这两份）
- `~/zmax_data/dataspace/live.json` —— 逐话题**实时值**：`topics.<key>.fields`（值本身），
  外加 `hz / hz_design / count / jitter_ms / loss_pct / lamp / verdict / score / rules`（健康与判据）、
  `mode` + `mode_desc`（当前允许的话题集随模式变）、`loop`（闭环阶段表）。
  ⇒ 界面上要"实时数值"，先看 `fields`；**`fields` 空 = 上游确实没发**，不是界面藏了。
- `~/zmax_data/dataspace/trace.jsonl` —— 总线帧流（滚动尾部数百行）：`{t, topic, type, n, bytes, digest}`。
  `digest` 是**截断**的 payload JSON ⇒ 不能 `json.loads`（用正则抠数值）；若该话题的探针摘要只写了 `ts`，
  回退就只剩 `ts` —— 真正的值仍在 `live.json.fields`。
- 面板代码：`tools/gui/dds_canoe.py`（类 `BusView`：信号表 · Trace · 闭环 · 告警 + 搜索框 + Δt/导出）· `tools/gui/dds_bus.py`。

## 关键词（搜索框按"话题 key / 全名 / 类型"子串匹配）
| 搜这个 | 得到 |
|---|---|
| `ss_plan` | MoveIt 规划镜像：`goal_xyz` / `joints_path` / `tcp_path` / `n_points` / `plan_code` / `gate_same_source` |
| `ss_action` | 动作通道（画布 `ssdec → n_moveit` 的「action 直通」那一路） |
| `ss_state` | 状态镜像 · `ss_calib` 标定（手眼/平面） · `ss_diag` 吞吐/帧龄/丢弃 |
| `link_value` / `hw_state` / `heartbeat` | 连线值 / 硬件 / 心跳 |

⚠️ **ROS 的 action 话题不在这个总线上**（trace 只镜像 DDS 的 `zmax/*`）⇒ 搜 `move_action` 零命中是**正常**的。
先给他能命中的词（走值就用 `ss_plan`），再说清"那个 action 要看另一条命令"。

## MoveIt 侧取数（容器 `zmax-moveit`，只规划不执行）
- **ROS 域是 `ROS_DOMAIN_ID=42`**（不是 0；在 0 域扫永远是空的），且 action 话题**默认隐藏**，必须加 `--include-hidden-topics`：
  ```bash
  sudo docker exec zmax-moveit bash -lc 'source /opt/ros/humble/setup.bash; export ROS_DOMAIN_ID=42; \
    ros2 topic list -t --include-hidden-topics | grep -E "move_action|execute_trajectory"'
  # /move_action/_action/feedback [moveit_msgs/action/MoveGroup_FeedbackMessage]
  # /move_action/_action/status   [action_msgs/msg/GoalStatusArray]
  ```
- **规划结果不走话题**，走 `.../get_result` **服务** ⇒ 别指望 echo action 话题能拿到轨迹。
- `ros2 action info /move_action` 看 `Action clients / servers`：**clients = 0 = 接口开着但没人调**
  （本部署是 plan-only 旁路），此时"输出"实际落在 JSON 文件 + 画布端口上 —— 报口径必须说清哪条在真跑。
- 规划文件：宿主机 `~/zmax_moveit_plan/live_plan_latest.json`（= 容器 `/ws/plans/`，bind mount；
  同目录 `live_plan.jsonl` 历史、`planner.log`）。生产者 = 容器内 `moveit_plan_live.py --interval 3`
  （是**拷进**容器的，不是挂载 ⇒ 改完要 `docker cp` + 重启那个 nohup 进程）。
- 关键字段：`goal_xyz` / `goal_quat`（目标位姿）、`joints_path`（关节路径，6 个数/点）、
  **`tcp_path` 只有 3 个数/点（x y z）** —— 生产端 `[v for row in tcp for v in row[:3]]` 把姿态切掉了；
  而 `fk()` 本身返回 `x y z qx qy qz qw`（7 个）⇒ 要逐点 a b c 就在那里补，下游镜像不用改。
- 同源闸：`fk_start_pos_err_mm` + `gate_same_source` / `gate_reason`（FK(真关节) 与真机 TCP ≤5mm 才算同源；
  实测 343.9mm ⇒ **只可当设计态轨迹看**，不许冒充已通过真机校验）。
- 可复跑取证探针：`tools/fk_pose_probe.py`（逐路点 FK → xyzabc）· `tools/fk_quat_angle.py`（四元数夹角核末点姿态）。
  两者都靠容器里的 `/compute_fk`：`docker cp` 进容器 → `source /opt/ros/humble/setup.bash` → `ROS_DOMAIN_ID=42 python3 /tmp/<脚本>`。

## 姿态比对：只用四元数夹角，别比 RPY 三元组
同一姿态的 RPY 表示**不唯一**（另一组三元组表示同一个旋转）⇒ 直接相减会得到假误差：
实测按三元组差 ≈25°，按四元数 `2·acos|q1·q2|` 只有 **2.29°**。报"姿态差多少度"一律用四元数夹角；
报"位置差多少 mm"才可以直接比 `tcp_path` 首/末点。
