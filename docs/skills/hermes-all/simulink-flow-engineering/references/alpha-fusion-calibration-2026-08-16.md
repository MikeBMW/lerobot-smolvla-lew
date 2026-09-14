# α 融合层 + 标定三件套 (2026-08-16) — 世界模型的"置信度旋钮"

## 思想 (老倪贴的理论)

右脑 GRU 是非线性黑箱, 无法直接改 A 矩阵 → 在「预测值(GRU输出)」和「观测值(传感器)」
之间外挂可调谐残差加权融合层:

    fused = (1 − α)·pred + α·meas       α ∈ [0,1] = 等效卡尔曼增益 (Kalman Gain Knob)

- α→0 完全信任世界模型 (传感器噪声大/瞬态干扰)
- α→1 完全信任传感器 (信号平滑准确)
- α 按状态机阶段调度: 接近 0.3 (靠模型快速驱动) / 转移 0.7 / 插入 0.9 (绝对依赖实时反馈)
- 状态机 = 宏观决策 (何时切换阶段) · α = 微观信号融合 (怎么相信传感器) — 完整标定闭环

## 工具: tools/kalman_fusion.py (.venv 或 gui-venv 跑, 需 numpy/matplotlib)

- `kalman_fusion(pred, meas, alpha)` — 融合层核心函数
- `stage_alpha(stage)` — 增益调度表 ALPHA_SCHEDULE (approach 0.3/grasp 0.5/lift 0.5/transfer 0.7/insert 0.9/done 0.5)
- `calibrate_R()` — ① 静态噪声标定: 静止记录 N 次读数 → σ_sensor → R=σ²
- `calibrate_Q()` — ② 开环漂移标定: 空载快速动作, 右脑只预测推演 → 漂移误差 → Q=σ²
- `scan_alpha()` — ③ α 扫描: 正弦激励, 每 α 拟合残差, 最小 = 最优
- `plot_lissajous()` — Lissajous 图 (α=0 圆 / α=0.6 椭圆 / α=1 线): 椭圆最扁 = 预测观测对齐
- main: 三步全跑 → reports/kalman_fusion.json + kalman_lissajous.png

**坑**:
- GUI 系统 python3 无 numpy/matplotlib → gui-venv 跑; gui-venv 无 pip 模块 → `/root/.hermes/bin/uv pip install --python /root/gui-venv/bin/python matplotlib` (实测 2026-08-16 成功)
- matplotlib 新版 `addfont` 在 `font_manager.fontManager` 下 (旧 `_fm.addfont` 报 module attribute error) → try/except 双路兼容

## 画布: ff_pd_top.json 神经同构行升级 (5 节点 9 连线, 生成器 gen_ff_pd_neural.py)

| id | 节点 | x | params |
|---|---|---|---|
| ffkal | 🔮 右脑 · 非线性卡尔曼 | 150 | neural_kalman, A=0.95, K=0.5 |
| ffkal2 | ⚖️ α 融合层 (置信度旋钮) | 360 | neural_alpha, alpha=0.5, alpha_approach=0.3, alpha_insert=0.9, inputs=[in1,in2,in3] |
| ffcer | 🧠 左脑 · 小脑 (前馈) | 570 | neural_cerebellum, K_ff=0.2 |
| ffctx | 🧭 皮层 · 状态机 | 800 | neural_cortex, contact_th=0.6, Kp=2.0, thresh=0.06 |
| ffcal | 🔧 α 标定实验 | 1030 | neural_calib, n_static=1000, drift_sec=2.0 |

连线 (9): ffy1→ffkal.in1(观测) / ffb1→ffkal.in2(动作) / ffkal.out1→ffkal2.in1(预测)
/ ffy1→ffkal2.in2(传感器观测) / ffy1→ffcer.in1 / ffkal.out2→ffctx.in1(contact)
/ ffsm→ffctx.in2(几何误差) / ffctx→ffact.in2(决策) / ffcal→ffkal2.in3(标定注入)
row_bg ffnbg w=1330 「🧠 神经同构 (脑↔控制)」。

⚠️ **ffcal→ffkal2 用 in3** (不是 in1): ffkal2 已有 in1(预测)+in2(观测), 标定结果走 in3 防端口冲突。

## 代码三件套 (与神经同构行同款)

1. node_logic.py: `node_neural_alpha` (融合层公式+调度表) / `node_neural_calib` (三件套标定说明)
2. `_reg("neural_alpha", ["α 融合层", "置信度旋钮"], ...)` / `_reg("neural_calib", ["α 标定实验", "标定实验"], ...)`
3. `_show_internal_detail` 两个 elif 分支 (neural_alpha 渲染公式+α取值表; neural_calib 渲染三件套表)

## 验证要点

- 加载 18 节点 19 连线无悬空; DFS 环检测无环 (标定→融合→皮层→动作链路)
- 双击 5 神经节点 → _show_internal_detail 5 次
- node_logic 全命中 (z700_internal 系走 params 分支, 排除在断言外)
- 库覆盖: 5 神经节点名 ⊆ LIBRARY Z700 组
- 单步 25 步无异常; tools/kalman_fusion.py 真实跑出 R/Q/α 数据 + 92KB Lissajous PNG

## 升级已有 flow 的姿势 (2026-08-16 实测)

旧版神经行(3节点) → 新版(5节点): 先删旧 id 集 (ffkal/ffcer/ffctx/ffnbg/ffkal2/ffcal) 的节点+连线,
再跑生成器 — 生成器幂等判断是 `if "ffkal" in nids: skip`, 不清旧节点会误判已存在跳过。
