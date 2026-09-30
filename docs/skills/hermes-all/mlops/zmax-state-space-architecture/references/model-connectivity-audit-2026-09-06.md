# 模型接入真伪审计总表 (2026-09-06, 引擎实测证据)

老倪高频追问 "所有模型(YOLO/左脑/右脑/流形)都连上了么? 整体上真实模型和数据么?"。
本表是逐模型查证结论 (权重文件存在性 + 代码调用点 + 主执行/降级状态), 直接引用可答。

## 总表

| 模型 | 真权重文件 | 接入点 | 状态 |
|---|---|---|---|
| 🎯 YOLO 2D | outputs(或runs/detect)/yolo_peg/peg_v1/weights/best.pt | state_space_sim_real.py:153 `_yolo_sense` → aligner.detect_3d | R1 真主执行 |
| 🎯 YOLO depth head | outputs/yolo_peg_depth/peg_depth_v1-2/weights/best.pt (v1 兜底) | yolo_state_aligner.py:53 depth_model → 反投影 z | R1 真主执行 (文件在=真深度, 不在才写死z回退) |
| 🧠 左脑 MLP | models/ss_left_brain.npz (547K, 4层Linear, 09-04) | parallel.py mlp_ff_forward; 引擎 308 行 accel.forward(obs) | 引擎=主执行 / **R0=强制解析降级** |
| 🧠 右脑 WM | models/ss_right_brain.npz (345KB, 09-06 重训) | dynamics.py rb_ff_forward → contact_of; 引擎 332-334 contact_p=max(公式, wm) | **contact 通道主执行** / 位置先验=实测否决 |
| 🌀 流形 | 无 (纯几何计算件, 非学习模型) | manifold_layer.py decompose/evaluate; 引擎 443-451 每步实算入 tr | 真实计算, **只读仪表不反哺控制** |

## 逐模型证据链 (查证法, 下次审计照做)

1. **找加载点**: grep -nE "YOLO\(|np.load|NPZ_DEFAULT|rb_ff_forward|load_npz" 对应文件
   → 权重文件 ls -la 实测存在 (别信注释, 信文件)。
2. **找调用点**: grep -nE "accel.forward|contact_of|detect_3d|decompose|evaluate" 引擎主循环
   → 确认每步真调, 且**没被替换**: 查 `accel.forward = accel.analytic_forward` 这类覆盖。
3. **判主执行/降级**: 看代码注释写的降级原因 + 计数器 (parallel.py loaded/n_mlp/n_guard,
   dynamics.py n_wm/n_linear) — 数字即真实执行占比证据。
4. **层判定四分类**: 主执行 (域内真跑) / 域外降级 (强制解析, 注释写明原因, 可恢复) /
   实测否决 (能力保留不主执行, 数据说话) / 只读仪表 (设计如此, 非隐藏故障)。

## 关键降级事实 (诚实分层, 引用时别夸大)

- **左脑 R0 强制解析**: state_space_sim_real.py:103 注释 — R0 布局每进程随机漂移 >10cm,
  单布局蒸馏 MLP 出训练域 (逐通道 4σ 域守卫只能救单通道域外, 救不了联合分布偏移);
  09-04 R0 基线 62% 本就是解析跑的。引擎快演单布局=训练域 → 仍 MLP 主执行。
  多布局重蒸馏后解除。**训练数据管道 (sim.accel.forward=analytic_forward, sim.py:684)
  教师固定=解析律** — MLP 不能当教师 (域外自举发散, 实测 hand 飞 9m)。
- **右脑**: contact_of 域内主执行融合 (acc 1.00 可靠); predict 位置先验引擎默认不传 obs
  走线性 (纯积分动力学线性即最优, wm 1cm 残差加噪 0.108 vs 0.0485); R0 use_wm=False
  (布局域外)。即: contact 通道真主执行, 位置通道能力保留待真实物理场景。
- **YOLO hand 恒编码器真值**: 定标实锤 YOLO 检测 hand 漂移 12-20cm 不可控 →
  真机同构机械臂末端=编码器, 视觉只定位工件 (光模块/hole)。这是架构决定非偷懒。
- **流形不反哺控制**: 引擎 443-451 每步真算发布 (progress/risk/η/V 入 tr 全程序列),
  但只读展示 — 监控仪表不是控制回路成员。回答时如实说明。

## 流形实测数值 (2026-09-06, 引擎 310 步, 修复后)

```
阶段        progress(末)  risk(max)   eta(max)
接近          0.0739       0.0000     0.0000   ← 离目标远
对位          0.0330       0.0000     0.0000
下降          0.0291       0.0191     0.0000   ← 垂直下刀真实横向偏离
插入          0.0000       0.0275     1.0000   ← 插到底, 对准成功!
完成          0.0000       0.0000     1.0000   ← η 保持 1.0
```
- progress 单调收敛 0.074→0 (通道走完); risk 下降/插入段真实出现; V 0.0027→0 能量归零。
- **η 0→1.0 对比旧记录 0.57→0.77**: 两段式插入修复 (5de91cec) 让 peg 真插到底 —
  流形数字直接佐证修复效果 (η=exp(−V_p/σ²), σ=0.004, 插到底 δ→0 才到 1.0)。
- 回答模板: "progress/risk/η/V 是引擎逐帧真实几何计算的只读展示, 非写死非装饰,
  数值随阶段有物理意义变化" — 附上表即铁证。
