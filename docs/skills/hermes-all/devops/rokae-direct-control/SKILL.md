---
name: rokae-direct-control
description: "Use when 本机直连珞石控制器(绕开Orin)读状态或控臂。"
version: 1.0.0
author: agent
tags: [zmax, rokae, xcoresdk, direct-control, robot-arm]
platforms: [linux]
---

# 本机(4060) 直连珞石控制器 — 不经 Orin 的独立控制 (2026-09-21 实测通)

## 何时用
- 老倪问「能不能不启动 Orin 上的工程，本机从头控制机械臂」
- 要在本机读真值(关节/位姿/力矩)而不依赖 Orin 的 robot_driver
- 产线 ROS2 栈没起、但要看机械臂状态或要自己算守卫 Δ

## 关键事实（一次说清）
- 控制器 IP: **192.168.23.160**（珞石 XMS5-R800-W4G3B4C），本机 ping 0.09ms 可达
- SDK: 厂家 xCoreSDK，在 Orin 工作空间
  `.../install/robot_driver/lib/python3.10/site-packages/robot_driver/rokae/xcoresdk_python/`
  —— **同时打包 arm 与 x86_64 两套 .so**（`Release/linux/xCoreSDK_python.cpython-310-x86_64-linux-gnu.so`）
- SDK 是 **cpython-310** 扩展：本机 3.12 不能直接用 → 用 `ros:humble-ros-base`（python3.10）容器跑，
  挂 `~/zmax_data/rokae_sdk`，`--network host`
- 机型类必须匹配：XMS5 → **`xMateRobot`**；用 `xMateErProRobot` 会报
  `Robot instance type does not match with the connected robot XMS5-R800-W4G3B4C`
- API 形状：几乎每个方法都要 **`ec` 错误码 dict**（`r.jointPos({})`）；`connectToRobot(ip)` 无返回值，
  靠异常报错；`cartPosture(CoordinateType.xxx, {})` 需要坐标系参数
- 同口径：`CoordinateType.endInRef` = 工具系在参考系 = 产线 `/robot/tcp_pose` 口径（实测逐位一致）；
  `flangeInBase` 是法兰（比 TCP 少了工具偏移，差 15~23cm，别混）

## 步骤
```bash
# 1) 拷 SDK 到本机（含两套 .so，17M）
mkdir -p ~/zmax_data/rokae_sdk
ssh tashan@192.168.23.66 "cd /home/tashan/0810/<ws>/install/robot_driver/lib/python3.10/site-packages/robot_driver/rokae && tar -cf - xcoresdk_python" \
  | tar -C ~/zmax_data/rokae_sdk -xf -
# 2) 只读探针（零运动）
sudo docker run --rm --network host -v ~/zmax_data/rokae_sdk:/sdk -w /sdk ros:humble-ros-base python3 /sdk/rokae_direct_probe.py
```
仓库里有现成脚本：`tools/rokae_direct_probe.py`（读关节/速度/力矩/TCP/模式，落 JSON）。
校验口径：与 Orin 的 `/real_joint_states`、`/robot/tcp_pose` 对比，偏差应是 µrad / 逐位一致。

## 实测证据（可引用）
| 项 | 值 |
|---|---|
| 连接 | 0.09s 成功，Orin 不参与 |
| 关节 | 与 `/real_joint_states` 最大偏差 **0.96 µrad** |
| TCP | `endInRef` 与 `/robot/tcp_pose` 逐位一致 |
| 额外可读 | `jointVel`、`jointTorque`（六轴力矩）、`operateMode`、`getStateData` |

## 运动侧（接口齐备，尚未实动）
`moveAppend(...) → moveStart()`（点位）；`moveReset()`；`getRtMotionController()`（实时/伺服）；
`forceControl`；`enableCollisionDetection`；`setOperateMode`。共 91 个方法 → Orin `robot_driver` 的功能可在本机自实现。

## 坑 / 红线（务必先看）
1. **接管前必须 `moveReset`**：SDK 文档原文「RL程序和SDK运动指令切换控制，需要先运动重置」→
   产线在跑时你一发运动就是抢控制，两边同时下发会互抢。**"完全由我控制"= 产线运动栈不起或先交权**。
2. **夹爪暂时跑不到本机**：DH 夹爪 SDK `pyDHgripper` 只有 `aarch64-linux-gnu.so`，没有 x86 版
   → 要 x86 SDK，或拿 Modbus/RS485 协议自己实现。别以为"机械臂能直连 = 夹爪也能"。
3. **安全层要自兜**：直连绕开 MES/HMI/急停软件互锁 → Δ 守卫、向下限幅、势函数、急停必须挂在本机链路上。
4. 首次实动一律走现场闸门（逐条请示、低速、有人看着），并用真值核对（不看 success）。
5. 只读探针也别在产线节拍里高频连——控制器的 SDK 会话是共享资源。
