---
name: zmax-production-state-machine
description: Z-MAX Orin真机生产流程 — 完整插拔工序状态机
tags: [zmax, production, state-machine, orin, 真机]
version: 1.0.6
---

# Z-MAX 生产流程状态机

Orin真机实际运行的生产流程状态机。

## 主循环

```
初始化循环→取料→扫码→插入×2→测试→拔出→AOI×6→OK/NG→循环守卫→取料(循环)
```

## 关键配置

| 参数 | 值 | 用途 |
|:--|:--|:--|
| grasp_threshold | 5N | 触觉抓取力阈值 |
| max_grasp_fail | 2 | 连续失败报警次数 |
| insert_depth | 0.75 | end_pose[0]成功判定 |
| aoi_faces | 6 | AOI检测面数 |
| ng_places | 2 | NG分拣位(25/26) |
| vision_windows | 192.168.23.26 | 视觉服务器IP |
| orin | 192.168.23.10 | Orin Nano IP |

## 文件映射

- 生产主流程: `config/state_machines/orin_production_flow.yaml`
- 视觉管道: `config/state_machines/motion/call_grasp_vision.yaml`
- 主流程入口: `config/state_machines/orin_main_flow.yaml`
- 抓取位姿: `config/state_machines/抓取位姿识别/state_machine.yaml`
- 抓取放置: `config/state_machines/抓取放置/state_machine.yaml`

## AOI检测流程

6个面依次检测: AOI_1 → AOI_2 → AOI_3 → AOI_4 → AOI_5 → AOI_6
任一fail → aoi_fail_flag累加 → 整体判断NG

## 异常处理

- 抓取失败(力<5N): 开爪重试, 连续2次→报警
- 插入失败: 第二次尝试, 仍失败→停机
- 测试FAIL: 直接NG分拣
- AOI fail: 标记NG分拣
