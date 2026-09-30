# 4060 直连珞石控制器 (不经 Orin) — 可行性实证 2026-09-21

老倪问：**"能不能不启动 Orin 上的 ROS2 工程，由本机（4060）从启动就控制机械臂？"**
答：**机械臂本体可以（读已实证、运动接口齐备）；夹爪暂时不行（缺 x86 SDK）。** 下面是实测证据与缺口。

## 一、已实证（本机 4060，全程零运动指令）

| 项 | 结果 |
|---|---|
| 连通 | 容器内 `xMateRobot().connectToRobot("192.168.23.160")` **0.09s** 成功（Orin 完全不参与） |
| 机型识别 | 控制器回报 `XMS5-R800-W4G3B4C`；类必须用 `xMateRobot`（用 `xMateErProRobot` 会报机型不匹配） |
| 关节真值 | `jointPos()` 6 轴，与 Orin `/real_joint_states` **最大偏差 0.96 µrad**（=0.000055°，编码器噪声级 → 同一真值源） |
| TCP 真值 | `cartPosture(CoordinateType.endInRef)` = `[0.625297, 0.227474, 0.185665]`，与产线 `/robot/tcp_pose` **逐位一致** |
| 其它可读 | `jointVel()`（静止全 0）、`jointTorque()` 六轴力矩、`operateMode`（automatic）、`getStateData()` |
| SDK 来源 | Orin 工作空间 `install/robot_driver/.../rokae/xcoresdk_python/Release/linux/xCoreSDK_python.cpython-310-x86_64-linux-gnu.so`（厂家同时打包了 arm 与 **x86_64** 两套） |
| 运行环境 | SDK 是 `cpython-310` → 本机 3.12 不能直接用；用 `ros:humble-ros-base`（python3.10）容器即可，读数一致 |

复现：`tools/rokae_direct_probe.py`（说明见该文件头部）。

## 二、运动能力（SDK 接口齐备，尚未实动）

`moveAppend`(MoveAbsJ/MoveL 指令) → `moveStart` → 执行；`moveReset` 重置；
`getRtMotionController()` 实时(伺服)控制；`forceControl` 力控；`enableCollisionDetection`；
`setOperateMode`；`calibrateFrame/calibrateForceSensor` 等，共 91 个方法。
⇒ Orin 上 `robot_driver` 的功能，**可以在 4060 上自己实现一份**，不需要 Orin 的 ROS 栈。

## 三、缺口（决定"能不能完全不要 Orin"）

1. **夹爪（硬缺口）**：产线用的 DH 夹爪 SDK `pyDHgripper`（PGHL/RGD/PGC/DH3）**只有 aarch64 .so**，没有 x86 版
   → 夹爪目前跑不到 4060 上。出路：向小芳/厂家要 x86 版，或拿到 Modbus/RS485 协议自己在 4060 实现。
2. **抢占关系（规程缺口）**：SDK 文档明确 —— "RL程序和SDK运动指令切换控制，**需要先运动重置(moveReset)**"。
   产线程序在跑时我要接管必须先 `moveReset`（会清空产线已发指令）；两边同时下发会互相抢。
   ⇒ "完全由我控制"要成立，前提是**产线运动栈不起（或先交权）**。
3. **安全层（责任缺口）**：直连 SDK = 绕开 MES/HMI/急停软件互锁/限位。守卫（Δ/向下限幅/势函数/急停）必须由本机链路自兜。
4. **相机/力控**：RealSense 可在本机直连（不必依赖 Orin 节点）；六维力可从 `jointTorque()` 或产线 tactile/force 节点取。

## 四、建议路径

- 阶段0（已完成）：只读打通 + 同口径校验（本文）。
- 阶段1：本机"独立控制端"最小闭环 = 读状态 + 点位运动 + L2 守卫 + 急停，**首次实动必须走现场闸门**（逐条请示、低速、有人看着）。
- 阶段2：接管演练：产线停机 → `moveReset` → 本机下发一个最小动作（如 J6 +30° 标准字节）→ 真值核对 → 交回产线。
- 阶段3：夹爪 x86 SDK/协议落实后，本机侧才谈"完整替代"。
