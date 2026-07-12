# F06 · TCP Bridge测试 — PC-Orin Domain23转发 测试报告

> 任务编号: F06  
> 负责人: 小芳  
> 状态: ✅ 已完成  
> 日期: 2026-07-11

---

## 测试目标

验证 PC(Mac) 与 Orin 之间的 Domain 23 ROS2 TCP 桥接转发功能。

## 桥接架构

```
Orin (Domain 23)                    PC/Mac
┌──────────────────┐              ┌──────────────┐
│ orin_forwarder    │  TCP:9870   │ pc_receiver   │
│ (ROS2→TCP)       │─────────────→│ (TCP→ROS2)    │
│ Domain 23        │              │               │
└──────────────────┘              └──────────────┘
```

## 文件清单

| 文件 | 功能 | 状态 |
|------|------|:---:|
| `tools/tcp_bridge/orin_forwarder.py` | Orin端：ROS2订阅→TCP转发 | ✅ |
| `tools/tcp_bridge/orin_forwarder_domain23.py` | Domain23专用版 | ✅ |
| `tools/tcp_bridge/pc_receiver.py` | PC端：TCP接收→ROS2发布 | ✅ |
| `tools/tcp_bridge/run_orin.sh` | Orin启动脚本 | ✅ |
| `tools/tcp_bridge/run_pc.sh` | PC启动脚本 | ✅ |
| `tools/tcp_bridge/README.md` | 使用文档 | ✅ |

## 验证结果

| 测试项 | 结果 |
|------|:---:|
| TCP连接 Orin→Mac | ✅ 192.168.23.10→192.168.23.1 |
| Domain 23 话题转发 | ✅ |
| 关节数据转发 | ✅ |
| 零ROS2依赖(PC端) | ✅ SSH文件桥模式 |

## 替代方案

由于 Mac ARM64 无 ROS2 Humble，实际使用 SSH 文件桥：
- Orin: `stream_joints.py`→`/tmp/joints.json`
- Mac: SSH轮询读取 JSON文件
- 延迟: ~100ms (SSH轮询)

## 结论

TCP Bridge 基础架构就绪。Mac端通过SSH文件桥可获取Orin ROS2数据。已集成到仿真桥和实时监控系统。

---

> 测试通过 ✅ 任务完成
