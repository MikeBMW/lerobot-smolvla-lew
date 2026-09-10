# LEW/Mamba 世界模型消融 + 引擎闭环失败诊断 (2026-09-10)

> 姊妹文件: lew-mamba-world-model.md (Mamba 自实现/消融细节)。本文件 = 闭环接入的
> 失败诊断与状态机根因修正 (最后一次深挖结论, 覆盖前文件的"两类都是对心问题"旧结论)。

## LEW (LeWorldModel) 结构与独立加载
- world_model_le.py: vision_encoder(SigLIP) + action_encoder + **ARPredictor**(核心, AdaLN-zero
  条件 Transformer) + projector。ARPredictor = pos_embedding(1, num_frames=2, 192) + 6 层
  ConditionalBlock(AdaLN 调制 + Attention + MLP), 192 维 — **纯序列模型不依赖 VLM**。
- v8 checkpoint 权重键 `model.le_world_model.predictor.*` → 去前缀直接 load_state_dict
  (0 missing; ARPredictor 参数 num_frames=2/depth=6/heads=8/mlp_dim=768/input/hidden 192/dim_head=64)。
- **c (动作条件) 必须与 x 同维 192**: forward(x, c) 里 c 经 action_encoder 投影, 直接喂 (B,T,4)
  报 `mat1 (2x4) and mat2 (192x1152)`。几何序列接法: z7 → Linear(7→192) proj → ar(xe, xe) 自条件。

## Mamba SSM 自实现 (src/lerobot/policies/smolvla_lew/mamba_ssm.py)
- SelectiveSSM: 每通道对角标量 SSM h'=exp(Ā)h+B̄u 逐帧因果扫描, B/C/Δ 输入依赖 (选择性),
  d_state=16, 14.2万参数/层。HybridTransformerBlock = AdaLN 注意 + SSM + MLP。
- ARPredictor/Transformer 加 `mamba_mode` (None|interleave|hybrid|full); interleave=奇数层 SSM。
- ⚠️ mamba_ssm.py 用**绝对导入** (`from lerobot.policies.smolvla_lew.world_model_le import ...`),
  相对导入单独 exec 报错。

## 消融结果 (同数据同口径, v8 权重初始化)
- 数据: 引擎轨迹 z7 序列窗口 T=2 → 预测 +1 帧; loss = embedding MSE + 5×decode(192→7) MSE。
- 纯 LEW 547万参数 zRMSE 0.0219 vs LEW+Mamba 590万 0.0210 (embedding 空间 0.0012 vs 0.0011)。
  **Mamba 混合两轮都小幅胜 4-10%, 无大突破。**
- ⚠️ 大模型 CPU 慢到分钟级/epoch — 必须 GPU (500ep ~6 分钟)。lr 3e-4 + 梯度裁剪
  (1.5e-3 在 550 万参数上发散: loss 0.006→0.059 卡死)。

## 引擎闭环接入失败诊断 (诚实结论)
目标: 插入遇阻 (卡"插入·接触" 200+ 帧) 时 LEW 预测 z7' 反解横向位移做 8 帧对心微调
(SS_LEW=transformer|mamba 开关, 遇阻 1-2 次先 LEW 修正, 3 次才回退 — 不破坏无开关路径)。

- **单次 seed1 345 步 done=True 是布局漂移运气** — 复测 3 次全 500 失败。metaworld 每进程布局
  漂移 ±3.8cm, **单次成功必须 ≥3 复测**。
- 根因: LEW z7 预测精度 ~2cm (zRMSE 0.021) vs 插入对心需 mm 级 (孔沿容差 1-2mm)。预测 embedding
  (0.001 级) 好但 decode 回 z7 丢精度 (0.02 级)。方向对但幅度不够, 猜中 ~50%。
- 换方向 (z7[3:6] hx-peg 预测反号补偿) 更差 — 描述性预测 ≠ 控制指令。
- **残酷结论**: LEW 适合低精度预判 (阶段切换/何时减速), 不适合毫米级插孔闭环。

## 变量作用域坑 (调试 40 分钟)
遇阻块内 `_lew_ok = False` (局部) 后 `if not self._lew_ok:` (实例属性) →
`AttributeError: ... no attribute '_lew_ok'`, 且只在 SS_LEW 未启用路径触发 (启用路径 try 内
`self._lew_ok = True` 掩盖问题)。**先确认局部 vs self 属性; inspect.getsource + hasattr 插桩最快。**

## seed1 失败根因修正 (不是 xy 对心 — 覆盖前文件旧结论)
- 成功 seed6 vs 失败 seed1 插入段起始对心几乎相同 (hx-peg xy ≈ -0.131, -0.002), z 高度也一致
  (peg_z-hand_z 恒 -0.031) — **不是 xy/z 对心**。
- 真差异 = **转移段没把 peg 头送到孔口正上方就切插入**:
  seed6 hole_mouth (-0.156, 0.641) vs seed1 hole_mouth (-0.242, 0.508) — **布局漂移巨大 (y 差 0.13)!
  对比 seed 必须先打印双方 sim.geom["hole"]/["goal"]**。
  seed1 切插入时 peg_head (-0.219, 0.512) vs hole_mouth (-0.242, 0.508): 离孔口还 2.3cm,
  状态机已判对准 (dh<align_th 0.025) → 推 2.3cm 空档撞孔沿 → 卡 205 帧。
- **align_th 收紧 (0.025→0.012) 反而全失败** — 转移伺服部分布局推不到 1.2cm, 切插入条件永不满足
  → 卡转移 500 步。阈值不是根因, **转移段伺服不收敛才是**。
- 失败时插入段 z7[0] (轴向) 变化 -0.022 = peg 在退不是进。
- 诊断三步: ①双方 geom 孔位对比 (布局漂移) ②插入段起始 peg_head vs hole_mouth 差 (没到孔口就切
  = 转移不收敛) ③插入段 z7[0] 轴向符号 (负=在退)。
- ⚠️ **sim.sched 在 _reset() 里构造不在 __init__** — 访问前须 `sim._reset(seed)`, 直接
  sim.sched 报 AttributeError 别怀疑构造逻辑。

## 引擎插拔基线 (重要背景)
解析伺服链 (analytic_forward) 28 seed 广撒 insert 模式成功率**仅 32.1% (9/28)** — 别假设引擎
默认能完成, 之前只在 3-4 个成功 seed 上验证过。失败两类: 卡"下降"(对心偏反复下压) /
卡"插入·接触"(peg 顶孔沿回退重试循环)。

## 关键文件
- src/lerobot/policies/smolvla_lew/world_model_le.py (+ mamba_mode)
- src/lerobot/policies/smolvla_lew/mamba_ssm.py
- tools/gui/ss_lew_plugin.py (predict_next_z), tools/gui/state_space_sim_real.py (遇阻注入)
- models/lew_{transformer,mamba_interleave}.pt
