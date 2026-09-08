# 550 用例全量验收 + 摆设断言审计 + metaworld seed 陷阱 (2026-09-04 老倪)

老倪验收要求: ①导出含所有 function↔用例、看总体 ②真实运行不假设 ③真实数据路径
④不过→自动改进→再测→全合格 ⑤YOLO 真链路不许偷真值 ⑥报告朴素语言无缩略语
⑦Excel 结果 ⑧突出精细操作独特用例 vs 普通动作。全绿交付 + commit e6a087e0/5d8f29ba。

## 摆设断言审计法 (零空转铁律的执行细节)
- **grep 审计**: `grep -n "or True\|and True\|return True," verification_layer.py` —
  逐条区分: 有 if 条件保护的 = 真 SKIP 分支 (无数据/无轨迹/无 torch 可接受);
  无条件 `or True` / import 成功即 True = 假过必修。本次抓到 5 处:
  | 用例 | 摆设形态 | 真断言修法 |
  |---|---|---|
  | t_pred_default | `A==1.0 or True` (类默认实为 A=0.95) | 审计 state_space_sim/sim_real/node_logic 全部 `PriorDynamicsPredictor(` 实例化点 `A=` 显式 1.0 (标定 prior_A 写回锚) |
  | t_yolo_nofake | `0.99 not in … or True` | 正则截 `def _io_snapshot` 方法体 → 去 `#` 注释行后无 "0.99" 且含 "conf --" |
  | t_llm_unknown | `len(tokens) >= 1 or True` | `0 ≤ len ≤ 50` + try/except 不崩 (plan 对未知指令回退默认主链 4 token) |
  | t_rsn_count | `k_lo != k_hi or True` | 真断言: veto 2/5 次→"插入未到位" ≠ veto 6/5→"力控异常" |
  | t_sched_real | import quick_run 成功即 True | 真跑 quick_run 2 集 ≥1 完成 (detail 带 完成率+末集摘要) |
- 修断言后必单独真跑验证 (PASS 且 detail 带真实数值), 再全量回归。
- **semi 分类口径**: 16 项 semi 多数可本机真跑 (RealStateSpaceSim 渲染/源码审计),
  少数需真机 (真夹爪/滑脱/微力) — 审计实现后按实跑, 别默认 skip。全量 = skip_slow=False。

## metaworld seed 陷阱 (顺序耦合 → 假随机)
- **实锤**: metaworld `env.reset(seed=…)` **忽略 seed** (sawyer_xyz_env.py reset 文档
  "Ignored, use seed() instead"); `_freeze_rand_vec=False` 时 `_get_state_rand_vec`
  走 **全局 np.random.uniform** (L713) — 布局由进程全局随机状态决定, 不随 seed。
- **复现数据**: 同 seed=100 干净进程销头初位 [0.0283,0.5398] vs 先 `_reset(0)` 污染后
  [0.0345,0.6169] → 500 步插不进孔 (真实化基线 6/12 不稳的根源之一)。顺序测试里的
  RealStateSpaceSim 实例共享 `_ENV` 全局单例 (state_space_sim_real._make_env)。
- **修复 (state_space_sim_real._reset)**: `env._freeze_rand_vec=False` →
  `np.random.seed(seed*7919+13)` → `env.reset(seed=seed)` → freeze=True。
  同 seed 恒同布局; 不同 seed 仍不同 (非造假)。修复后 seed=100 布局固定为控制器
  "难例" (500 步插不进) — 单集必完成不是稳定契约, 闭环用例用 2 集 ≥1 完成。
- **诊断法**: 疑测试顺序耦合 → 打印 site 初位对比 (env.data.site_xpos[site_id]) 干净 vs
  污染后是否漂移; 别先怀疑控制器。
- 连带修复: t_sssensor_real 手工拼 33D ≠ fuse_sensors 要求 39D (AssertionError 从没
  真跑过) — 照 state_space_sim_real.py 主循环 L379-386 构造 cur18+prev18+target3=39D。

## 全量验收通道 (产物不入库)
- **命令**: `DISPLAY=:0 gui-venv311/bin/python tools/test_acceptance_run.py` (EXIT 0=全合格)
- gui-venv311 在 **仓库内** `/home/ubuntu/lerobot-smolvla-lew/gui-venv311` (~/ 下没有!),
  已实测含 torch 2.7.1+cu128 CUDA 可用 (2026-09-04)。
- 环境自检 7 项 (引擎/六层/标定/流形/planner/YOLO 权重/DISPLAY) → 全量真实执行
  auto 339 + semi 16 逐用例计时 (manual 195 标"手动+验收步骤"不跑) → Excel + txt。
- **Excel 4 sheet**: 总体一览 (110 功能 × 5 用例列: 过/败/手动+34字证据) /
  全部用例明细 550 行 (结果+实测证据+耗时秒+手动步骤) / 精细操作专项 (PRODUCT_TREE
  jobs 含 插拔/耦合/力控/对准 → 精细, 取放/搬运/流转 → 普通; 每功能白话说明 +
  10 条"普通动作没有的独特检查": 销头到孔底 <4mm/通道轴/接触概率联动/防抖确认/
  滑脱回退/否决减速/η 完成态/力→概率单调/夹持锁存/质检可复现) / 执行环境与统计。
- **朴素语言**: _plain() 替换表 (SKILL.md 级别提示: 报告禁缩略语 — metaworld→物理
  仿真环境、43D→43 个数值、σ(残差·gain)→误差→接触概率换算、x̂₋=A·x+B·u→按上一时刻
  推算、η=exp(−V/σ²)→用对准偏差估算耦合效率、cam_mat/fovy→相机矩阵/视野角…);
  长串替换在前 (组合表达式先于单字符), 注意 "39D 视觉" 与 "39D" 顺序避免重复词。
- 全量执行 ~7s (metaworld 纯物理步无渲染很快; R0 quick_run 2 集 ≈ 850 步含在内)。
- 报告/Excel 放 reports/ 时间戳文件, **不入 git** (交付件; 老倪 Git 精简惯例)。
