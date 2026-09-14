# LEW Transformer 世界模型 + Mamba SSM + 引擎闭环 — 2026-09-09/10 实测

## 背景
L4 两条世界模型线: ①引擎旁路流形预测器 (predictor_layer.py, MLP, v5 部署, clean 45.7%+抗干扰 64.6% —
见 l4-manifold-predictor-training.md) ②**LEW = smolvla_lew 的 LeWorldModel** (world_model_le.py,
AdaLN-zero 条件 Transformer)。本文件 = LEW 独立加载 + Mamba 混合消融 + LEW 接引擎闭环的实测结论。

## LEW 结构与权重 (v8 checkpoint)
- `LeWorldModel`: vision_encoder(SigLIP 197 块) + action_encoder + **ARPredictor**(核心) + projector。
- ARPredictor = 纯时序 Transformer: pos_embedding (1, num_frames=2, 192) + Transformer 192 维 × 6 层
  (ConditionalBlock: AdaLN-zero 调制 + Attention + MLP)。
- **predictor 是纯序列模型, 不依赖 VLM** — 引擎闭环可喂几何序列投影, 不必每帧跑 SigLIP (0.6s/帧太慢)。
- v8 权重键前缀: `model.le_world_model.predictor.*` → 去掉前缀直接 `ARPredictor(...).load_state_dict`
  (0 missing 0 unexpected, num_frames=2/depth=6/heads=8/mlp_dim=768/input_dim=192/hidden_dim=192/dim_head=64)。
- 加载注意: ARPredictor `forward(x, c)` 里 c (动作条件) **必须与 x 同维 192** (经 action_encoder 投影),
  直接喂 (B,T,4) 动作报 `mat1 (2x4) and mat2 (192x1152)`。

## Mamba SSM 增强 (自实现, 零外部依赖) — src/lerobot/policies/smolvla_lew/mamba_ssm.py
- **SelectiveSSM** (d_model, d_state=16): 每通道一个标量对角 SSM, h' = exp(Ā)h + B̄u 逐帧因果扫描;
  选择性 = B/C/Δ 由输入 x 线性投影产生 (Mamba 关键, 非时不变)。参数 141,696/层 (192 维)。
- **HybridTransformerBlock**: AdaLN 注意 + SSM 增强 (无额外条件) + MLP — 插进 Transformer 层做混合。
- **world_model_le.ARPredictor/Transformer 加 `mamba_mode` 参数** (None|interleave|hybrid|full):
  构造函数里 `use_mamba` 按模式选 HybridTransformerBlock 否则 ConditionalBlock —
  interleave = 奇数层 SSM (3/6 层混), 消融开关在模型层, 训练脚本只传参。
- ⚠️ import 注意: mamba_ssm.py 内用**绝对导入** `from lerobot.policies.smolvla_lew.world_model_le
  import Attention, FeedForward, modulate` (相对导入 .world_model_le 单独 exec 时报错)。

## 消融方法 (同数据/同口径才可比)
- 数据: 引擎轨迹 z7 序列 (T=2 窗口 → 预测 +1 帧), 几何 z7 → Linear(7→192) proj → ARPredictor
  (c=xe 自条件, 无动作) → 预测末帧 embedding; 损失 = embedding MSE + 5×decode(192→7) MSE。
- 变体同权重初始化 (v8 predictor 权重载入, mamba 层随机) 同 400-500ep 同 lr。
- **结果 (z7 decode 空间)**: 纯 LEW 547 万参数 val zRMSE 0.0219; LEW+Mamba 590 万 0.0210 (Mamba 略胜)。
  embedding 空间消融同向 (0.0012 vs 0.0011)。**Mamba 混合两轮都小幅胜 (4-10%), 无大突破**。
- ⚠️ 大模型 (550 万) CPU 训练慢到 17 分钟/epoch 级 — 必须 GPU (4060 上 500ep ~6 分钟)。lr 用 3e-4 +
  梯度裁剪 (1.5e-3 在 550 万参数上发散: loss 0.006→0.059 后卡死, ep300 突变)。

## LEW 接引擎闭环 (遇阻前视修正) — 实测结论
目标: 插入遇阻 (peg 顶孔沿, 卡"插入·接触" 200+ 帧失败) 时用 LEW 预测下一帧 z7' → 反解横向位移 →
8 帧微调窗口对心修正 (SS_LEW=transformer|mamba 环境变量开关, 引擎遇阻块 `_stall>=5` 时, 第 1-2 次
先试 LEW, 3 次才回退 — 不破坏无 SS_LEW 时的原路径)。

**❌ 实测不稳定 (诚实结论)**: seed1 (原卡死 500 步失败) 首次 LEW+Mamba 跑出 345 步 done=True, 但
**复测 3 次全 500 步失败** — 首次成功是 metaworld 布局每进程漂移 (±3.8cm 已知) 的运气, 不是 LEW 修正生效。
- **单次成功必须 ≥3 次复测**, 单次结果在布局漂移噪声内不可信 (metaworld 每进程布局漂移是老坑)。
- 根因: LEW 预测 z7 精度 ~2cm (zRMSE 0.021) vs 插入对心需 mm 级 (孔沿容差 1-2mm) — 预测方向对但
  幅度/精度不够, 猜中方向概率 ~50%。
- **换方向修正 (用 z7[3:6]=hx-peg 预测反号补偿) 反而更差** — 描述性预测 (下一帧会怎样) ≠ 控制指令
  (该往哪走); 预测 embedding (0.001 级) 好但 decode 回 z7 丢精度 (0.02 级)。
- **残酷结论**: LEW 世界模型当前精度不足以直接驱动毫米级插孔修正; 适合"阶段切换预判/何时减速"等
  低精度需求, 不适合直接闭环插孔。

## Python 变量作用域坑 (调试 40 分钟实锤)
遇阻块内先写 `_lew_ok = False` (局部变量) 再 `if not self._lew_ok:` (实例属性) →
`AttributeError: 'RealStateSpaceSim' object has no attribute '_lew_ok'`, 且只在不启用 SS_LEW 时触发
(启用路径里 try 内 `self._lew_ok = True` 掩盖了问题)。**排查: 先确认变量是局部还是 self 属性,
缩进相同 ≠ 同一变量**。inspect.getsource + hasattr 插桩比读代码快。

## 引擎插拔基线 (2026-09-09 实测, 重要背景)
- 解析伺服链 (analytic_forward) 28 seed 广撒 insert 模式成功率 **仅 32.1% (9/28)** — 别假设"引擎默认能
  完成", 之前只在 3-4 个成功 seed 上验证过。
- 失败两类: ①卡"下降" (seed 3/4/100, 186-265 帧): 夹爪下降对心偏反复下压;
  ②卡"插入·接触" (seed 1/8, 148-205 帧): peg 顶孔沿插不进 → 回退重试循环 (遇阻 5 帧确认 → 12 帧回撤
  → 回转移/接近重试, 3 次后回接近重抓 — 回退不对心修正, 反复顶同一位置)。
- 两类都是"对心/对准"问题 — L4 流形 risk/dperp 恰是观测, 但预测精度不足时修正无益 (见上)。

## 关键文件
- src/lerobot/policies/smolvla_lew/world_model_le.py (LEW + mamba_mode)
- src/lerobot/policies/smolvla_lew/mamba_ssm.py (SelectiveSSM/HybridTransformerBlock 自实现)
- tools/gui/ss_lew_plugin.py (LEW 加载插件 predict_next_z)
- tools/gui/state_space_sim_real.py (遇阻块 SS_LEW 注入, _z7_hist 维护)
- models/lew_{transformer,mamba_interleave}.pt (消融产物)
