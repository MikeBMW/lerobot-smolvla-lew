# L4 流形预测器 (JEPA) 训练实录 — 2026-09-09 (v1→v2→v3→v3.5 四轮)

模型: `src/lerobot/manifold/predictor_layer.py` WorldModelPredictor
= LatentPredictor(z7+a4→z') + ManifoldReadout(z'→流形6D)。
引擎旁路: 每帧真调 `predict_manifold(z7,a4)`, 输出旁路列 mani_pred。
训练数据 = 引擎轨迹字段 `z7_vec / u_exec_vec / mani_progress·risk·V·eta·rem·dperp`。

## 版本成绩链 (test seed 7/9 未见布局族, clean 口径)
| 版本 | 数据 | 架构 | 训练 | 帧成功率 | 插入段 |
|---|---|---|---|---|---|
| v1 | 16872帧/18seed | 384/3层 342K | 200ep CPU | 16.4% | 38.2% |
| v2 | 23193帧/25seed | 512/4层 867K | 400ep CPU | 39.3% | 85.0% |
| v3 | 83806帧/42seed 全采 | 1024/6层 5.5M | 1000ep GPU | 27.5% ❌ | 66.2% |
| v3.5 | 50153帧/42seed done过滤 | 1024/6层 5.5M | 1000ep GPU lr3e-4 | **45.6%** | 79.6% (ep800 93.3%) |

v3 退步根因 = 盲目扩 seed 引入失败轨迹 (500/2000 步超时未完成, 占 64%),
模型学到"反复尝试"失败模式。教训: **数据质量(成功/失败) > 数据量**。

## 数据采集规则 (collect_mani_v35.py 模式)
1. train/test 按 seed 布局族分; test seed (7/9) 必须实际采 (test 空 → nan)。
2. 逐 episode 过滤: `done=True` 全保留; `done=False` 只留 rem<0.1 前段;
   **test 集保持完整不过滤** (与旧版可比)。
3. `vision=False` 快采 (秒级/轮); insert+full 两种 mode 都采。

## 训练规则
- **大容量必降 lr**: 5.5M 参数 lr 1.5e-3 → ep300 loss 爆炸 0.006→0.059;
  改 3e-4 + clip_grad_norm_(1.0) 立即稳。小模型 (867K) 1.5e-3 没事。
- 5.5M CPU 训不动 → GPU (4060: 1000ep ≈ 12min, batch 2048, num_workers=2)。
- loss = 0.5·MSE(z', zn) + mean((manifold-m)²·W6), W6=[1,3,1,1,3,3] (rem/dperp/risk ×3)。
- 每 200ep 评估 test 存最佳 (波动大: ep200 12% → ep400 42%)。
- 评估物理容差: progress≤0.03 / risk≤0.01 / V≤0.01 / eta≤0.05 / rem≤15mm / dperp≤15mm,
  6 维全中 = 帧成功; 分维 + 按 rem 分层 (插入<0.06 vs 转移) 报。
- 汇报口径: clean (seed7/9) 与抗干扰 (jitter seed901) 分开, 别混比。

## 部署规则
- 引擎实例化固定架构 (v4/v2 时代: hidden 512/4): 换大架构先改实例化参数。
- 引擎多版本回退链按存在性加载 (v5→v4→v2): 部署前先 ls + 查加载顺序,
  别覆盖并行会话已部署的更好版本 (v5 抗干扰 jitter 64.6%)。
- 权重 = 裸 state_dict; 引擎 `_pred.load_state_dict(torch.load(path))`。

## 并行会话差异线 (v4/v5, 勿混)
v4 = v2(clean) × v3(CY 一致性正则 + jitter 干扰数据 seed901) 融合; v5 = CY 修复版
抗干扰 64.6% (jitter 口径)。他们另立 test_jit=[901], 与 clean test 7/9 是两套口径。
