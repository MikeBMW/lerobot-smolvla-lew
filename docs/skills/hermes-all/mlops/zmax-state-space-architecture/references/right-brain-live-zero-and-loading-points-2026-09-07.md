# 右脑模型"现场恒 0"与加载点问答 (2026-09-07)

老倪连环追问链: est 为什么没加载模型 → predict 在哪调用 → ff_forward 模型长什么样 →
为什么结果没插拔成功。标准答复 = 代码行号级调用点 + 实测计数器, 架构说明随后。

## 模型加载点分布 (谁加载训练好的模型)
- est `AdaptiveStateEstimator` (parallel.py:186) = **教学卡尔曼**, A/K/B 标定常数无权重
  (引擎实例化 A=1.0/K=0.2/B=dt, state_space_sim.py:158; predict 315 行 / update 336 行真调用)。
- 右脑 WM = `dynamics.py` PriorDynamicsPredictor:
  - NPZ_DEFAULT = models/ss_right_brain.npz (L20), rb_ff_forward (L24) 装载 (L79)
  - predict() (L98): 调用方**不传 obs → _in_domain(None)=False → 全走线性** A·x+B·u —
    这是"数据否决"的刻意设计 (引擎纯积分动力学线性先验即最优, 右脑 1cm 残差加噪
    0.108 vs 0.0485), 不是漏接。n_wm/n_linear 计数器现场可验。
  - contact_of() (L117): 传 obs, 才是右脑 WM 常驻推理入口 (引擎 state_space_sim.py:332 每步调)。
- 左脑 = parallel.py:134 mlp_ff_forward(npz) + 引擎 load_trained_left_brain (state_space_sim.py:721)。

## 现场"恒 0"实锤 (为什么 acc 1.00 白搭)
- 实测 324 步全程: predict 324 次调用 → wm 分支 0 次 (n_wm=0/n_linear=324);
  contact_of 324 次 → 域内返回 324 次 → 输出全 0.0 (logit −282~−42)。
- 235/324 帧满足训练接触标签条件 (手-peg <5cm), 模型对最近帧 (1.3cm) 也只给 logit −88。
- **根因判定**: 模型没坏, 是输入与训练分布"通道间语义错位" — 逐通道 4σ 域检查只查单通道
  值域, 查不出通道间错位 (每通道在域内, 组合是乱码 → logit 极端负)。
- 教训: 域检通过 ≠ 模型认识输入; 验证模型作用必须看**现场 logit/输出分布**, 不信验证集 acc。

## 答复格式教训 (老倪两次打断)
- "我是说模型在哪里调用?" → 直接给: wm 推理只在 dynamics.py predict(use_wm 分支)与
  contact_of 两处; predict 不传 obs 从不触发, contact_of 每步触发但输出恒 0。附实测计数。
- "为什么结果, 没有插拔成功呢?" → 先查 3D/视频数据源是本次运行轨迹还是旧产物, 再给
  失败阶段证据; 不要先讲架构分层。
