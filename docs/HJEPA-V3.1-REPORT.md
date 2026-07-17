# H-JEPA v3.1 模型验证报告

> 小芳 · 2026-07-17

## 模型基础信息

| 指标 | 值 |
|:---:|:---:|
| 参数量 | **2.7M** |
| 文件大小 | 10MB |
| 格式 | PyTorch state_dict |
| 存储路径 | `models/hjepa_zflow_model.pt` |
| 来源 | 4090 训练 (300 epochs) |
| W&B | `xspace/zmax-hjepa` |

## 架构

```
5回路分布式反馈:
回路① 语义 JEPA₃ Enc → Pred → z₃'
回路② 物体 JEPA₂ Enc ← z₃'先验 → Pred → z₂'
回路③ 空间 JEPA₁ Enc ← z₂'先验 → Pred → z₁'
回路④ 跨模态 VLM ↔ GNN ↔ Force
回路⑤ 全局 Action → 环境 → s' → z'

级联: z₃'→z₂→z₂'→z₁→z₁'  (高层先验约束低层)
融合: z₁⊕z₂⊕z₃ → 512D → DiT → Action[14]
推理: 门控关闭 = 零开销
```

## 训练数据

| 来源 | 帧数 | 格式 |
|:---:|:---:|:---:|
| Orin 真机 | 300 帧 | `/zmax/sensor/*` topics |
| 转换 | — | LeRobot .npz (16.4MB) |

## 验证状态

| 检查项 | 状态 |
|:---:|:---:|
| 模型加载 | ✅ |
| 参数量统计 | ✅ 2.7M |
| 权重完整性 | ✅ 无损坏 |
| Mac 推理 | ⏳ 需完整推理代码 |
| Orin 部署 | ⏳ 网络离线 |
