# Z-MAX 测试任务板 · Test Task Board

> 测试专家: 小芳 · 任务管理: web · 总工: xspace  
> 所有测试→任务映射→验证报告

## 📋 测试任务清单

### ✅ 已完成

| ID | 任务 | 测试项 | 结果 | 报告 |
|:---:|------|------|:---:|------|
| T01 | Orin 连接验证 | SSH免密+网络延迟 | ✅ 0.2ms | `orin-reference.md` |
| T02 | 6轴关节读取 | `/real_joint_states` topic | ✅ 真机通过 | `orin-reference.md` |
| T03 | 相机采集 | RealSense D405 640×480 | ✅ 在线 | 本报告 |
| T04 | 力传感器 | TS-T-15 Fz回读 | ✅ 六维正常 | 本报告 |
| T05 | J6 逆时针10°运动 | `/target_relative_joint` | ✅ 7.1° | 本报告 |
| T06 | Sys-0 安全检查 | 力超阈/关节限位/急停 | ✅ 4层全过 | `sys0_safety.py` 自检 |
| T07 | 仿真桥自检 | 真机数据驱动 | ✅ J6验证 | `orin_sim_bridge.py --test` |
| T08 | 仿真协议 | 编解码+吞吐量 | ✅ 5/5 | `test_simulation_integration.py` |
| T09 | leRobot抽象 | L3仿真模式 | ✅ 通过 | `robot_zmax_orin.py` |
| T10 | 实时监控JSON | 数据格式+分层 | ✅ L0/L1/L2 | `robot-status.json` |
| T11 | 力控带宽统一 | 全局>10kHz→1kHz | ✅ 22文件 | `fcd13e68` |
| T12 | 节拍统一 | 全局<8s→<25s | ✅ 3文件 | `dcbf631f` |

### 🔄 进行中

| ID | 任务 | 测试项 | 状态 | 阻塞 |
|:---:|------|------|:---:|------|
| T13 | 端侧模型部署 | Mac M1 全量推理 | ⏳ | 等xspace Sys-1接口 |
| T14 | Orin Nano 部署 | 代码同步+启动 | ⏳ | Orin需在线 |

### 📋 待开始

| ID | 任务 | 依赖 | 负责人 |
|:---:|------|------|:---:|
| T15 | Sys-1 ACT 底座验证 | xspace 提供接口 | xspace→小芳 |
| T16 | Sys-2 VTLA/GR00T 接口测试 | web 提供API | web→小芳 |
| T17 | Sys-11 SmolVLA 兼容测试 | ACT底座就绪 | 小芳 |
| T18 | Sys-12 LeWorldModel 测试 | SmolVLA就绪 | 小芳 |
| T19 | Orin Nano 端到端 | T13+T14完成 | 小芳 |
| T20 | 真机自动模式运动 | 急停解除 | 小芳+现场 |

## 📊 测试覆盖率

| 系统层 | 已测 | 待测 |
|:---:|:---:|:---:|
| Sys-0 安全 | 4/4 ✅ | — |
| Sys-1 ACT | 0/1 | T15 |
| Sys-2 VTLA/GR00T | 0/1 | T16 |
| Sys-11 SmolVLA | 0/1 | T17 |
| Sys-12 LeWorld | 0/1 | T18 |
| 端侧部署 | 1/3 | T13,T14,T19 |

---

## 📝 测试报告模板

每个测试完成后生成:

```
### TXX: [任务名]
- 日期: YYYY-MM-DD
- 环境: [Mac M1 / Orin / WSL2]
- 输入: [指令/参数]
- 预期: [期望结果]
- 实际: [实测数据]
- 偏差: [差异分析]
- 结论: PASS / FAIL
- 数据: [关键指标]
```

> web 负责任务开启/关闭，关闭时需附详细验证报告
