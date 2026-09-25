# 上真机前预检 (sim-to-real) — 2026-09-25 09:07:05

仿真可跑 **8/8** · 真机只读可用 **6/8** · 待现场 **8** 项 · 全程零动作下发

## 仿真真跑证据 (真 rc + 输出尾)
- **engine_moe_bypass** rc=0 15.3s
  - ``
  - `Notes:`
  - `- UNEXPECTED:	can be ignored when loading from different task/architecture; not ok if you expect identical arch.`
- **engine_l5_vision** rc=0 0.9s
  - `   已有 40 帧 → 从变体 1 续`
  - `✅ L5 造数据完成: 40 帧 / 0s → /tmp/l5_smoke.h5`
  - `   变体方向谱: 1 个 (对位偏差 × 阶段 × 力档 × 速度)`
- **policy_rollout_state_space** rc=0 4.1s
  - ``
  - `🎯 state_space: 0/1 次插入成功 (0%) | 抬起 0/1 | 最小孔距 0.335m`
  - `WARNING:lerobot.configs.policies:Device 'None' is not available. Switching to 'cuda'.`
- **manifold_engine** rc=0 4.6s
  - `}`
  - `→ /home/ubuntu/lerobot-smolvla-lew/reports/manifold_engine_bench.json`
  - `MANIFOLD_BENCH_DONE`
- **bypass_live_infer** rc=None s

## 功能矩阵
| 功能域 | 仿真可跑 | 真机只读 | 证据 |
|---|---|---|---|
| 仿真引擎 (metaworld 真物理 + MOE pipeline) | ✅ | ✅ | tools/moe_engine_bypass.py |
| 造数据管线 (引擎+渲染真像素) | ✅ | ✅ | tools/l5_plan_and_gen.py --vision 1 |
| 状态空间旁路 (真机只读帧→本机推理) | ✅ | ✅ | ss-bypass service + 8790 infer_count 增量 |
| 流形引擎内核 | ✅ | — | tools/manifold_engine_bench.py (MANIFOLD_BENCH_DONE) |
| 通用策略 rollout (state_space 权重) | ✅ | — | tools/rollout_peg_check.py --policy state_space (链路通; 该权重此口径 0/1 插入, 引擎自口径另计) |
| L5 Web 智能体桥 (提示词↔只读功能) | ✅ | ✅ | tools/verify_web_agent_node.py 27/27 |
| AOI 视觉 (10082 判决/裁减只读) | ✅ | ✅ | tools/opt_camera_client.py · verify_opt_camera 40/40 |
| 记忆层 (L2/L3/L4 + 总装宏观) | ✅ | ✅ | 记忆层阶梯哨兵 + 引擎记忆条 |

## 真机只读实测
- Orin: rtt min/avg/max/mdev = 0.133/0.225/0.292/0.067 ms
- 工控机路由: {'10082/picture': '200', '10083/picture': '404', '10082/crop_info': '200', '10083/crop_info': '404', '10082/region': '200', '10083/region': '404', '10082/last_result': '200', '10083/last_result': '404', '10082/capture_detect': '200', '10083/capture_detect': '200'}
- 10082 判决: {"code": 200, "count": 0, "defects": [], "detect_type": "gf", "ms": 1563.5, "n": 148, "origin": "./goldfinger_images\\Finger_Image_W2448_H2048_No_288.png", "saved_incoming": "D:\\AOI_images\\gf\\incoming\\20260924_210141_295.png", "t": 1790254903.3245122, "topview": "./goldfinger_images\\Finger_TopV

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

## 今日修复 (上真机前打通仿真链路的两个真 bug)
- tools/rollout_peg_check.py 硬编码 os.chdir('/home/xspace/lerobot-smolvla-lew') (别的机器路径) → 改按本文件推仓库根
- tools/rollout_video.py load_policy 缺 left_right/state_space 分支 → 用 SmolVLALewPolicy 装载左手权重报 TypeError → 补分支 LoadPolicy=LeftRightPolicy

## 需现场/授权
- **任何真机动作授权** — 老倪红线: 未授权不下发 (本次全程零下发, 只读)
- **AOI 首轮标定 (金手指/外观缺陷框选)** — 数据集现 0 标注框 (4 张 960×960 图已同源)
- **10083 表面相机 /picture 路由** — 实测仍 404 (补丁 docs/patch/opt_surface_10083_add_picture_route.md 已交现场)
- **10082 拉长口径 短边×2 + 裁减对齐 score≥0.95** — 现场侧服务改造
- **2D→3D 标定采集 (哨兵 paused)** — 需在场摆件; box3d_live_box.json ok=false
- **T_base_cam / plane_z 现场测量** — 真机 3D 最后两环
- **ring_pose 示教 (L2.pull_module 合爪未夹住)** — 09-20 未决
- **抓取五段计划 S0~S5 批准 + 位姿来源** — 需人工决策

耗时 35s · 原始 JSON `sim2real_preflight_20260925_090740.json`
