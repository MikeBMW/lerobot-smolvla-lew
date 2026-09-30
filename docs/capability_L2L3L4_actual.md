# Z-MAX 状态空间实际能力 — L2/L3/L4 功能整理 (2026-09-09 老倪: 按实际状态空间模型)

> 依据: 引擎 state_space_sim_real.py (insert/full 双模式) · 实际模型文件 · 画布三级行 · 可跑断言组
> 分级语义 (老倪): L2 基础辅助=分段小模型 / L3 高级自动=端到端模仿学习 / L4 专家自主=世界模型技术

## 🗺 状态空间模型实际架构 (一条完整链)

```
模式: insert (插入完成) / full (插拔+AOI 13段闭环) — 引擎双模式实际可跑
物理: metaworld MuJoCo peg-insert-side-v3 (seed 布局随机, 现场几何动态采样)
模型: ss_left_brain.npz (左脑 前馈MLP 2.1MB) + ss_right_brain.npz (右脑 WM 344KB)
      + smolvla_lew_v8 (VLM 冻结 + DiT ActionHead + LEW, 微调训练中)
```

## 🔧 L2 基础辅助功能 (分段式小模型 — 单段可靠, 人在环)

| ID | 功能 | 实际载体 | 状态 |
|---|---|---|---|
| L2-A01 | 目标检测 | YOLO (yolo_3d/yolo_state_aligner) 检 peg/孔/末端 | ✅ 真跑 |
| L2-A02 | 2D→3D 解算 | yolo_state_aligner.detect_3d (cam_mat0 反投影) | ✅ 真跑 |
| L2-A03 | 触觉感知 | gen_tactile.synth_tactile + 真实力觉 | ✅ |
| L2-A04 | 状态融合 | perception.fuse_sensors → 43D obs | ✅ |
| L2-A05 | 前馈建议 | parallel.FeedforwardAccelerator (左脑 MLP / 解析) | ✅ |
| L2-A06 | 状态机调度 | cognition.ActionModulator 13段 (接近→…→完成, 否决权) | ✅ |
| L2-A07 | 安全边界 | safety.saturate 饱和限幅 | ✅ |
| L2-A08 | 原子技能 | SK01-08 分段模板 | ✅ |
| L2-A09 | 插拔工艺 | insert 模式闭环 (引擎 R0/R1) | ✅ 实测成功 |
| L2-A10 | AOI 检测流程 | full 模式 AOI 段 (quality_check) | ✅ |
| L2-A11 | 物理执行 | execution.RobotExecutor + PhysicalWorld (metaworld) | ✅ |

**L2 本质**: 每段有明确规则/小模型, 失败交还人 (辅助驾驶 L2: 车道保持+ACC)

## 🚀 L3 高级自动功能 (端到端模仿学习 — 整任务自主, 已训练)

| ID | 功能 | 实际载体 | 状态 |
|---|---|---|---|
| L3-B01 | 通用视觉编码 | SmolVLM2-500M (vlm_encoder) 图像/视频/触觉 → 潜空间 z960 | ✅ 权重+真推理 |
| L3-B02 | 任务规划 | 规则/LLM 可插拔规划器 → 技能序列 | ✅ |
| L3-B03 | 动作头解码 | DiT ActionHead (smolvla_lew) z → action 块 | ✅ 已训练 |
| L3-B04 | 双通路执行 | DiT 动作直通 + 肌肉记忆固化 (画布 lkdc_act/lkdc_ff) | ✅ |
| L3-B05 | 端到端演示 | full 链端到端自主 (VLM 编码每帧 → 动作 → 闭环) | 🔄 训练收敛中 |

**L3 本质**: 给任务指令 → VLM+DiT 端到端出动作, 特定场景自主 (NOA 类比)

## 🏆 L4 专家自主功能 (世界模型技术 — 复杂场景+自主恢复)

| ID | 功能 | 实际载体 | 状态 |
|---|---|---|---|
| L4-C01 | 状态估计 | AdaptiveStateEstimator (卡尔曼) | ✅ |
| L4-C02 | 先验预测 | PriorDynamicsPredictor / WorldModelPredictor (右脑) | ✅ |
| L4-C03 | 接触流形 | manifold.ContactManifold (e∥进度/e⊥偏离) | ✅ |
| L4-C04 | 性能流形 | manifold.PerformanceManifold (V_p/η 耦合代价) | ✅ |
| L4-C05 | 潜空-流形标定 | latent 标定 + 现场几何采样 (布局漂移修正) | ✅ |
| L4-C06 | 校正恢复 | 状态校正器 (残差/接触概率 → 纠偏) | ✅ |
| L4-C07 | 肌肉记忆 | muscle_memory.py (观察→固化→快通道, 越练越顺) | ✅ 实测 |
| L4-C08 | 真实化运行 | R1 vision 真 YOLO + full 链自主恢复 | ✅ |

**L4 本质**: 世界模型预判 + 流形导航 + 自主恢复失败 (城区 NOA 类比)

## 🔗 三级关系 (实际数据流)

```
L2 (分段): YOLO→融合→MLP/解析→状态机→原子技能→执行     [单独能跑, 每段可靠]
        ↑ 增强
L3 (端到端): VLM编码(z960) → DiT ActionHead → 动作直通     [整任务自主]
        ↑ 预判
L4 (专家): 右脑WM预判 + 接触/性能流形导航 + 肌肉记忆快通道  [自主恢复+越练越顺]
```

## ✅ 自动测试现状 (三级可跑断言)
```bash
gui-venv311/bin/python tools/ss_level_tests.py        # L2 186 + L3 76 + L4 103 = 365 断言
gui-venv311/bin/python tools/ss_level_tests.py --level L3
```

## 📌 升级焦点 (实际缺口)
1. **L3-B05 收敛**: smolvla_lew_v8 续训 10000 步中 (已完成 3000 → 收敛目标), 完成后 rollout 验证真插拔
2. **L4-C08 自主恢复**: full 链多布局成功率提升 (难布局仍卡仿真无倒角物理)
3. **三级切换**: 引擎按场景选 L2/L3/L4 (画布可配置, 可分可合)
