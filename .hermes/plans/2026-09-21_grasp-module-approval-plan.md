# 抓取光模块 — 待批准动作计划 (老倪批准后执行)

日期: 2026-09-21 · 状态: **待批准** · 硬约束: 已切拖动模式 → 未批准前零指令

## 一、感知与几何现状 (全部实测, 非假设)

| 项 | 状态 | 证据 |
|---|---|---|
| 产线 RealSense 彩色 | ✅ 在线 640x480 | `cam_rs.png` 帧龄 0.06~1s · std 47.9(真图) · tap recv.img 47→涨 |
| 相机内参 K / 畸变 | ✅ 可读 | `/realsense/color/camera_info` (plumb_bob, d 已给) |
| 深度 | ⚠️ 有发布者但默认 QoS 收不到 | 需 BEST_EFFORT 订阅 (待验可用性; 记忆里有"全帧 2-3m"旧坑) |
| 手眼标定 | ✅ 在位, 精度 2.5mm / 0.20° | `calibration/cgb020/camera_extrinsic.yaml` (eye_in_hand_board_on_base, 21 样本, trans RMSE 0.00255m) |
| 产线自带视觉 | ✅ 托盘 YOLO `models/托盘_yolo/best.pt` · 槽位路由 `slot_routes.yaml` (device slot 1..10 → manual_pose_1..10) · `device_relative_points.yaml` | 只读抄口径, 不改 |
| 我方示教点 | ✅ slot1 (0.64711,0.50264,0.11355) · slot2 (0.64832,0.45241,0.11308) · insert_pose · aoi_gold_view | `data/skills/l2_atomic/taught_points.json` (6 帧极差 <1e-6 m) |
| 模块位姿来源 | ❗**未定** | `/robot/tcp_pose` 现在 **0 发布者**(产线主程序未跑) |
| L2 YOLO 检出 | ✅ peg conf 0.84 @ [326,188,371,336] (640x480) | `~/zmax_data/ss_bypass/yolo_detections.json` |
| L1 DeepSeek-VL 判读 | ✅ "两个带绿色拉环的光模块(SFP类), 竖直插在托盘槽内, 绿环朝上, 不在夹爪上" | 同帧真调用 |
| L4 INTACT | ✅ 加载/零搜索通过 · ❗**本域成功率 0/2** (预测 std 塌到教师 7~22%) | `verify_l4_intact_zeroseach` ✅ · `verify_l4_optical_chain` 诚实口径 |
| L3 SmolVLA | ✅ 权重在位 5.7G (LoRA/flow 参数齐) | `--policy.enable_lora_vlm/action_expert` |

## 二、动作计划 (五段, 每段单独请示)

### S0 感知定位 (零指令)
1. YOLO 连续 N=10 帧检出 + 稳定判据 (框中心抖动 <3px)
2. L1(DeepSeek-VL) 场景判读 → `data/scene_state.json` (模块数/位置/朝向/绿环/是否在夹爪上/质量)
3. **几何对账**: 用 K + 手眼 + 当前位姿把 slot1/slot2 投影到图像, 与框对账 → 判定"哪个槽位有模块"
   - 判据: 框-投影距离 < 15px 认账; 否则报"对账失败, 不猜"
   - ❗依赖: 位姿来源 (见待决 ②)

### S1 意图与流程 (零指令, 交你审)
- L4 INTACT → intent (去哪/对准方向); L3 SmolVLA → 技能序列+参数
- 产出: 一页 JSON (意图 + 技能序列 + 每步判据), 给你过目
- 诚实说明: L4 本域 0/2 → 本轮其输出只作**参考意图**, 不承担运动; 运动由 L2 技能收口

### S2 到槽位上方 (第一段真指令)
- 技能: `L2.slot1` 或 `L2.slot2` 的**阶段1** (+30mm 到正上方)
- 判据: TCP 真值到位偏差 ≤1.0mm · 三查 power=on/idle/has_error=false · 夹爪开度读取
- 中止: 任一判据不满足 → 停 + 报告, **不重发**

### S3 视觉微调 + 下降
- 上方取帧(+深度) → 算模块相对夹爪的横向偏差 → >0.5mm 用四方向技能微调(单步 ≤2mm, 累计 ≤10mm)
- 再执行该槽位**阶段2** (-30mm 下降 到抓取位)
- 判据: 到位偏差 ≤0.5mm · 微调方向与图像一致

### S4 合爪 + 抬升
- 合爪 (pos0, force 30 起步; 产线口径: 夹绿环用 force30)
- **免费真值**: 夹爪开度 (空夹≈21 / 夹住模块≈185)
- 抬升 `L2.lift` 30mm
- 判据: 开度读数判夹住/空夹 + TCP 位移真值

### S5 复核与交付
- 抬升后取帧 → L1 复判"模块在夹爪上吗" → 与夹爪开度**交叉验证**
- 成功/失败都如实报, 附帧龄与真值

## 三、安全闸门 (硬约束)
1. 拖动模式 → 零指令 (驱动会拒, 也是你设的防误操作闸门)
2. 每条真指令逐条请示; 只用 L2 注册表技能名
3. 不碰 `/hmi/command` `/execute_external_task` `/state_machine/*` · 不改产线代码
4. 单步最小步长 · 每段独立中止 · 判完成只看真值 (踩过 ROBOT_IDLE_TIMEOUT 假失败)
5. 定位判据不达标 → 报"不确定", 不擅自加力/加距离

## 四、待批准事项
1. S0→S5 顺序与"逐段批准"方式
2. **位姿来源**: (a) 起产线主程序(含 motion) (b) 用新栈 `/arm_a/rokae_driver/cartesian_pose`(50Hz, 需先证同一台臂) (c) 你说一个
3. 先抓哪个: 一号位(slot1) / 二号位(slot2) / 由 YOLO+L1 判定后抓靠外的那个
4. 合爪力: force 30 起步是否可以 (夹不住再加)
5. 视觉微调: 用(更准, 需验深度) / 不用(纯示教点, 重复性 0.4µm)
