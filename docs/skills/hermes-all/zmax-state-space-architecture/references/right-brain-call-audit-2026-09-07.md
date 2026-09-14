# 右脑模型调用审计 (2026-09-07) — est→predict→"模型在哪里调用" 追问链实锤

老倪连环追问: ①贴 AdaptiveStateEstimator 问"怎么没加载模型" → ②贴 predict() 问
"在哪里调用了" → ③打断"我是说模型在哪里调用?"。逐层落点 = **训练好的右脑权重在引擎
闭环里到底执行没有、输出有没有影响任何决策**。回答要点: 直接给调用点行号 + 分支计数
+ "输出是否改变决策"的实测, 不要先铺架构叙事 (老倪两次打断 = 嫌长/嫌绕)。

## 代码调用点 (2026-09-07 实核)

| 组件 | 加载处 | 推理调用处 | 引擎调用行 |
|---|---|---|---|
| est 教学卡尔曼 | 无权重 (A=1.0/K=0.2/B=dt 标定) | predict/update 主循环 | sim:315/336 |
| 左脑 MLP | parallel.py:134 mlp_ff_forward(npz) | accel.forward / load_trained_left_brain | sim 数据采集+快演 |
| 右脑 WM | dynamics.py rb_ff_forward → PriorDynamicsPredictor.wm (use_wm=True) | predict() use_wm 分支 (需调用方传 obs); contact_of() | sim:319 predict(不传obs)/332 contact_of; sim_real:426/435 |

- est 实例化: state_space_sim.py:158 `AdaptiveStateEstimator(A=1.0, K=0.2, B=dt)`;
  dyn 实例化: :160 `PriorDynamicsPredictor(A=1.0, B=dt)`。
- est.predict 用 act4 = 上一步真实下发 u_exec (非 u_ff 建议, 模长差 3.12 倍 bug 已修,
  离线重放误差 3.60→3.01mm)。
- dyn.predict 消费链: prior → cognition.state_correction(prior, z_k, K=0.5) →
  residual (力维改 force_norm) → r_scalar → contact_probability(gain=8.0) → contact_p;
  残差进 res_ema(α=0.15) → u_fb。

## 实测定量 (324 步全程 hook, 计数装在 run() 之前)

```
右脑权重 loaded=True, wm OK
predict:   324 次调用 → wm 分支 0 次 (n_wm=0) → 全走线性 A·x+B·u (引擎不传 obs, 设计如此)
contact_of: 324 次调用 → 域内返回 324 次 → 输出 contact 恒 0.0 (max=0.0, 无一次 >0.5)
```

结论:
1. predict 的右脑分支 = 保留能力, 引擎闭环从不触发 (位置先验走线性是 09-06 数据否决,
   docstring 已写明)。
2. contact_of 每步真执行右脑推理, 但**输出恒 0.0** → contact_p = max(经验残差公式, 0.0)
   = 经验公式单干 → **右脑在引擎闭环实际零影响**。
3. "重训 acc 1.000 (近1.00/远0.00)" 是验证集事实; 引擎现场抓取段手已到 peg (<5cm 标签
   阈值) 却从不报接触 → 输入 obs 语义/通道对齐/标签定义在引擎现场对不上, 疑似真 bug,
   根因未查 (下次会话接续: 对比引擎 _build_obs 通道 vs 训练数据通道; 打印模型对现场
   obs 的原始 logit/输出分布, 别只看阈值后结果)。
4. sim_real (state_space_sim_real.py:113) use_wm=True + 多布局重训 npz — 但 predict
   调用同样不传 obs (:426), 右脑位置先验同样不生效; contact_of :435 传 obs。

## 探测铁律 (本次踩的测试坑)

- **monkeypatch 计数 hook 必须在 sim.run() 之前装好**。同一 StateSpaceSim 实例第二次
  run() 会短路 — 引擎已 done, 主循环只象征执行 ~1 步, 计数全失真:
  实测第二次 run 后 n_linear 324→325 (只+1), contact_of calls=1 (非 324)。
- 引擎完成判定/重入逻辑: run() 检测已完成 → 几乎直接返回历史轨迹。
- 因此"全程 N 步统计"只能来自 hook 后的第一次 run, 别复用实例跑两遍对比。

## 回答模板 (老倪问"X 模型在哪/有没有用"时)

1. 一句话: 加载点文件:行号 → 推理调用点文件:行号 → 每步/每阶段触发 → 输出如何被消费。
2. 分支计数实测 (hook 一次 run): n_wm vs n_linear, 域内/域外返回次数, 输出 max/非零比例。
3. 诚实落点: 如果输出恒 0 / 从不触发 / 被 max 兜底盖过 → 明说"实际零影响", 别把
   "已接入"说成"已生效"; 给出下一步查证方向 (通道语义对比/原始输出分布)。
