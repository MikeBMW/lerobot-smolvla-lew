# tools/rokae — 珞石控制器只读探针 (xCoreSDK 直连, 不经 Orin)

用途: 从 4060 本机**直连控制器 192.168.23.160** 读真实状态 —— 关节力矩/位姿/模式/工具负载/控制器报警原文。
**全部只读**(connect → 读 → disconnect), 不含任何运动指令。用于真机故障取证与日常体检。

跑法(SDK 是 cpython-310, 本机 3.12 不行 → 用 python3.10 容器; SDK 在 `~/zmax_data/rokae_sdk`):
```bash
cd ~/zmax_data/rokae_sdk
sudo docker run --rm --network host -v $PWD:/sdk -w /sdk ros:humble-ros-base python3 /sdk/<脚本>.py
```

| 脚本 | 读什么 | 典型用途 |
|---|---|---|
| `probe_torque_alarm.py` | 六轴 position/velocity/**torque** + TCP + operateMode/powerState + 接口发现 | 力矩异常/报警时第一时间取真值 |
| `probe_toolset_fields.py` | 工具集(`toolset`)/工具列表(`toolsInfo`)的全部字段: 质量/质心/坐标系 | 核对"设定的末端负载 ≠ 实际" |
| `probe_controller_log4.py` | 控制器日志原文(`queryControllerLog`, error/warning 级, 含 repair 建议) | **最快根因入口**: 拿权威报警原文与限定值 |
| `probe_sdk_all.py` | SDK 93 个接口全列 | 判断某能力(如力矩限位)SDK 到底有没有 |
| `gravity_torque_check.py` | (离线, 不需要机器人) 用 URDF 算当前姿态的**重力模型力矩**并与实测并列 | 判"传感器 vs 模型"是否自洽 |

判据经验(2026-09-22 实证, 详见 `docs/design/real_machine_j5_torque_diagnosis_20260922.md`):
- **竖直轴(本机 J1)的重力力矩在任何姿态恒为 0** ⇒ 它读数非 0 就说明是传感器零点/外部力, 与重力无关
- FK 必须自校: 用 URDF 算出的末端位置与控制器 `cartPosture` 差 ≤ 几 mm 才可用该模型做判据
- 报"力矩超限"时先分清: **真实负载大** vs **读数基线贴门槛** (本机 J5 静止 21.93 vs 限值 22.000)

URDF 副本: `config/robot/xms5_r800_w4g3b4c.urdf` (与 Orin 上现场文件逐位一致)。
