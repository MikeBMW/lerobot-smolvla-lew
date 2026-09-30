# L2 肌肉记忆 → ROS2 转发 (实现细节, 2026-09-19 真机实测)

## 链路形状 (用户要的"从 L2 发出去, 经 ROS2 转发到 Orin")

```
状态空间工程 (L2 层技能库 data/skills/l2_muscle/*.json)
   │  选择技能 + 点位(操作员示教值)
   ▼
tools/l2_ros2_bridge.py   ← 本机进程(不是 DDS 节点): 逐条下发 + 取证 + 落盘
   │  ssh + `ros2 service call` (走 Orin 自己的 ROS2 图)
   ▼
Orin ROS2 service: /move_line · /move_joint · /target_relative_joint · /gripper_driver · /rokae_recover_estop
```

- Orin 上**没有 rosbridge / websocket**(实测 `ros2 service list | grep rosbridge` 空, 9090/9091 无监听),
  本机也不是 DDS 节点 ⇒ 转发就用 `ssh + ros2 service call`. 若将来装了 rosbridge, 可换成 websocket 客户端, 桥的逻辑不变.
- GUI 侧入口: 真机视面板加一个按钮(仅 Real 模式可见) → 二次确认对话框 → 后台起 `gui-venv311/bin/python tools/l2_ros2_bridge.py --cycles 1`
  (**不要用 `sys.executable`**, 冻结包里它是 app 自身 → 会再开一个实例).

## 技能 JSON 字段 (骨架见 templates/l2_muscle_skill_v1.json)

```json
{ "id": "L2.MUSCLE.<名>.v1", "layer": "L2", "kind": "muscle_memory",
  "points": { "slot": {"pos": [x,y,z], "quat": [x,y,z,w], "desc": "..."},
              "safe": {"pos": [...], "quat": [...], "desc": "槽位正上方 100mm(纯 Z 抬升最安全)"} },
  "params": {"speed": 30, "grasp_force": 40, "grasp_pos": 0, "open_pos": 1000},
  "steps": [ {"op":"gripper","args":{"target_pos":1000},"note":"张爪(放料)"},
             {"op":"move","to":"safe","note":"抬起退让"},
             {"op":"move","to":"slot","note":"下降回槽位"},
             {"op":"gripper","args":{"target_pos":0,"target_force":40},"note":"夹紧"},
             {"op":"move","to":"safe","note":"抬起(验证:开度不变=夹牢)"} ],
  "verify": {"grasp_open_min": 60, "grasp_open_max": 320} }
```

## 转发桥每步只做四件事

1. `gate()`: 三查 `power_state=on` / `operation_state=idle` / `has_error=false`;
   有错先 `ros2 service call /rokae_recover_estop std_srvs/srv/Trigger`(**无运动**, 可清 has_error), 再复查.
2. **单步**下发(绝不把两步合成一条).
3. 等 6s 后读 `tcp_pose` + `gripper_pos` 取证.
4. 追加写 `~/zmax_data/l2_muscle_run_<ts>.jsonl`(每步一行: 步骤名/success_flag/开度/耗时/位姿).

CLI: `--skill <json>` · `--cycles N`(重复练习) · `--dry-run`(只打印将下发的完整字节, 给操作员过目).

## 三条运动路径的模式语义 (选错就"莫名下电"/"莫名被拒")

| 路径 | 动作后伺服 | 适合 |
|---|---|---|
| `/target_relative_joint` (rt 实时) | **下电**(`power_state=off`) → 下条前要示教器再上电 | 单发一次的最小步验证 |
| `/move_joint` (绝对关节) | **保持 on** ✓ | 连做多步 |
| `/move_line` (笛卡尔直线) | **保持 on** ✓ | 单轴小步首选 |

## 超时与拒绝的语义 (别误判成失败)

- `success=False + ROBOT_IDLE_TIMEOUT`(`wait_until_idle` 30s 上限): **动作常常已经到位**
  (实测目标 z=0.20848888 → 实测 0.20848888, 误差 0.1µm) ⇒ **判完成只看真值**, 绝不因 `success=False` 重发(会叠加).
  把 speed 提到 25~50 常能在 30s 内返回 `success=True`(实测 50mm 匀速约 23s).
- `-50002 目标点超出运动范围, 或为奇异点`: 组合斜线大位移/异地姿态会触发,**且不下发运动**(安全) ⇒ 改单轴小步.
- `-514 setPowerState(true): 上下电失败`: 那一刻模式/伺服没就绪(刚被拒过/刚被人扶过) ⇒ 清错 + 三查后重发.
- `实时模式异常: 设置模式错误 … 网络连接错误`: 拖动残留/未就绪 ⇒ 查控制器日志(`/tmp/tashan_robot_run.log` 的 `[robot_status]` 行含 repair 建议).

## 字节模板

```bash
# 笛卡尔单轴小步 (姿态保持不变)
ros2 service call /move_line interfaces/srv/TargetPose \
 "{speed: 30.0, joint_state: {name: [], position: []}, pose: {position: {x: X, y: Y, z: Z}, orientation: {x: QX, y: QY, z: QZ, w: QW}}}"

# 夹爪: 张开 / 夹紧(必须显式给力, 否则只会合到 250~311 偏松)
ros2 service call /gripper_driver interfaces/srv/GripperSrv \
 "{target_pos: 1000.0, target_speed: -1.0, target_force: -1.0, target_acc: -1.0, target_push_length: -1.0, target_push_speed: -1.0}"
ros2 service call /gripper_driver interfaces/srv/GripperSrv \
 "{target_pos: 0.0, target_speed: -1.0, target_force: 40.0, target_acc: -1.0, target_push_length: -1.0, target_push_speed: -1.0}"
```

## 卡点与处置 (现场遇到过的)

| 现象 | 处置 |
|---|---|
| 一步 1000→0 合爪"静默 no-op"(回 490 不动) | 走**分步** `400 → 100 → 0`; 并确认 `operation_state=idle` |
| 拖动模式下夹爪指令无效 | 请操作员关拖动回 idle 再下发 |
| 操作员手扶过臂 | 重读当前位姿再算目标; 旧位姿算出的目标点是错的 |
| 抓取后"看不到目标" | 是数据缺口不是没加载权重; 让操作员标注"抓在手里的半个目标"重训 |
