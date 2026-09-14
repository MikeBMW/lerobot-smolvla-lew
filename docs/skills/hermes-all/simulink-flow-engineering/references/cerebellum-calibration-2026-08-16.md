# 左脑·小脑标定参数设计 (2026-08-16) — 工程标定 vs 生物标定缝合

## 思想 (老倪贴的理论)

**左脑标定 ≠ 调权重**: 左脑是固定 .pt (547K 权重), 工程师用三个「数据/执行」旋钮:
- ① 感知零偏标定: 静止记录 obs → 新 x_mean; 满行程 → x_std — 校准零点, 光模块换位只更新参考坐标 → 输出整体平移 (最快重标定)
- ② 执行力标定: `act[:3] = act*act_gain + clip(delta*err_gain)` — act_gain=肌肉记忆占比 (MLP 主导), err_gain=误差纠正力度 (重物体调小防过冲)
- ③ 现场微调: 采集 20-30 条示教 → 4090 微调 5min → 热加载 .pt (小脑急性手术)

**生物标定 (小脑配平误差)**:
- 平行纤维(上下文) = 左脑 MLP 输出
- 攀缘纤维(误差信号) = 右脑 contact + 实际力传感器对比 (力 5N vs 预测 0.5N = 复杂脉冲)
- 长时程抑制 LTD = 状态机 gate 系数 (1.0/0.1/0.01): 左脑不准 → 瞬间降 gate 压制 MLP 输出, 控制权移交传感器
- 恢复期 = 状态机切阶段 → gate 恢复 → 左脑继续主导

## 工具: tools/cerebellum_calib.py (gui-venv 跑)

- `calib_bias()` — ① 感知零偏: 标准位静止观测 → 新 x_mean, 输出平移量 (等效重标定不重训)
- `calib_exec()` — ② 执行力: (act_gain×err_gain) 网格扫描 → 过冲率/收敛步数 → 推荐参数
- `calib_gate()` — ③ gate(LTD) 仿真: 接触力误差尖峰 → gate 骤降 (误差超阈值 → gate_min)
- `plot_gate()` — 双联图: 上=误差信号, 下=gate 系数 (误差尖峰→骤降→恢复)
- main: 三件套 → reports/cerebellum_calib.json + cerebellum_gate.png
- 实测: 零偏 -0.0004→平移0.05 / 推荐 act_gain=0.8 err_gain=2.0 / 4.5N 误差→gate 压至 0.1 (62 步)

## 画布: 神经同构行 5→7 节点 (生成器 gen_ff_pd_neural.py)

| id | 节点 | x | params |
|---|---|---|---|
| ffkal | 🔮 右脑·非线性卡尔曼 | 150 | neural_kalman |
| ffkal2 | ⚖️ α 融合层 | 360 | neural_alpha (in1预测/in2观测/in3标定) |
| ffcer | 🧠 左脑·小脑 (前馈) | 570 | neural_cerebellum + **act_gain=0.3, err_gain=2.0, gate=1.0, x_mean=0.0, x_std=1.0** (in1状态/in2标定) |
| ffclim | 🧬 攀缘纤维·误差警戒 | 730 | neural_climbing, gate_th=2.0, gate_min=0.1 |
| ffltd | 🛡 gate·突触抑制 (LTD) | 890 | neural_ltd, gate=1.0, gate_off=0.1, gate_off2=0.01 |
| ffctx | 🧭 皮层·状态机 | 1050 | neural_cortex |
| ffcal | 🔧 左脑标定实验 | 1230 | neural_calib, n_static=500, fine_tune_steps=3000 |

连线 (14): 感知链→右脑/融合层in2/左脑in1 / 双脑→右脑in2 / 右脑→融合层in1 / 左脑→攀缘in1(平行纤维) / 感知链→攀缘in2(力传感器) / 攀缘→gate in1(误差) / 左脑→gate in2(被抑制输出) / gate→ffact in2 / 右脑contact→皮层in1 / 状态机→皮层in2 / 皮层→ffact in3 / 标定→左脑in2。
ffact inputs = [in1(状态机+ffana注入), in2(gate抑制), in3(皮层决策)] — 3 条业务入线, in1 双源是既有设计。
row_bg ffnbg w=1530。

**端口分配铁律**: 同节点多入线必须不同端口 — 标定→左脑用 in2 (in1 已被感知链占); 标定→融合层用 in3 (in1预测/in2观测已占)。

## 代码三件套

1. node_logic.py: `node_neural_climbing` (平行纤维/攀缘纤维/LTD 对照) / `node_neural_ltd` (gate 三档位表) / 更新 `node_neural_calib` (三旋钮: 零偏/执行力/微调)
2. _reg: neural_climbing (["攀缘纤维"]) / neural_ltd (["gate · 突触抑制", "突触抑制"]) / neural_calib 关键词改 ["左脑标定实验", "标定实验"]
3. _show_internal_detail: neural_cerebellum 分支扩展标定旋钮行 + 新增 neural_climbing/neural_ltd 分支 + neural_calib 内容改为左脑三件套

## 验证要点

- 加载 20 节点 24 连线无悬空; DFS 无环; 双击 7 神经节点 → 详情 7 次
- node_logic 全命中; 库覆盖: 7 神经节点名 ⊆ LIBRARY (⚠️ 库按钮名与画布节点名必须一致 — α 标定实验 vs 左脑标定实验 曾不一致导致覆盖检查报缺)
- 单步 30 步无异常; cerebellum_calib.py 真实出数据 + 52KB gate 图

## 坑

- matplotlib 新版 addfont 在 font_manager.fontManager; emoji 在 plt 标题会 UserWarning 缺字形 (去 emoji)
- 画布节点名改 → LIBRARY 按钮名必须同步改 (覆盖检查是硬性断言)
- 大 patch 用小块替换 (neural_cerebellum 分支整体替换失败 → 拆小块成功)
