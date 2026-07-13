# Z-MAX 五层系统接口规范 · Unified Interface Spec

> 静界科技 · 2026-07-12  
> 供 web 前端展示 · 小芳/xspace 联编

---

## 一、系统层定义

| 层 | 模型 | 设备 | 负责人 | 接口 |
|:---:|------|------|:---:|------|
| Sys-0 | 安全层 | Mac M1 | 小芳 | Python API |
| Sys-1 | ACT 51.6M | RTX4060 | xspace | HTTP/gRPC |
| Sys-2 | VTLA/GR00T | RTX4090 | web | gRPC |
| Sys-11 | SmolVLA 450M | RTX4060 | xspace | HTTP |
| Sys-12 | LeWorldModel | RTX4060 | xspace | HTTP |

## 二、数据流

```
相机+关节 → Sys-0(安全检查) → Sys-1(ACT底座) → 动作执行
                                    ↓ 可切换
                              Sys-2(VTLA/GR00T)
                              Sys-11(SmolVLA)
                              Sys-12(LeWorldModel)
```

## 三、Sys-0 接口 (小芳)

```python
# 安全检查
sys0 = Sys0SafetyController()
sys0.ok_to_move(joint_positions=[6])  # → bool

# 力超阈值
sys0.update_force_torque(fx, fy, fz, tx, ty, tz)
sys0.ok_to_move()  # → False if Fz > 5N
```

## 四、Sys-1 ACT 底座接口 (xspace)

```python
from lerobot.policies.zmax_sys1 import ZmaxSys1Policy

model = ZmaxSys1Policy(engine='act')
action = model.select_action({
    'observation.state': tensor(1,14),      # 14D 关节
    'observation.images.top': tensor(1,3,480,640)  # 相机
})
# → [1,1,7] = [6关节 + 夹爪]

# 切换到 Sys-2 VTLA
model.set_engine('vtla')  # 自动路由到 4090:50052
action2 = model.select_action(batch)

# 切换到 Sys-11 SmolVLA
model.set_engine('smolvla')
```

## 五、Sys-2 VTLA/GR00T 接口 (web)

```protobuf
service ZmaxSys2 {
  rpc Predict(SensorData) returns (ActionOutput);
}

message SensorData {
  repeated float joint_positions = 1;     // 6D
  bytes camera_image = 2;                 // 480×640 RGB
  ForceData force = 3;
}

message ActionOutput {
  repeated float target_joints = 1;       // 6D
  float gripper = 2;
  float confidence = 3;
}
```

## 六、Sys-11 SmolVLA 接口 (xspace)

```python
from lerobot.policies.smolvla import SmolVLAPolicy

model = SmolVLAPolicy.from_pretrained("lerobot/smolvla_base")
# 输入: 14D obs + 3×480×640 image
# 输出: 7D action (6关节 + 夹爪)
# 延迟: 42ms ACT / 215ms SmolVLA / ~500ms VTLA
```

## 七、引擎切换表

| 切换 | 代码 | 延迟 | 场景 |
|------|------|:---:|------|
| ACT → SmolVLA | `set_engine('smolvla')` | <5ms | 需要推理 |
| ACT → VTLA | `set_engine('vtla')` | <50ms | 需要大模型 |
| ACT → GR00T | `set_engine('groot')` | <50ms | 需要仿真 |
| 任意 → ACT | `set_engine('act')` | <5ms | 快速响应 |

## 八、实际推理性能

| 引擎 | 设备 | 延迟 | FPS |
|------|------|:---:|:---:|
| ACT | RTX4060 | 8.4ms | 119 |
| ACT | Mac M1 MPS | 42ms | 24 |
| SmolVLA | RTX4060 | 215ms | 4.7 |
| SmolVLA | Mac M1 MPS | 300ms | 3.3 |
| VTLA | RTX4090 | ~500ms | 2 |
| GR00T | RTX4090 | ~800ms | 1.2 |
| Sys-0 | Mac | <0.1ms | — |
