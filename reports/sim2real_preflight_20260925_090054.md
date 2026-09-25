# 上真机前预检 (sim-to-real) — 2026-09-25 08:59:14

仿真可跑 **8/8** · 真机只读可用 **5/8** · 待现场 **8** 项

## 功能矩阵
| 功能域 | 仿真可跑 | 真机只读 | 证据 |
|---|---|---|---|
| 仿真引擎 (metaworld 插拔) | ✅ | ✅ | tools/rollout_peg_check.py |
| 状态空间旁路 (吃真机只读感知) | ✅ | ✅ | tools/ss_bypass_run.py (systemd ss-bypass) |
| 流形引擎内核 | ✅ | — | tools/manifold_engine_bench.py |
| 多层 pipeline / MOE 阶段专家 | ✅ | — | tools/moe_engine_bypass.py |
| L5 Web 智能体桥 (提示词↔只读功能) | ✅ | ✅ | tools/verify_web_agent_node.py 27/27 |
| AOI 视觉 (工控机 10082 判决/裁减) | ✅ | ✅ | tools/opt_camera_client.py · verify_opt_camera 40/40 |
| L2 分段技能 (13 段状态机) | ✅ | — | 引擎 mode=insert/full 真跑 |
| 记忆层 (L2/L3/L4 + 总装宏观) | ✅ | ✅ | 记忆层阶梯哨兵 + 引擎记忆条 |

## 服务
| 服务 | 状态 |
|---|---|
| ss-local-infer | active |
| ss-bypass | active |
| ss-remote-tap | active |
| ss-yolo-bypass | active |
| zmax-data-mount | active |
| zmax-net-optimize | active |
| aoi-feishu-push | active |
| zmax-web-agent-bridge | active |
| studio | pid=7718 |
| l2_daemon | 4826 |

## 需现场/授权 (上真机前清单)
- **AOI 首轮标定 (金手指/外观缺陷框选)** — 数据集现 0 标注框
- **10083 表面相机 /picture 路由** — 实测四路由 404 (补丁已交现场)
- **10082 拉长口径 短边×2 补丁 + 裁减对齐 score≥0.95** — 现场侧服务改造
- **2D→3D 标定采集 (哨兵 paused)** — 需在场摆件; box3d_live_box.json ok=false
- **T_base_cam / plane_z 现场测量** — 真机 3D 最后两环
- **ring_pose 示教 (L2.pull_module 合爪未夹住)** — 09-20 未决
- **抓取五段计划 S0~S5 批准 + 位姿来源** — 需人工决策
- **任何真机动作授权** — 老倪红线: 未授权不下发 (本次全程零下发)

耗时 100s · 原始 JSON `sim2real_preflight_20260925_090054.json`
