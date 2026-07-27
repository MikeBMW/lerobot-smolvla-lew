---
name: vla-realtime-inference
description: Real-time VLA inference pipeline — Orin camera+joints → SmolVLA → action prediction
platforms: [macos, linux]
---

# VLA 实时推理管线

从 Orin 机器人采集真实相机图像和关节数据，送入 SmolVLA 450M 模型预测动作，输出可视化到飞书。

## 架构

```
Orin (stream_camera.py → /tmp/camera.jpg)
Orin (stream_joints.py → /tmp/joints.json)
Orin (stream_gripper.py → /tmp/gripper.json)
        ↓ SSH cat (免密Key)
Mac Gateway (:8080 FastAPI)
        ↓ HTTP
infer_camera.py → SmolVLA 450M → 动作预测 + 可视化
        ↓
飞书 MEDIA: 发送结果图
```

## 启动

### 1. 确保 Orin 机器人运行中
```bash
ssh nvidia@192.168.23.10 "bash run.sh &"
```

### 2. 启动数据流 (Orin 上)
```bash
# 关节流
ssh nvidia@192.168.23.10 "source /opt/ros/humble/setup.bash && source ~/0615/tashan_robot_so_20260630_163849_f98c30a_aarch64/install/setup.bash && nohup python3 /tmp/stream_joints.py > /dev/null 2>&1 &"
# 相机流
ssh nvidia@192.168.23.10 "source /opt/ros/humble/setup.bash && source ~/.../install/setup.bash && nohup python3 /tmp/stream_camera.py > /dev/null 2>&1 &"
# 夹爪流
ssh nvidia@192.168.23.10 "source /opt/ros/humble/setup.bash && source ~/.../install/setup.bash && nohup python3 /tmp/stream_gripper.py > /dev/null 2>&1 &"
```

### 3. 启动 Gateway (Mac)
```bash
cd ~/lerobot-smolvla-lew/hermes_gateway_mac
.venv/bin/python3 gateway_pure.py --orin-host 192.168.23.10 --port 8080
```

### 4. 启动 VLA 推理 (Mac)
```bash
cd ~/lerobot-smolvla-lew
.venv/bin/python3 infer_camera.py
```

## 模型选择

| 模型 | 参数 | Mac推理 | Orin推理 | 场景 |
|------|------|---------|----------|------|
| **SmolVLA** | 450M | 0.3s (3FPS) | 0.24s (4FPS) | 复杂VLA任务 |
| **ACT** | 51.6M | 0.5ms (2172FPS) | 未测 | 快速实时任务 |
| SmolVLA Mini | 263K | 0.5ms | 未测 | 原型验证 |

详见 `references/performance-benchmarks.md`

## SmolVLA 模型信息

- **模型**: lerobot/smolvla_base (HuggingFace 官方)
- **参数**: 450,046,176
- **骨干**: SmolVLM2-500M-Video-Instruct (冻结, 只取16层VLM)
- **Action Head**: DiT-B Transformer + Flow Matching (非纯MLP, 用Transformer去噪)
- **设备**: Apple M1 MPS GPU / Orin CUDA fp16

## 推理关键坑位

### 1. language tokens + attention mask 强制要求
SmolVLA的`select_action()`必须提供 `observation.language.tokens` + `observation.language.attention_mask`，不管config是否声明。

```python
batch["observation.language.tokens"] = torch.zeros(1, 64, dtype=torch.long, device=DEV)
batch["observation.language.attention_mask"] = torch.zeros(1, 64, dtype=torch.bool, device=DEV)
```

### 2. MPS设备对齐
所有tensor必须在同一device。`torch.randn()`默认CPU导致 `input(device='cpu') and weight(device=mps:0')` 错误。

```python
DEV = next(policy.parameters()).device
batch[key] = torch.randn(1, *shape, device=DEV)
```

### 3. 图像resize到64×64
SmolVLA的SigLIP视觉编码期望64×64输入。

### 4. Orin内存不足无法本地部署
Orin 7.4GB RAM仅剩140MB。SmolVLA需要~2.3GB。Mac推理+Orin采集是最优架构。

### 5. HF下载: Xet CAS 401错误
`RuntimeError: CAS Client Error: HTTP status client error (401 Unauthorized)`
→ 禁Xet: `HF_HUB_DISABLE_XET=1 HF_XET_HIGH_PERFORMANCE=0`
→ 或用镜像: `HF_ENDPOINT=https://hf-mirror.com`

### 6. 飞书输出格式
手机上表格容易错位。用列表格式而非复杂表格。发送图片用 `MEDIA:/path/to/file`。

## 数据格式

- 相机: 480×640 BGR JPEG → resize 64×64
- 关节: 6维 float (XMS5-R800-W4G3B4C)
- 语言: 零token (可扩展指令)
- 输出: 6维连续动作

## 网络要求

- Mac en0: 192.168.23.1
- Orin: 192.168.23.10
- 千兆以太网直连
- SSH Key 免密 (global_authorized_keys +i)
