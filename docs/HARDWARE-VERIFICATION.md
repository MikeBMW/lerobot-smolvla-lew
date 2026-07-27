# 硬件验证 · 动作技能量化指标

> 小芳 @ 2026-07-14 · 每项动作技能都有硬件可测指标

## 动作技能 → 量化指标映射

| action_skill | DDS节点 | 量化指标 | 传感器 | 标准 |
|:---:|:---:|:---|:---|:---:|
| 取料100G | `action_pick_100g` | grasp_force >5N | 触觉 | 抓取力 |
| 取料400G | `action_pick_400g` | grasp_force >5N | 触觉 | 抓取力 |
| 插入测试座 | `action_insert` | depth >0.75m, Fz=6N | TCP+力 | 深度+力 |
| 拔出 | `action_pull` | retreat_z = 0.12m | TCP | Z位移 |
| AOI检测×6 | `action_aoi_1~6` | code=200, detect_count>0 | 视觉 | HTTP响应 |
| NG分拣 | `action_ng_sort` | ng_place_count轮换 | 状态机 | 双料盘切换 |
| 扫码 | `action_scan` | barcode回读匹配 | Honeywell | 码值校验 |
| 夹爪控制 | `action_gripper` | pos:0~1, force:40N | 夹爪驱动 | 位置+力 |

## 硬件验证方法

```python
def verify_action(skill_name, dds_node):
    """硬件验证动作技能"""
    data = gds.get(dds_node)
    metrics = ACTION_METRICS[skill_name]
    
    results = {}
    for metric, (fn, threshold) in metrics.items():
        value = fn(data)
        results[metric] = {
            "value": value,
            "threshold": threshold,
            "pass": value >= threshold if ">" in str(threshold) else value == threshold
        }
    return results

ACTION_METRICS = {
    "action_pick_100g": {
        "grasp_force": (lambda d: d.get("force", 0), ">5N"),
        "tactile_cells": (lambda d: len(d.get("tactile",[])), "16"),
    },
    "action_insert": {
        "depth_m": (lambda d: d.get("pose",[0])[0], ">0.75"),
        "force_z": (lambda d: abs(d.get("force",[0,0,0])[2]), "6N"),
        "latency_ms": (lambda d: d.get("latency",0), "<2000"),
    },
    "action_aoi": {
        "code": (lambda d: d.get("code",-1), "200"),
        "detect_count": (lambda d: d.get("count",0), ">0"),
    },
}
```

## 验证流程

```
Orin 执行动作 → DDS pub action_* → Mac subscribe
  → 提取指标 vs 阈值 → PASS/FAIL
  → 写入 DDS quality_* 节点 → web 看板显示
```

## 与 model_skill 的关系

```
action_skill: 硬件执行, 量化验证 (小芳)
      ↑ 动作数据
model_skill: 多模态训练数据 (web)
      ↑ 数据回流
DDS: 全局数据空间 (xspace)
```
