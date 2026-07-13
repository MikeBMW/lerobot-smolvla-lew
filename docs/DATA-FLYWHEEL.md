# Z-MAX 数据闭环方案 · Data Flywheel

> 小芳(Mac) + xspace(4060) + web(4090)  
> 目标: Orin真机数据 → 混合仿真 → 推理 → 训练 → 部署

---

## 一、数据流

```
Orin (192.168.23.10)         Mac (192.168.23.1)          WSL2/4060        RTX4090
┌─────────────────┐         ┌─────────────────┐        ┌───────────┐    ┌───────────┐
│ RealSense D405  │──RGB──→│ JSON+JPEG HTTP   │        │           │    │           │
│ 640×480 30fps   │  HTTP  │ 缓存 → 混合推理   │──act──→│ Sys-11/12 │──→│ 全部模型   │
│ joint_states 20 │──6D──→│ Sys-1 ACT 42ms   │  gRPC   │ 推理      │    │ 训练      │
│ force_torque    │────────│ 动作输出          │←───────│           │←──│           │
│ gripper_pos     │────────│                   │        │           │    │           │
└─────────────────┘        └─────────────────┘        └───────────┘    └───────────┘
```

## 二、Orin 数据采集 (小芳)

```python
# Orin 上运行的采集服务 (~/.zmax/gateway/)
# HTTP GET http://192.168.23.10:8765/
{
  "joints": [6D],          # 实时关节位置
  "image": "base64_jpeg",  # RealSense 640×480 JPEG
  "gripper": float,        # 夹爪位置
  "force": [6D],           # 六维力
  "ts": timestamp
}
```

关键: 图像用 JPEG 压缩 (≈50KB/帧), 5fps 约 250KB/s 带宽

## 三、Mac 混合推理 (小芳)

```python
# 1. 拉取 Orin 真实传感器数据
data = requests.get("http://192.168.23.10:8765/observation").json()

# 2. 组装 ACT 输入batch
batch = {
    "observation.state": torch.tensor(data["joints"] + [data["gripper"]]),  # 7D
    "observation.images.top": torch.tensor(jpeg_to_tensor(data["image"])),  # 3×480×640
}

# 3. Sys-1 ACT 推理
action = model.select_action(batch)  # 42ms MPS
```

## 四、4060 推理 (xspace)

```python
# Sys-11 SmolVLA 认知推理
smolvla_action = smolvla_model.select_action(batch)  # 215ms 4060

# Sys-12 LeWorldModel 仿真预测
next_state = world_model.predict(current_state, action)
```

## 五、4090 训练 (web)

```python
# 全部模型训练
- ACT 51.6M:  ~2h/epoch (4090)
- SmolVLA 450M: ~8h/epoch (4090)
- LeWorldModel: ~4h/epoch (4090)
```

## 六、数据闭环

```
Orin采集 → Mac推理 → 4060复核 → 4090训练 → 模型部署到Orin
                                        ↓
                                    Orin执行改进后动作
                                        ↓
                                    Orin采集更好的数据 (闭环)
```
