# 会话案例 (2026-08-07/08 Z-MAX 控制台迭代)

## 案例 1: 架构层边框不可见 (QSS 8 位 hex 全透明)
- 现象: 四层分组框, 系统/数据/场景层有边框, 架构层默认看不到, hover 才出现
- 排查: 架构层颜色 `#00d4aa` → 写成 `#00d4aa88` → Qt 按 #AARRGGBB 解析, alpha=0x00 全透明
- 其他层 `#58a6ff88` → alpha=0x58(非0) 显示"边框"但颜色错乱
- 修复: 全色 6 位 hex 或 rgba(); 验证正则检查 styleSheet 无 8 位 hex
- 教训: Qt QSS 半透明**只用 rgba()**, 8 位 hex 的 AARRGGBB 顺序极易踩

## 案例 2: 产品大屏卡点开无反应 (WSL 无 xdg-open)
- 现象: QDesktopServices.openUrl() 静默失败 (返回 False)
- 验证: offscreen 下报 "Please instantiate the QGuiApplication object first" + which xdg-open 为空
- 修复: `subprocess.Popen(["cmd.exe", "/c", "start", "", url])` → rc=0 实测打开
- 注意: ~/.git-credentials token 提取要取冒号后 (`https://user:TOKEN@github`)

## 案例 3: 训练状态监视 (外部启动的训练 GUI 看不到)
- 现象: 飞书端/命令行启动的 lerobot_train, GUI 日志框无显示 (原监视只盯固定日志文件)
- 修复: `pgrep -f lerobot_train` 检测进程 → 找最新 `outputs/train/*/checkpoints` 最大数字步数
  → 读 `config_<dir>.yaml` 的 steps 做总步数 → `⚙ 训练中: <dir> · 步 N/M (P%)`
  → 状态去重 (变化才 append) + 结束提示 `✅ 训练完成`
- loss 附加: 若 `reports/train_curve_<policy>.json` mtime 新于训练目录才附 loss (外部训练常无曲线更新)

## 案例 4: 视频白屏根治
- 根因链: 曲线 ckpt 更新 → 每次打开对话框检测"ckpt 比视频新" → 自动重生成 rollout → 白屏等 1-2 分钟
- 修复: 有帧分支**永远先 `_play()` 播历史**, ckpt 新只在 note 提示 "点 🔄 重新生成 更新";
  仅完全无帧才自动生成
- 原则: 历史数据优先显示, 重生成改手动 — 治本 (之前多次"修"都是治标)

## 案例 5: 模块库全节点可拖 (模板 ↔ LIBRARY 覆盖)
- 需求: 所有模板(模型对比/VLA-Touch/AWE/总系统/CICD等)的节点都能从左侧模块库拖出
- 方法: 盘点脚本 — REFERENCE_APPS 模板节点集 vs LIBRARY 条目集 → 差集 → 补 LIBRARY 组
- 别名策略: 模板名与库名不一致时 (如 "🧠 ACT 训练" vs "🚀 ACT 训练", "H03 机械臂" vs "机械臂")
  → 库补别名条目 (模板不动), 功能一致
- 最终: 11 模板 0 缺失, LIBRARY 134 节点 20 组
- 主数据: data_space.py 加 `_scan_nodes()` 把 LIBRARY 节点注册为全局数据空间主数据 (node↔主数据映射)

## 案例 6: 验证脚本断言陷阱
- `PipelinePanel.__new__` 免构造 → _refresh 访问未建控件崩溃 → monkeypatch `_refresh = lambda: None`
- 静态断言写 f-string 字面错 (`"_mx 步"` 实际代码是 `"{_mx} 步"`)
- ModuleCard 无 .title/.sys_label 属性 → findChildren(QLabel) 查 badge 文本
- 环境: python3 无 torch → 运行时验证必须 .venv/bin/python (静态检查可用 python3)
