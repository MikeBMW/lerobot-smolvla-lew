# Z-MAX SmolVLA 训练方案

> 决策文档 · 2026-07-08 · 智蜂创元(ZFCY)

---

## 一、SmolVLA 原始论文方法

### 架构
- **视觉编码器**: SmolVLM-2 (500M) — 处理 VLM 视觉+语言输入
- **动作头**: Flow-Matching Transformer (DiT-B, 262M)
- **总参数**: 450M (含 VLM) / 262M (仅动作头)
- **推理**: 异步推理，动作预测与执行解耦，平均减少30%任务时间

### 训练方法
```
Fine-tune模式:
  python lerobot/scripts/train.py \
    --policy.path=lerobot/smolvla_base \
    --dataset.repo_id=lerobot/svla_so101_pickplace \
    --batch_size=64 --steps=20000

从头训练模式:
  python lerobot/scripts/train.py \
    --dataset.repo_id=lerobot/svla_so101_pickplace \
    --batch_size=64 --steps=200000
```

### 训练数据集
| 数据集 | 用途 | Episodes | 环境 |
|--------|------|----------|------|
| PushT | 基础运动验证 | 10+ | 2D推块 |
| Metaworld MT50 | 多任务泛化 | 50任务 | 仿真机械臂 |
| LIBERO | 长程任务 | 多种 | 仿真+真实 |
| SO101 Pick-Place | 精细操作 | 50 | SO100真实臂 |

---

## 二、Z-MAX 硬件约束

| 资源 | 现状 |
|------|------|
| GPU | RTX 4060 Laptop · 8GB VRAM |
| RAM | 10GB |
| 磁盘 | 711GB 可用 |
| CUDA | 12.7 |
| LeRobot | v0.5.2 (conda lerobot) |

**约束分析**:
- SmolVLA 完整训练 (450M) 需约 16GB VRAM → **8GB不够**
- DiffusionPolicy 训练 (262M) 需约 4GB VRAM → **可以**
- 微调 SmolVLA (freeze VLM) 可能剪枝后可行

---

## 三、推荐训练方案

### Phase 1: DiffusionPolicy 基线 ✅ 已完成

```
数据集: PushT (10 episodes, 1,347 frames)
模型: DiffusionPolicy (262M)
结果: 100步 · Loss 1.16→0.078 (93.3%↓)
时间: ~2分钟
```

### Phase 2: Metaworld 多任务验证 (推荐下一步)

```bash
# 数据集: lerobot/metaworld_mt50
python lerobot/scripts/train.py \
  --dataset.repo_id=lerobot/metaworld_mt50 \
  --batch_size=4 --steps=500 \
  --output_dir=outputs/train_002_metaworld \
  --policy.device=cuda
```

**预期**: 多任务泛化能力验证，Loss < 0.1

### Phase 3: Orin 真实数据微调 (核心交付)

```bash
# Step 1: Orin上录制 MCAP
ros2 bag record -s mcap -o orin_insertion \
  /realsense/color/image_raw \
  /robot/joint_states \
  /robot/force_torque \
  /gripper_pos

# Step 2: MCAP→LeRobot格式转换
python tools/convert_mcap_to_lerobot.py \
  --input orin_insertion.mcap \
  --output ~/.cache/huggingface/datasets/zfc7/orin_insertion

# Step 3: 微调预训练动作头
python lerobot/scripts/train.py \
  --policy.path=outputs/train_001_diffusion_pusht/policy.pt \
  --dataset.repo_id=zfc7/orin_insertion \
  --batch_size=2 --steps=200 \
  --output_dir=outputs/train_003_orin_finetune \
  --policy.device=cuda
```

### Phase 4: SmolVLA 完整训练 (需硬件升级或云GPU)

如果未来获得更大显存（RTX 4090 24GB 或云GPU）:

```bash
# 加载 SmolVLA 预训练基础模型 + Orin 数据微调
python lerobot/scripts/train.py \
  --policy.path=lerobot/smolvla_base \
  --dataset.repo_id=zfc7/orin_insertion \
  --batch_size=8 --steps=5000 \
  --output_dir=outputs/train_004_smolvla_orin \
  --policy.device=cuda \
  --policy.freeze_smolvlm=true  # 冻结VLM，只训动作头
```

---

## 四、数据复用策略

### 4.1 可用数据源

| 来源 | 类型 | 大小 | 用途 |
|------|------|------|------|
| PushT (缓存) | 仿真2D | 1.3K帧 | 基线验证 |
| Metaworld MT50 | 仿真3D | ~50K帧 | 多任务泛化 |
| Orin rosbag | 真实数据 | 338MB→3.3MB.rrd | 域适配微调 |
| Orin 新采集 | MCAP | 实时录制 | 大量真实数据 |

### 4.2 数据流

```
Orin录制 MCAP ──→ 转换为LeRobot Dataset ──→ 本地缓存
                                              ↓
PushT + Metaworld ──→ 预训练 DiffusionPolicy ──→ 基础动作头
                                                        ↓
Orin 真实数据 ──→ 微调动作头 ──→ Z-MAX 部署模型
```

---

## 五、实施路线图

| 阶段 | 数据集 | 模型 | 步数 | 预期Loss | 状态 |
|------|--------|------|------|----------|------|
| Phase 1 | PushT | DiffusionPolicy | 100 | 0.078 | ✅ 完成 |
| Phase 2 | Metaworld MT50 | DiffusionPolicy | 500 | <0.15 | ⏳ 计划中 |
| Phase 3 | Orin 真实数据 | DiffusionPolicy微调 | 200 | <0.10 | ⏳ 等待Orin |
| Phase 4 | Orin + 多源 | SmolVLA(freeze VLM) | 5000 | <0.05 | 🔮 需GPU升级 |

---

## 六、当前最优建议

**基于 RTX 4060 8GB 的约束，推荐路径**:

1. **立刻可做**: Metaworld MT50 训练（Phase 2）— 验证多任务泛化
2. **Orin上线后**: 采集 50-100 个真实插拔 episode，微调动作头（Phase 3）
3. **GPU升级后**: SmolVLA 完整训练

**一句话**: 先用 DiffusionPolicy 在 Metaworld 上验证多任务能力，等 Orin 数据到位后微调，保持轻量可部署。
