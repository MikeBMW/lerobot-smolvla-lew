# 小芳 · 数据质量验证方案

> 硬件系统专家 · 2026-07-14

## 验证范围

所有 DDS 数据节点在 Mac 仿真 和 Orin 真机上的发布/订阅质量。

## 验证维度

| 维度 | 方法 | 标准 |
|------|------|:---:|
| **完整性** | 每个 DDS 节点 100 次 publish 测试 | 成功率 >99% |
| **一致性** | Mac 仿真数据 ↔ Orin 真机数据对比 | 偏差 <1% |
| **时效性** | publish→subscribe 延迟测量 | <50ms |
| **格式** | JSON schema 校验 | 字段类型匹配 |
| **稳定性** | 连续 1 小时运行 | 零崩溃 |

## model_skill 数据质量

```python
# 验证传感器数据格式
def verify_sensor_data(node_name, data):
    """校验传感器数据完整性"""
    schema = {
        "sensor_force_6d": [6, float],    # [Fx,Fy,Fz,Tx,Ty,Tz]
        "sensor_joint_6d": [6, float],    # [J1~J6]
        "sensor_gripper": [1, float],     # 夹爪开度
        "sensor_camera": [480, 640, bytes], # RealSense RGB
        "sensor_tactile": [16, float],    # 4×4 触觉阵列
    }
    return validate(data, schema[node_name])
```

## action_skill 质量验证

```
拿取光模块 (100G/400G/800G) → 验证: 力传感器 Fz>5N
插入测试座              → 验证: 深度 >0.75m
AOI检测                → 验证: 6工位通过率
NG分拣                 → 验证: 双料盘切换
扫码                  → 验证: 码值回读匹配
```

## 验证流程

```
xspace DDS 节点推送
  ↓
小芳 Mac 拉取部署 → publish 测试数据 → subscribe 验证
  ↓
Orin 部署 → ROS2 真机数据 → DDS 节点验证
  ↓
报告 → web 数据质量面板
```
