# 真机 6 轴角度「反出来」+ 授权前的只读 preflight (2026-09-18 实测)

原话: 「机器人6轴的实际角度，先反出来」——老倪要的是**实时真值读数表**, 不是接口清单、不是选项。
本文给读数口径 (三源交叉) + 换算 + 授权后仍必须先跑的两道只读闸 + 侦察命令面的两个坑。

## 1. 6 轴读数: 两个话题的差异必须知道 (别只挑一个读)

| 话题 | 速率 | name 风格 | position | velocity | effort |
|---|---|---|---|---|---|
| `/robot/joint_states` | 45~47Hz | `joint_1`…`joint_6` | **12 项** (后 6 项恒 0 = 预留位, 不是 7~12 轴) | `[]` 空 | **有效, 真实力矩** |
| `/real_joint_states` | 100Hz | `XMS5-R800-W4G3B4C_joint_1`…(`frame_id` 同前缀) | 6 项 | 有字段但实测全 0 | 全 0 |

- 型号/机型从 name 前缀与 `frame_id` 直接读出来 (本次: 珞石 **XMS5-R800-W4G3B4C**)。
- 两源同一时刻差 **~1e-5 rad (0.0006°)** ⇒ 是同源真值; 差得大就要怀疑其中一路在发旧帧。
- 只想读一次: `ros2 topic echo --once /real_joint_states` (100Hz 更稳, 必出消息); 要力矩用 `/robot/joint_states`。
- **静止判定** = `velocity` 全 0 **且** `/robot_status.operation_state == "drag"` (人手拖动示教中), 此时 J2/J3 的 ±21~22 N·m 是**重力保持力矩**。

## 2. 三源交叉核对 (给证据, 不给单点读数)

```
A Orin /real_joint_states   100Hz   ┐
B Orin /robot/joint_states   46Hz   ├─ A vs B 差 <1e-5 rad → 判真值在新
C 本机 4060 tap 落盘 10Hz           ┘   (state_YYYYMMDD.jsonl 末行 jpos/tcp, 记的是**本机接收时刻**)
```
C 的读法 (文件几百 MB, 一律尾部反向读, 别整文件 load):
```bash
tail -c 4000 ~/zmax_ss_remote/state_$(date +%Y%m%d).jsonl | tail -1 |
  python3 -c "import json,sys;d=json.load(sys.stdin);print(d['jpos'],d['tcp'],d['tcp_frame'])"
```

## 3. 换算 (老倪要度, 别只给弧度)

```python
import math
deg = [math.degrees(v) for v in jpos]                    # 弧度 → 度
# TCP 四元数 → 欧拉 (先归一化):
roll  = math.atan2(2*(qw*qx+qy*qz), 1-2*(qx*qx+qy*qy))
pitch = math.asin(max(-1,min(1,2*(qw*qy-qz*qx))))
yaw   = math.atan2(2*(qw*qz+qx*qy), 1-2*(qy*qy+qz*qz))
```
本次实测锚点 (用于判断"读数是否变过"):
`J1..J6 = -11.0065 / -9.6999 / -134.2525 / +18.3062 / -54.1142 / +14.0969 deg`,
`TCP = (438.9, 147.3, 231.7) mm, |xyz|=517.7mm, RPY=(-162.617, -41.888, -1.890)°`。

## 4. ⚠️ 时间戳口径: Orin 的 `header.stamp` 不是墙钟

本次实测: Orin `stamp.sec=1789612327`, 本机 CST epoch `1789707561` → **Orin 慢 26.24 小时** (RTC 未校)。
⇒ **时间基准一律用本机接收时刻** (tap 落盘 `t` / `date`), 千万别拿 `header.stamp` 报时间;
两边节点自己的 stamp 之间也会差 1~2s (`/robot/joint_states` vs `/real_joint_states`), 不要用它做同步。

## 5. 授权后也必须先跑的两道只读闸 (老倪: "我在现场"≠可以免检)

```bash
# 闸 1: 机器人能不能接自动指令
ros2 topic echo --once /robot_status
#   → operation_state=drag 时**不下发** (跟人手抢); 还看 has_error / power_state
# 闸 2: 产线状态机允不允许
ros2 service call /hmi/snapshot interfaces/srv/HmiSnapshot '{}'
#   → 返回 snapshot_json: lifecycle / mode / paused / active_states / command_availability{...allowed,reason}
```
实测 (本次): `lifecycle=PAUSED, mode=real, paused=true, active_states=[]`,
`START_TASK: allowed=false (current lifecycle is PAUSED)`; `RESUME / SET_MODE / SET_GRIPPER / ROBOT_HOME /
EMERGENCY_STOP / SAVE_TEACH_POSE` 为 `allowed=true`。
⚠️ **快照里的 `timestamp` 是"最后一次变更"的时刻** (本次还停在 09-17T10:27) ⇒ 别当实时状态读,
只把它当"上一次状态机变更时允许什么"。
`/physical_estop`、`/emergency_stop` 的 publisher 数实测 = 0 ⇒ **现场急停状态不可观测**,
只能靠 `robot_status.has_error`; 所以"急停在手边"必须由**人**保证, 不能靠软件读。

## 6. 侦察命令面的两个坑 (Humble 实测)

- `ros2 service type /move_pose /move_line …` → `error: unrecognized arguments`。**只能一次一个名字**,
  用 for 循环逐个查: `for s in move_pose move_line …; do printf "%-24s " $s; ros2 service type /$s; done`
- `ros2 interface show interfaces/srv/TargetPose` 只 source `/opt/ros/humble` 会报 **`Unknown package 'interfaces'`**
  → 必须先 source 现场工作区: `for ws in /home/tashan/0810/*/install/setup.bash; do [ -f "$ws" ] && source "$ws" && break; done`
- 运动类**全是 service, 没有 action, 也不在话题上** —— 用 `ros2 topic info /robot/move_pose` 查会得到
  `Unknown topic`, 别据此判定"没有运动接口"。

## 7. 全仓"谁能真动机器人"审计结论 (2026-09-18)

`grep -rn "service call /move\|service call /target\|/execute_external\|/hmi/command" --include=*.py --include=*.sh tools/ src/`
→ 唯一会真发运动指令的代码: **`src/lerobot/robots/zmax_orin/robot_zmax_orin.py:247`**
(`ros2 service call /target_relative_joint interfaces/srv/TargetJoint '{sim_mode: false, …}'`, ssh 用户还是过时的 `nvidia@`,
且**无任何调用方 = 孤岛**)。GUI 硬件工具箱只**列出**可达服务, 没有运动按钮。
⇒ 审计这类问题时**用 grep 给结论**, 不要凭印象说"应该没接"。

## 8. 报告纪律 (老倪问真机状态时)

直接给**读数表**(度 + 弧度 + 来源 + 速率 + 两源差 + 力矩) + 时间口径提醒 + 当前能否下发的判定;
**不要**列"可达服务清单/选项让他挑"。被授权后仍然: 单步、限速、指令前后录 `tcp_pose` 真值、
`/robot_stop`(Trigger) 与 `/state_machine/emergency_stop`(Trigger) 一键停在手边; drag 模式一律不下发。
