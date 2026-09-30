# Z-MAX 数据闭环流程 · 全链路定义 v1.0

> 2026-08-02 · 小芳(硬件系统) · 基于当日实机验证的完整闭环

## 1. 系统架构（当前真实状态）

```
┌─────────────────────────────────────────────────────────────────────┐
│                        现场层 (Orin 192.168.23.66)                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │robot_driver│ │  motion   │  │ 相机直读      │  │ 快照服务      │    │
│  │6关节驱动   │ │状态机27态  │  │orin_cam15    │  │orin_snapshot │    │
│  └──────────┘  └──────────┘  │ 424×240@16fps │  │4fps+动作叠加  │    │
│      │              │        └──────────────┘  └──────────────┘    │
│      ▼              ▼             │                    │            │
│  ┌──────────────────────────┐     ▼                    ▼            │
│  │  orin_gateway.py :8765   │  /realsense/color/   /api/snapshot/  │
│  │  采集MCAP+录制控制        │  image_raw            latest(静态)   │
│  └──────────────────────────┘                                       │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ scp/ssh
┌───────────────────────────────▼─────────────────────────────────────┐
│             中转层 (Mac 192.168.23.1 — 唯一通公网+Orin)               │
│  auto_deploy_watch.py (监听relay新模型→部署Orin)                      │
│  orin_real_infer.py (真实推理验证, 自动推断维度)                       │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ HTTPS
┌───────────────────────────────▼─────────────────────────────────────┐
│            云端层 (ECS datadrive.world)                              │
│  /api/relay/upload   ← 数据包上传 (裸JSON)                            │
│  /api/relay/latest   ← 弹栈拉取 (取走即删!)                          │
│  /api/relay/peek     ← 只读查看                                     │
│  /api/snapshot/latest← 快照直播 (200/JPEG)                           │
│  /models/act_cartesian.safetensors ← 模型静态URL (永久, 不弹栈!)     │
│  cicd.html           ← 数据闭环控制台                                │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ 40s/84MB (4060→ECS)
┌───────────────────────────────▼─────────────────────────────────────┐
│            训练层 (4060 静静)                                        │
│  relay_train.py pull → 构建LeRobot数据集 → 训练ACT → 覆盖静态URL      │
│  守护进程: 检测新数据→自动训练→自动推模型 (855b1bd5修复)               │
└─────────────────────────────────────────────────────────────────────┘
```

## 2. 数据流定义（闭环时序）

```
① 采集:    Orin 20s MCAP录制 (网关:8765)
② 打标:    upload_data_v2.py 读MCAP → 帧提取 + motion状态标签 + 去重
③ 上传:    裸JSON POST /api/relay/upload
④ 训练:    静静守护 pull → LeRobot格式 → 训练ACT (2000步)
⑤ 推模型:  覆盖 /models/act_cartesian.safetensors (静态URL!)
⑥ 部署:    Mac监听器 或 手动 curl+scp → Orin act_model.safetensors
⑦ 推理:    orin_real_infer.py (真实关节/位姿 → 动作块)
⑧ 再采集:  cron zmax-auto-collect (每10分钟)
```

## 3. 场景定义

### 场景A: 光模块400G AOI产线 (当前)
- 6关节珞石SR5 + 夹爪 (非7电机)
- 视觉: MechMind 192.168.23.23:10081 (project_id=1) + AOI程序 10082/10083
- 动作: 料盘识别→取料→扫码→尝试插入→AOI_1-6→等待测试结果 (27态状态机)
- 控制: ExecuteExternalTask (entry_state=main.yaml流程级裸名)

### 场景B: Simulink 仿真 (System 0 Sim)
- simulink_hw_server.py sim模式 (30Hz, 4话题)
- 无motion状态机 → 标签=IDLE
- 用于算法预研/流程演练

### 场景C: metaworld 仿真 (静静)
- mujoco 3.3.0 + metaworld
- 真实渲染图像 (var>4000)
- 用于视觉算法验证

## 4. 功能定义

### 数据格式 (每帧, LeRobot必需)
```json
{
  "observation.state": [6D关节或3D位姿],
  "action": [6D关节或4D末端速度],
  "label": "取料/扫码/AOI_1/等待测试结果/IDLE",
  "timestamp": 0.0,       // 相对秒(episode内)
  "frame_index": 0,        // 轨迹内索引
  "episode_index": 0,      // 每包独立episode
  "camera_b64": "JPEG 320x240 q75"
}
```

### 模型规格
| 版本 | state | action | 数据 | 推理 |
|:---:|:---:|:---:|:---|:---:|
| v1 | 3D位姿 | 4D末端速度 | 仿真 | 1051ms |
| v2 | 6D关节 | 6D关节 | 755帧真机 | 479ms |
| v3+ | 待部署 | | 持续采集 | 自动 |

### 关键接口
```
Orin 网关:  POST /record/start?duration=20  GET /record/status
推理服务:   GET /status  (model_size, infer_count)
模型URL:    https://datadrive.world/models/act_cartesian.safetensors
快照:       https://datadrive.world/api/snapshot/latest
```

## 5. 数据一致性规则

1. **模型传递用静态URL** (弹栈队列竞争丢失过5次!)
2. **每包独立episode** (frame_index轨迹内, 不跨视频超界)
3. **timestamp必须相对秒** (绝对时间戳导致torchcodec双重偏移)
4. **图像320×240 q75** (64×64训练视觉弱)
5. **label从motion状态机取[-1]** (累积数组最后=当前态)
6. **静态帧去重** 关节0.02rad+200ms窗口
7. **快照走独立通道** (不污染relay主队列)

## 6. 控制台 (cicd.html) 数据源

| 显示 | 数据源 | 真实? |
|:---|:---|:---:|
| Orin状态 | /orin/status (ECS聚合) | ✅ |
| 模型版本 | /orin/status | ✅ |
| 推理次数 | infer_count | ✅ |
| 直播画面 | /api/snapshot/latest | ✅ |
| 队列 | /api/relay/status | ✅ |
| 动作状态 | current_state (快照JSON) | ✅ |
