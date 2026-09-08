# 20260808 数据全透明 + 训练可控 + 模型选择器

老倪需求链："本地所有数据要透明/完全可控；训练结果也要完全可控；数据闭环控制台选模型→sim-to-real→stage3"。

## 1. 数据集管理全透明 (studio.py DatasetModule._local_datasets)

- 白名单 cands（好 desc 的中文名/官方名两行）+ **自动补全**：glob data/ 全部目录，未列入白名单的加通用行
  `name: f"📁 {_d}\n(data/)"`，tags ["local","auto"]——**data/ 每个目录都可见**。
- 两行命名：上行中文名 / 下行官方任务名（`f"📁 {cn}\n{official}"`）。
- 本地行"任务数"列恒"—"（单一任务演示集，帧数/eps 在描述列）；本地行下载按钮禁用（"本地"）或 orin 类指向 CICD 网页。

## 2. 训练结果完全可控 (DatasetModule._refresh_train_results)

- 数据集页表格下加「🧠 训练结果 (outputs/train)」区：每行 = 目录名 · 步数(ckpt 最大数字) · 大小(MB) · 时间 + 🗑 删除按钮。
- 删除保护：`pgrep -f lerobot_train` 有进程 → 拒绝删除（"训练进行中, 不删除训练目录"）。
- 注意：`bl.addLayout(self._tr_box)` 后刷新要先 takeAt 清空旧项。

## 3. 数据闭环模型选择器 (simulink_module.PipelinePanel)

- 状态栏后插入模型选择区：QComboBox（7 模型 `名字 · MM-DD HH:MM`）+ 属性 QLabel（ckpt/训练时间/步数/尾loss）+ 「🎯 Sim-to-Real (S2)」「🚀 Stage 3 真机微调」按钮。
- `_reload_models()`：glob reports/train_curve_*.json → _DISP 显示名映射 → ts 字段格式化 → _model_meta。
- 默认选中 AWE（index 2）。`_on_sim2real/_on_stage3`：写 docs/PIPELINE_STATE.json stages["2"/"3"]（model/policy/status/ts）+ log_signal。
- 验证坑：`PipelinePanel.__new__()` 不调 __init__ 会缺控件（lbl_stage_now 等）→ monkeypatch `pp._refresh = lambda: None` 再测。

## 4. 训练状态监视（终端要看到训练状态）

- 外部/飞书端启动的训练 stdout 是 **pipe**（/proc/PID/fd/1 → pipe）→ GUI 读不到；训练目录无日志文件、曲线 json 也不写。
- `_poll_train_state`（挂在 _poll_ext_log 里每 2s）：
  - `pgrep -f lerobot_train` 检测进程（不管谁启动）
  - 最新 outputs/train/*/checkpoints 的**最大数字 ckpt** = 当前步数
  - 总步数从 `config_{目录名}.yaml` 的 `^steps:` 正则读 → 百分比
  - loss 尽力：train_curve_{policy}.json 尾点（仅当 mtime 新于训练目录——外部训练不写就略过）
  - 显示 `⚙ 训练中: {name} · 步 {mx}/{total} ({pct}%)`
  - **去重**：`self._last_train_state` 变化才 _safe_log（防刷屏）；有→无时提示 "✅ 训练完成"

## 5. 数据集目录统一命名（rename 全引用流程）

- 老倪："在 data 里统一名称"——`metaworld_peg_lerobot` → `metaworld_peg`（去格式后缀，变体风格统一：peg/peg_long/peg_far）。
- **rename 流程（已验证）**：
  1. `mv data/旧名 data/新名`
  2. `grep -rl "旧名" tools/ config_*.yaml reports/ | grep -v __pycache__ | xargs sed -i 's/旧名/新名/g'`
  3. 验证无残留 + 表格显示 + config root 指向新名（tempfile ad-hoc）
- 引用文件类型：simulink_module.py（数据源节点名/placeholder/候选）、studio.py（cands/repo_id）、data_space.py、eval_insert.py、config_*.yaml。

## 6. 其他

- 数据判断"有没有用"：查 `config_*.yaml` 引用（peg_far 有 config_act_peg_far.yaml → 保留；无引用 + 训练完成 → 删）。
- 磁盘铁律对**外部会话训练产物**同样执行：act_peg_long/far 各 25 个中间 ckpt → 只留 004000+last（58G→33G）。
- 飞书同步：本地实际状态 vs 飞书端说法不一致时，发 dataworld 群消息对账（chat_id oc_c0b4048546145c5c581ddd1a9e8f565d）。
- home 顶层清理：一次性任务脚本（build_zmax_ppt_slide.py/poll_win_build.py/zmax_train*.sh/zmax_*.log）确认无代码引用后删。
