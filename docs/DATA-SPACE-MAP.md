# Z-MAX 全局数据空间映射 v1.0

> 2026-08-02 · 小芳(硬件系统) · 供 web 更新 datadrive.world 数据空间页

## 1. 数据端点总览

| 端点 | 方向 | 用途 | 格式 |
|:---|:---:|:---|:---|
| `POST /api/relay/upload` | Orin→ECS | 数据包上传 | 裸JSON |
| `GET /api/relay/latest` | ECS→训练 | 弹栈拉取(取走即删!) | JSON/binary |
| `GET /api/relay/peek` | ECS→任何 | 只读查看 | JSON |
| `GET /api/relay/status` | ECS→控制台 | 队列状态 | JSON |
| `GET /api/relay/packages` | ECS→控制台 | 包列表 | JSON数组 |
| `GET /api/snapshot/latest` | ECS→控制台 | 快照直播 | JPEG |
| `GET /models/act_cartesian.safetensors` | ECS→Mac/Orin | 模型静态URL(不弹栈) | safetensors |
| `GET /orin/status` | ECS→控制台 | Orin聚合状态 | JSON |

## 2. 数据实体定义

### 采集数据包 (source=orin)
```json
{
  "meta": {"source": "orin", "frames": 96, "n_joint": 6, "n_action": 6},
  "frames": [{
    "observation.state": [6D关节角 rad],
    "action": [6D关节角],
    "label": "取料/扫码/AOI_1/等待测试结果/IDLE",
    "timestamp": 0.0,
    "frame_index": 0,
    "episode_index": 0,
    "camera_b64": "JPEG 320x240"
  }]
}
```

### 快照包 (source=orin_snapshot, 走独立通道)
```json
{
  "meta": {"source": "orin_snapshot", "type": "camera_snapshot"},
  "snapshot_b64": "JPEG 318x180",
  "action": "等待测试结果 + AOI_1 + ...",
  "current_state": "AOI_3",
  "all_states": ["料盘识别", "取料", ...],
  "timestamp": 1785682108.4
}
```

### 推理报告 (source=orin_v2_infer)
```json
{
  "event": "real_infer",
  "model": "act_v2_6d_6d",
  "input_state": [6D],
  "action_step0": [6D],
  "latency_ms": 479.2,
  "time": 1785682108.4
}
```

### 模型
- 静态URL: `/models/act_cartesian.safetensors` (84MB, 覆盖式更新)
- 版本: v2 = state6D→action6D (755帧真机, loss 1.524)
- 推理: 479ms/帧 (CUDA)

## 3. 数据流 (闭环时序)

```
① Orin采集(20s MCAP) → ② upload_data_v2打标+去重
  → ③ POST /api/relay/upload → ④ 静静守护pull
  → ⑤ 训练ACT(2000步) → ⑥ 覆盖静态URL模型
  → ⑦ Mac监听器/手动拉取 → ⑧ scp Orin → ⑨ 推理服务:8766
  → ⑩ 真实推理(orin_real_infer) → ⑪ 报告回传ECS
  → ⑫ cron每10分钟再采集 → 循环
```

## 4. 现场节点 (Orin 192.168.23.66)

| 服务 | 端口 | 说明 |
|:---|:---:|:---|
| orin_gateway.py | 8765 | 采集控制/健康 |
| orin_infer_service.py | 8766 | 推理服务(WS心跳+HTTP) |
| orin_cam15.py | — | 相机直读16fps |
| orin_snapshot.py | — | 快照4fps直播 |
| 07171产线 | 8000 | HMI |
| 视觉主机 | 10081 | MechMind(192.168.23.23) |
| AOI程序 | 10082/10083 | capture_detect |

## 5. 数据一致性铁律

1. 模型传递用**静态URL** (弹栈竞争丢过5次!)
2. 每包**独立episode** (frame_index轨迹内)
3. timestamp**相对秒** (绝对时间戳致torchcodec双重偏移)
4. 图像**320×240 q75**
5. label取motion states **[-1]** (累积数组最后=当前态)
6. 静态帧去重: 关节0.02rad+200ms
7. 快照**独立通道** (不污染relay主队列)
