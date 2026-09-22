# J5 力矩超限 · 修复记录 (2026-09-22 08:26)

**结论: 已修好**。一条 SDK 调用 `calibrateForceSensor` 把关节力矩传感器清零即可, **不需要安全密码、不需要厂家**。
J5 从「静止就贴死 22.000 Nm 门槛」变为 **+0.55 Nm(余量 21.35 Nm)**, 现场可正常上电/点动。

## 一、修复前后实测 (SDK 直连控制器 192.168.23.160, 静止 vel 全 0)

| 轴 | 清零前 (Nm) | 清零后 (Nm) | 现场URDF重力模型 (Nm) | 说明 |
|---|---|---|---|---|
| J1 | **+29.08** | **−0.258** | 0.000 | 竖直轴重力恒 0 → 清零前读数 29 Nm 物理上不可能 (= 传感器零点偏置) |
| J2 | −15.78 | −27.58 | +28.92 | 量值吻合 (符号与本文模型约定相反) |
| J3 | −25.17 | +21.62 | −23.05 | 量值吻合, 差 6% |
| J4 | −11.44 | −1.46 | +3.32 | |
| **J5** | **−22.0031** | **+0.5449** | −2.03 | **门槛 22.000 → 修复前余量 −0.003 Nm(越线), 修复后 +21.35 Nm** |
| J6 | +0.85 | +0.17 | −0.12 | |

10 秒稳定性复读 (6 采样): J5 均值 +0.5885 Nm · 极差 **0.1089 Nm** · 全轴极差 0.3911 Nm → **稳定, 非一次性跳变**。

## 二、修法 (可复现)

```bash
# 前置: 机器人静止 (jointVel 全 0) + 末端无外力 + setToolset 负载正确 (本机 mass 1.51kg / cog [16.2,12.9,31.2]mm)
sudo docker run --rm --network host -v ~/zmax_data/rokae_sdk:/sdk -w /sdk \
    ros:humble-ros-base python3 /sdk/fix_torque_zero.py          # 加 --dry 则只读不标定
```
内部就两步: `r.calibrateForceSensor(True, 0, ec)` → 等 3s → 复读六轴对照。
本次返回 `ec={'ec':'0','message':'success'}`, 用时 0.04s (官方: 标定约 100ms, 函数不阻塞)。

## 三、为什么之前没找到 (自我更正)

昨天的问题单里写「SDK 93 个接口中**没有任何力矩/碰撞力限位接口**」—— **是错的**。
正确查法: 读 `~/zmax_data/rokae_sdk/xcoresdk_python/Release/linux/xCoreSDK_python/__init__.pyi`
(带逐接口中文文档的权威声明文件)。`xMateRobot → Cobot_6` 上有:

| 接口 | 用途 |
|---|---|
| `calibrateForceSensor(all_axes, axis_index)` | **力/力矩传感器标定(清零)** ← 本次修法 |
| `enableCollisionDetection(sensitivity[DoF], behaviour, fallback_compliance)` | 碰撞检测灵敏度 **0.01–2.0** (可调) |
| `disableCollisionDetection()` | 关碰撞检测 |
| `enableDrag/disableDrag` | 拖动示教 |

官方文档口径 (docs.rokae.com「力矩控制」页): *"通过 HMI 界面或者 SDK 的 `calibrateForceSensor` 接口执行力传感器标定;
通过 SDK 控制机器人运动时建议程序中调用 `calibrateForceSensor` 接口, 每次运动前标定一下力传感器"* ⇒ 标定是**常规操作**。
错误码表也印证: `-10040 开始拖动失败, 正确设置负载并标定力矩传感器`、`-10005 标定时重置负载失败`。

## 四、根因定性

碰撞保护**没有误动作, 它在按 22.000 Nm 正常保护**; 错的是传感器**零点**:
- 静态(vel=0)J5 实测 22.00 Nm, 而重力模型只有 2.03 Nm; J1 竖直轴读 29 Nm (物理上只能为 0)。
- 控制器自己也报 `#41447 力矩传感器与动力学模型偏差较大 Axis1 sensor_torque 28.15~30.16, torque command -0.000000`。
- 硬重启控制器无效 (重启前后六轴读数 Δ≤0.15 Nm) ⇒ 偏差在**传感器零点**, 不在参数同步。
- 零点丢失的典型诱因 = 先前碰撞/急停(用户提到"前几天碰撞了")。

## 五、遗留与纪律

1. **负载精度**: 标定精度取决于 `setToolset` 的 mass/cog (「不可粗估」)。当前 1.51kg/[16.2,12.9,31.2]mm 是现场已设值;
   若工装/夹爪换过, 应先重量再标定。
2. **每次碰撞/急停/下电后都要重标**: 这类事故会丢零点; 标定 3 秒, 成本极低。建议纳入开机/换工装例程。
3. **不用再转厂家**: 原问题单 (`rokae_j5_torque_issue_report_20260922.md`) 里"要安全密码/厂家介入"的部分作废。
4. 若标定后仍漂回 22 Nm 量级 ⇒ 传感器硬件/参数侧, 才需要厂家。
5. ❌ 不要靠 `setSoftLimit` 抬限值绕过; ❌ 不要常关碰撞检测。

## 六、取证文件

- `~/zmax_data/rokae_sdk/torque_zero_0922_002605.json` (before/after 全量)
- `~/zmax_data/rokae_sdk/torque_stability_0922_002634.json` (10s 稳定性)
- `~/zmax_data/rokae_sdk/probe_state_repair.py` · `fix_torque_zero.py` · `probe_torque_stability.py`
- 前置诊断: `~/zmax_data/arm_j5_torque_diagnosis_20260922.md` · `rokae_sdk/torque_BEFORE_restart.json`
