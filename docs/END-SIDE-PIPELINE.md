# Z-MAX 端侧实现方案 (小芳) — 对应 SIMULINK-PIPELINE-DETAILS 第5节

> 版本: v1.1 | 2026-08-05 | 端侧: 小芳 (Orin + Mac)

## 1. Orin / Mac 分工

### Orin (192.168.23.66) — 现场执行

| 服务 | 脚本 | 端口 | 职责 |
|:---|:---|:---:|:---|
| 采集网关 | orin_gateway.py | 8765 | 录制/清理/磁盘守护 |
| 推理服务 | orin_infer_service.py | 8767 | ACT推理+心跳sys |
| 快照直播 | orin_snapshot.py | — | 4fps JPEG+状态上传 |
| 影子模式 | orin_shadow.py | — | sim-to-real对比回传 |
| 相机直读 | orin_cam15.py | — | D405直读(心跳门控) |
| 状态上报 | orin_field_status.py | — | 系统指标→relay |
| 采集上传 | upload_data_v2.py | — | MCAP→打标→上传 |

### Mac (192.168.23.1) — 中转枢纽

| 服务 | 脚本 | 端口 | 职责 |
|:---|:---|:---:|:---|
| 文件服务 | mac_file_server.py | 9000 | 工控机↔Mac传文件 |
| 下载服务 | http.server | 8000 | 工控机拉取脚本 |
| 上网代理 | mac_proxy.py | 9100 | 工控机外网 (launchd托管) |
| 部署监听 | auto_deploy_watch.py | — | relay模型→自动部署 |

**Mac 是唯一同时通公网(ECS)+内网(Orin)的节点** → 大文件(84MB模型)由 Mac 中转下载后局域网秒传 Orin (75KB/s→8M/min)。

## 2. 接口定义

### 端侧对外接口

| 接口 | 方向 | 用途 |
|:---|:---:|:---|
| POST /api/relay/upload | Orin→ECS | 数据包/快照/影子报告 |
| GET /api/relay/{status,peek,latest,packages} | 各端→ECS | 队列查询/拉取 |
| GET /api/snapshot/latest | web→ECS | 实时快照JPEG |
| GET /orin/status | web→ECS | Orin心跳+sys性能 |
| 静态URL /models/act_cartesian.safetensors | 训练→Orin | 模型传递(不弹栈) |
| WS :8766 通知 | ECS→训练 | data_arrived事件 |

### ROS2 话题 (Orin 内)

| 话题 | 类型 | 用途 |
|:---|:---|:---|
| /robot/joint_states | JointState 6D | 关节采集/推理输入 |
| /robot/tcp_pose | PoseStamped | 笛卡尔末端位姿 |
| /realsense/color/image_raw | Image | 相机图像 |
| /motion/active_states | String JSON | 状态标签(states[-1]) |
| /motion/initialization_complete | Bool | 产线就绪判定 |
| /sim_joint_trajectory | 6D | simulink仿真轨迹(静静) |

## 3. 端侧落地手段 (对应管理方法)

### 3.1 自动采集闭环
- cron zmax-auto-collect 每10min: 磁盘守护→就绪检查→采集20s→打标上传
- 静态帧过滤: JOINT_EPS=0.01rad + 200ms窗口 (待机不记录)

### 3.2 模型自动部署
- auto_deploy_watch 30s轮询 relay → 模型到位 → Mac下载 → scp Orin → 重启推理
- 部署后自动推理验证 (orin_real_infer.py, 自动推断state_dim)

### 3.3 影子模式 sim-to-real
- orin_shadow.py: 真机状态+图像 → ACT forward → 4D动作预测 → 对比 → 回传
- 静态帧过滤, 只读绝不发布控制

### 3.4 磁盘守卫
- /disk/guard: mcap ≤1GB, 超了保留10轮删旧
- 快照/影子报告本地+ECS双备份

### 3.5 性能红线
- 我的服务合计 <8% CPU
- 产线进程 (motion/HMI/driver) 绝不触碰
- 心跳sys采集 <1% CPU (排除lo回环)

## 4. 故障恢复矩阵

| 故障 | 恢复 |
|:---|:---|
| Orin重启 | 自启07151→确认切07171 |
| 工控机重启 | 视觉/AOI三服务手动启动 |
| Mac重启 | launchd托管: 代理9100/文件9000/下载8000 |
| ECS 502 | 等待恢复/静态URL兜底 |
| 推理卡死 | kill重启+模型校验 |

## 5. 与 simulink 协同 (接口对齐)

- 静静: simulink 仿真数据 (6D关节+4D动作) → 训练 → metaworld 4D模型
- 小芳: 端侧影子模式验证 (真机对比4D动作) → 回传 shadow_report
- 对齐: /sim_joint_trajectory(6D) 仿真↔ /robot/joint_states(6D) 真机
- 迭代: 影子差异 → 静静训练 → 静态URL → 端侧自动部署 → 再对比 (周而复始)

---
*端侧实现方案 v1.1 · 小芳* | *与 SIMULINK-PIPELINE-DETAILS 第5节对齐*
