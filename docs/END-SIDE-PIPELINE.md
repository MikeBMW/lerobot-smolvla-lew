# Z-MAX 数据闭环端侧实现方案 (小芳·端侧)

> 版本: v1.0 | 2026-08-05 | 维护: 小芳(硬件端侧)
> 配合: 静静(simulink/训练) + web(云端/页面)

## 1. 全链路总览 (流程节点图)

```
┌────────────────────────── 现场层 (Orin 192.168.23.66) ──────────────────────────┐
│                                                                                  │
│  [N1 采集]──[N2 过滤]──[N3 打标]──[N4 上传]──┐                                   │
│      │           │           │              │                                    │
│  相机/关节/力  静态帧过滤    motion状态      relay队列                              │
│  60Hz采集       JOINT_EPS    states[-1]     (JSON)                                │
│                0.01rad+200ms                                                    │
│                                                                                  │
│  [N5 影子]──[N6 对比]──[N7 回传]──┐          │                                    │
│      │           │           │              │                                    │
│  状态+图像      sim模型      shadow_report  │                                    │
│  ACT推理       4D动作       meta=orin_shadow│                                    │
│                                                                                  │
│  [N8 推理]──[N9 心跳]──┐                  │                                      │
│      │           │     │                  │                                      │
│  ACT模型        sys指标  心跳→/orin/status │                                      │
│  :8767          CPU/GPU  cicd显示          │                                      │
└──────────────────────────────┼─────────────┘                                    │
                               ▼                                                   │
┌────────────────────────── 云端 (datadrive.world ECS) ──────────────────────────┐
│                                                                                  │
│  [N10 relay]──[N11 训练]──[N12 部署]──[N13 静态URL]──┐                          │
│      │            │           │           │          │                           │
│  upload/latest   auto_loop   模型推回     act_        │                           │
│  peek/status     WS事件触发   ECS         cartesian.  │                           │
│                                    safetensors        │                           │
└──────────────────────────────┼───────────────────────┘                          │
                               ▼                                                   │
┌────────────────────────── 控制台 (cicd.html) ──────────────────────────────────┐
│  [N14 显示]: 实时画面 / 当前状态 / CPU-GPU-内存-磁盘-带宽 / 模型版本 / 包数      │
└──────────────────────────────────────────────────────────────────────────────────┘
```

## 2. 节点详细说明 (输入/输出/质量要求)

### N1 采集 (orin_gateway.py :8765)
- **输入**: ROS2 话题 (关节60Hz / 力 / 夹爪 / 图像)
- **输出**: MCAP 录制文件 (~/.zmax/mcap/)
- **质量要求**: 每 20s 一轮; 缓冲≤10包; 含 timestamp/frame_index/episode_index (LeRobot必需)

### N2 过滤 (upload_data_v2.py)
- **输入**: MCAP 帧流
- **输出**: 有效帧 (去重后)
- **质量要求**: JOINT_EPS=0.01rad + 200ms时间窗; 静态帧剔除; 图像变化阈值8.0

### N3 打标 (upload_data_v2.py + motion)
- **输入**: 有效帧 + /motion/active_states
- **输出**: label字段 (中文状态名, 取states[-1])
- **质量要求**: 状态标签与时间戳对齐; 空闲无标签→IDLE

### N4 上传 (→ relay /upload)
- **输入**: 打标帧包 (320×240 q75 JPEG)
- **输出**: relay 队列 JSON包
- **质量要求**: 上传成功才删源MCAP; 包≤1MB; meta标记source

### N5 影子 (orin_shadow.py)
- **输入**: 真机状态+图像 → ACT forward(images,state)
- **输出**: 影子动作预测 (4D: dx,dy,dz,gripper)
- **质量要求**: 只读推理,绝不发布控制; 静态帧过滤; 30ms/次

### N6 对比
- **输入**: 影子动作 + 真机实际
- **输出**: 差异统计 (mean/std/max/min)
- **质量要求**: 每60s汇总114样本; 记录infer_ms

### N7 回传 (→ relay, meta=orin_shadow)
- **输入**: shadow_report JSON
- **输出**: relay shadow_reports 存档
- **质量要求**: 本地存档 + ECS双备份; 有动作才记录

### N8 推理 (orin_infer_service.py :8767)
- **输入**: 真机状态 (2D/3D/6D自动推断)
- **输出**: 动作预测
- **质量要求**: 模型自动适配维度; 只读安全信号,严禁真实ros2 action

### N9 心跳 (5s)
- **输入**: /proc 系统指标 (CPU/GPU/内存/磁盘/带宽/温度)
- **输出**: /orin/status sys字段
- **质量要求**: 轻量<1%CPU; 排除lo回环; GPU用tegrastats/频率占比

### N10 relay (ECS)
- **输入**: 各端上传包
- **输出**: upload/latest(弹栈)/peek/status/packages
- **质量要求**: 弹栈竞争已丢5次模型→**铁律:静态URL传递模型**; deploy_meta黑名单

### N11 训练 (auto_loop, 静静)
- **输入**: relay数据 + 仿真metaworld数据
- **输出**: ACT checkpoint
- **质量要求**: WS事件驱动+60s兜底; 断线5s重连

### N12 部署
- **输入**: 模型包 (84MB safetensors)
- **输出**: Orin act_model.safetensors + 推理服务重启
- **质量要求**: Mac中转下载(75KB/s直连太慢); 校验维度后再部署

### N13 静态URL
- **输入**: 训练产物
- **输出**: https://datadrive.world/models/act_cartesian.safetensors
- **质量要求**: 覆盖更新; 不弹栈; last-modified可查

### N14 显示 (cicd.html, web)
- **输入**: /orin/status + /api/snapshot/latest + relay peek
- **输出**: 实时画面/状态/系统指标/模型版本
- **质量要求**: 状态用current_action(states[-1]+8s超时IDLE); 视频4fps

## 3. 数据质量管理 (全链路)

| 维度 | 要求 | 手段 |
|:---|:---|:---|
| **完整性** | 每帧含 timestamp/frame_index/episode_index | 采集端强制 |
| **一致性** | 状态标签与关节时间戳对齐 | 打标取states[-1] |
| **去重** | 静态帧不记录 | JOINT_EPS+200ms |
| **时效** | 快照age<10s | cam/status心跳 |
| **带宽** | 待机静默,动作才传 | 影子+快照静态过滤 |
| **存储** | mcap≤1GB | disk/guard自动清理 |
| **安全** | 推理只读,不发控制 | 影子模式铁律 |
| **模型** | 静态URL传递不弹栈 | relay弹栈黑名单 |

## 4. 全链路管理方法

### 4.1 版本管理
- pipe 工程: 小芳权威 (orin_*.py 端侧脚本)
- gui 工程: 静静 (训练) / web (页面)
- 版本节奏: 小改commit / 中改tag / 大改release

### 4.2 监控
- Orin: 心跳sys (CPU/GPU/内存/磁盘/带宽/温度) → cicd
- relay: packages计数 / peek检查
- 异常: 包数波动=训练拉取(正常); 502=ECS维护

### 4.3 保生产铁律
- 产线进程 (motion/HMI/driver) 绝不触碰
- 我的服务 <8% CPU
- 用户说"保生产"→停监控上传留gateway+infer

### 4.4 故障恢复
- Orin重启: 自启07151旧版→确认切07171
- 工控机重启: 视觉/AOI三服务手动启动
- Mac重启: launchd托管代理9100/文件9000/下载8000

## 5. simulink 协同 (静静配合)

- simulink 仿真数据 → 训练 → metaworld 4D模型
- sim-to-real: 影子模式对比 (端侧) + 迭代训练 (云端)
- 端侧提供: 真机状态/图像/影子动作/差异报告
- 云端提供: 新模型 → 静态URL → 端侧自动部署

---
*端侧实现方案·小芳提交* | *web汇总至cicd页面形成总体方案*
