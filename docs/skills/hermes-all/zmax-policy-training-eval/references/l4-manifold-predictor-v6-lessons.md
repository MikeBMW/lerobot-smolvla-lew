# L4 流形预测器 v6 教训与部署结论 (2026-09-09 补遗 — v3.5 之后的三轮)

主表 (v1→v3.5 成绩链 + 采集/训练/部署规则) 见同目录 l4-manifold-predictor-training.md。
本文件只记 v3.5 之后的新结论, 避免大文件反复编辑。

## v6 = v3.5 + CY 在线噪声 → 失败 (别重复)
- 做法: 训练循环里对 z 前 6 维加 ~1cm 高斯噪声构 z_b (`zbc = z.clone(); zbc[:,:6] +=
  torch.randn_like(...)*0.01`), 加 cy_consistency_loss(z, a, out_manifold, z_b, out_b_manifold),
  lam=0.5, 想同时提 clean + 抗干扰。
- 结果: ep300 后 loss 波动, **ep800+ 发散 (0.005→0.010), clean 45%→8.3%**;
  最佳 ep400 = 34.2% (插入段 63.1%), **不如纯 v3.5 45.6%**。
- 根因: CY 等距约束 (dm ≤ lip·dz + slack) 与回归目标打架, 低 lr 后段 (cosine 尾部) 震荡
  不稳定; 在线噪声 batch 内每 epoch 随机 → 无固定干扰分布可学。
- **抗干扰的正确路线 = 并行会话的离线 jitter 实测数据** (seed901 布局, 固定分布) +
  CY 只约束模型输出且梯度流经 oa/ob (输入 detach 则 CY 恒 0 = 摆设, 消融实锤)。

## 部署结论: 保持并行会话 v5, 不换 v3.5
- 引擎加载链 `l4_mani_predictor_v5.pt → v4 → v2` (按存在性 break), 实例化架构固定
  hidden 512/4 — **v3.5 权重 1024/6 (21MB) 架构不匹配, 直接换路径会 load_state_dict 崩**。
- v3.5 clean 45.6% ≈ v4/v5 clean 45.7% (引擎注释实锤) → 大架构无 clean 增益;
  v5 还带抗干扰 64.6% (jitter 口径) → **双口径都赢, 保持 v5**。
- 教训: 训练新版本前先 `ls models/l4_mani_predictor_*.pt` + grep 引擎注释 +
  git log — 并行会话可能已部署更强版本, 别重复造轮子 (本次 v3.5 45.6% vs v5 45.7%
  白跑一轮才发现)。

## 训练"卡住"诊断 (py-spy, 别急着杀)
- 症状: 大模型 CPU 训练长时间无新 ep 输出 + CPU 高。可能只是 ep 打点稀疏 (每 50-100 ep),
  不是死锁。判别: `sudo env PATH=$PATH py-spy dump --pid <pid>` — 主线程栈在
  `torch/nn/modules/linear.py forward` = 正常前向, 等即可。
- 5.5M 参数 × 8 万帧 CPU 1000ep ≈ 17h+ → **直接 GPU** (4060 1000ep ≈ 12min,
  batch 2048 + num_workers=2)。小 MLP batch CPU 多线程用不满 (torch intra 24 线程
  但实际 2 线程在算 — 正常, 别当故障)。
- CPU 训练期间 stdout 进 pipe 用 process poll 看, 别 cat /proc/pid/fd/1 (会卡)。
