# Z-MAX 分层职责 (老倪 2026-09-19 更正版, v5.10.0 起生效)

| 层 | 名称 | 职责 (一句话) | 真机上的实现 |
|---|---|---|---|
| **LLM 大模型层** | DeepSeek VL | **理解场景** (看清+说清: 目标/位置/朝向/是否在夹爪上/画面质量/背景线索/建议) | `tools/perception_chain_real.py` 的 `l3_vlm` 段 → `data/scene_state.json` |
| **L4** | INTACT | **工作安全 + 物理世界导航** (否决/限幅/恢复预算 · 在哪可以动/怎么走到目标 · 流形世界模型) | 安全闸门 `gate()` + 世界模型/流形 (SS_L4 档) |
| **L3** | 长程序列规划 | **长程序列规划** (把任务拆成阶段/技能序列, 决定先做哪个模块、走哪条路径) | L3 规划器 (画布 大模型层→L3 链), 输出技能序列 JSON |
| **L2** | 肌肉记忆操作 | **肌肉记忆操作** (固化的原子动作序列: 对准/下降/夹紧/抬起, 越练越顺) | `data/skills/l2_muscle/*.json` + `tools/l2_ros2_bridge.py` → Orin ROS2 服务 |

## 真机链路 (一次抓取的真实数据流)
```
真机帧(Orin tap) ──► LLM: DeepSeek VL 场景理解 ─┐
                                              ├─► scene_state.json (单一真源)
YOLO(在役权重) 2D ──► 板坐标系/视觉常数 3D ────┘
        │
        ▼
L4 INTACT: 安全闸门(power/idle/no_error) + 导航(可达性: 目标点是否超范围/奇异点)
        │
        ▼
L3: 长程序列规划 (选目标模块 → 生成技能序列: 对准→下降→夹紧→抬起)
        │
        ▼
L2: 肌肉记忆技能 JSON → l2_ros2_bridge (ROS2 转发节点) → Orin ROS2 服务
        (/move_line · /move_joint · /gripper_driver · /rokae_recover_estop)
```

## 现场作业协议 (人机在环)
- **人操作时机器不下发**: `operation_state=moving/drag` 或人正在示教器操作 → **绝不下发** (读数会被互相干扰, 曾实测到两次无效结果)
- 每步: 三闸门 → 单步下发 → 取证(位姿/开度/图像) → 报人 → 等下一次授权
- `success=False` 且 `error_code=ROBOT_IDLE_TIMEOUT` → **动作通常已完成**, 判据看真值, **绝不重发** (会叠加)
