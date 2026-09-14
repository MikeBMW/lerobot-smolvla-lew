# 神经同构模块行 (2026-08-16) — 脑科学映射落地

## 背景 (老倪贴的理论分析)

左脑MLP ≈ **小脑**: 前馈控制 + 感觉-运动映射, obs→action 直接映射,
无递归无延迟 = 学习过的逆动力学模型 (熟练工直觉, 毫秒级无意识纠偏)。

右脑GRU ≈ **非线性卡尔曼滤波器** (世界模型):
- 预测 Predict: 状态转移 A ≈ GRU 循环权重 W_hh + 控制输入 B ≈ action
- 更新 Update: 卡尔曼增益 K ≈ GRU 更新门/重置门 (自动调节信预测 vs 信观测)
- 先验注入: ctx_proj (VLM 语义) 初始化 h₀ ≈ 带先验的卡尔曼迭代

状态机 ≈ **皮层 (前额叶)**: 卡尔曼只估计状态, 不决定该做什么;
皮层用 contact 概率 + 几何误差 → 阶段切换决策。

系统 = 物理约束(小脑) + 学习的非线性卡尔曼(世界模型) + 认知规划器(状态机) — 不是黑箱。
纯前馈无更新 = 尺寸偏差时按记忆力度硬插 → 接触力>20N 损伤金手指。

## 画布落地 (flows/ff_pd_top.json, 幂等生成器 tools/gui/gen_ff_pd_neural.py)

新增「🧠 神经同构 (脑↔控制)」行 y=290 (node y=330), 3 节点 + 1 row_bg:

| id | 节点 | type | x | 关键 params |
|---|---|---|---|---|
| ffkal | 🔮 右脑 · 非线性卡尔曼 | model | 150 | neural_kalman, A=0.95, K=0.5 |
| ffcer | 🧠 左脑 · 小脑 (前馈) | model | 400 | neural_cerebellum, K_ff=0.2 |
| ffctx | 🧭 皮层 · 状态机 | system | 680 | neural_cortex, contact_th=0.6, Kp=2.0, thresh=0.06 |

全部带 z700_internal=True (paint 显示参数 + 双击走 _show_internal_detail)。
row_bg ffnbg: 「🧠 神经同构 (脑↔控制)」w=1060, bg #1a1030。

连线 (6条): 感知链ffy1→ffkal.in1(观测) / 双脑ffb1→ffkal.in2(动作) /
感知链ffy1→ffcer.in1(状态) / ffkal.out2(contact)→ffctx.in1 /
状态机ffsm→ffctx.in2(几何误差) / ffctx.out1→ffact.in2(决策叠加, ffact inputs 扩 in2)。

## 代码三件套

1. node_logic.py: `node_neural_kalman` / `node_neural_cerebellum` / `node_neural_cortex`
   (docstring 写卡尔曼组件对照表 + 小脑前馈语义 + 皮层决策语义)
2. `_reg("neural_kalman", ["右脑 · 非线性卡尔曼", "非线性卡尔曼"], ...)` 等 3 个
   (关键词用全名/中段, 避免误匹配)
3. simulink_module.py `_show_internal_detail`: 三个 `elif p.get("neural_xxx")` 分支
   在双脑分支后、else 感知链前 — 每个渲染 HTML 表格 (卡尔曼 8 行组件对照 / 小脑 6 行
   神经vs工程对照 / 皮层 4 行输入表)。

## 模块库 (LIBRARY Z700 工程组末尾)

三条目与画布 params 一致 (neural_xxx + z700_internal + 标定默认值) —
画布节点 → 左侧库按钮全覆盖 (验证: 画布名集合 ⊆ 库名集合)。

## 验证要点

- 加载 ff_pd_top → 16 节点 16 连线, 无悬空, 类型合法
- 双击 3 神经节点 → _show_internal_detail 调用 3 次 (mock patch)
- node_logic.match_node 命中 3 新节点; 未命中的 🔬Z700子系统/感知链/双脑/状态机/动作
  是既有设计 (z700_internal 走 params 分支交互, execute_node_logic 返回 None 框架兜底)
- 单步执行 20 步无异常 (神经节点参与拓扑, 无环)
- 画布→库覆盖: 差集为空 (注意硬编码字符串与文件字符细微差异会导致假 False,
  用画布 JSON 实际名做差集验证)

## 坑

- 三节点名含「右脑/左脑/皮层」但现有 z700_internal 分支按名字匹配 (状态机/动作/双脑/感知链) —
  神经节点靠 params 标记 (neural_kalman 等) 分支, 不是名字; 名字分支 else 会掉进感知链兜底
- paint 的 role 映射 dict (感知链/双脑/状态机/动作) 不覆盖神经节点 → role="" 无类型标签, 正常
- 三节点 w=190 (与内部行一致), 别用默认 150 会被背景行盖住
