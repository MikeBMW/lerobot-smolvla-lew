# L4 架构三档事实 + mani_pred None 排查 (2026-09-09 代码级核实)

## 架构三档事实 (老倪常问"有 transformer/mamba 么")
1. **引擎部署的 L4 预测器 = 纯 MLP** (WorldModelPredictor: LatentPredictor MLP +
   ManifoldReadout MLP, 无 Attention/无 Transformer/无 Mamba) — 这是 v5 45.7%/64.6%
   成绩的载体。
2. **LeWorldModel (src/lerobot/policies/smolvla_lew/world_model_le.py) = 真
   AdaLN-zero Transformer** (Attention+FeedForward+ConditionalBlock+CrossAttention;
   ARPredictor)。v8 训练已启用: `enable_lew_world_model: true, lew_loss_weight: 0.1,
   lew_hidden_dim: 192, lew_num_layers: 6` — 它工作在 VLM z960 空间, 与引擎旁路
   预测器 (z7 几何) 是两条线, 别混为一谈。
3. **Mamba/SSM (selective scan) 全仓零实现** — grep 'mamba|Mamba|S6|selective_scan'
   src/ tools/ 无命中 (唯一 false positive 是 feetech 注释里的 issue 号)。
   要上 Mamba 需引 mamba-ssm 依赖 + 新架构。

## mani_pred 全 None 排查 (predictor 注入失败静默)
- 症状: `tr["z7_vec"]` 每帧都有 (记录无条件) 但 `mani_pred` 全 None → predictor
  注入失败被异常吞 (__init__ 里 `self._mani_cm` 是 None 直到 run() 内懒构造;
  构造块 try/except 吞错)。
- 判别: 跑后检查 `sim._mani_cm.predictor is not None` (或直接 `getattr(sim, "_mani_cm",
  None)` — run 前必是 None, run 内才懒建)。v5 权重路径存在 ≠ predictor 已注入,
  构造失败 (_PRED_MOD import/load_state_dict 异常) 会静默降级随机权重对照。
- 验证 predictor 真工作: seed104 insert 343 步 mani_pred 343/343 非 None 是健康基准。
- 用途: 若想用预测流形做遇阻对心修正 (L4 执行闭环), 先确认每帧 predictor 真调用,
  否则读到的预测列全 None → 修正逻辑空转。

## 关联
- v1→v3.5 成绩链/数据/训练/部署规则: l4-manifold-predictor-training.md
- v6 失败 + 保持 v5 结论 + py-spy: l4-manifold-predictor-v6-lessons.md
- 基线 32.1% + 失败模式 + decoder 病态: l34-joint-baseline-lessons.md
