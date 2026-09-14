# 2026-08-06 GUI 布局/主题/渲染教训 (第二波)

## 🔴 最大教训: "左侧列表/侧边栏/模块库" 三个词指三个不同控件 (浪费 3+ 轮)

老倪说"左侧"时**必须先用截图/代码确认对象**，否则白改:

| 老倪说 | 实际控件 | 位置/尺寸 | 代码 |
|---|---|---|---|
| "XSpace Studio 这个列表栏" / "左侧列表" / "侧边栏" | 主窗口 **SystemSidebar** | 主窗口最左 240px, 含 XSpace Studio 标题 + System2/Sys-12 卡片 + ◀ 收起 | studio.py `class SystemSidebar` (L199), `root.addWidget(self.sidebar)` |
| "模块库" | Simulink 页 **LibraryPanel** | 画布左侧 220px, 分组列表 (条件/模型/动作…) | simulink_module.py `class LibraryPanel`, `self.library` |
| 参考应用条 (已删) | 白色模板按钮横向滚动条 | 工具栏下方 44px | `REFERENCE_APPS` + 循环建 QPushButton |

本会话实录: 用户第 1-3 次反馈"左侧模块库没隐藏"我都在 LibraryPanel 打转 (v1 ◀按钮 → v2 蓝色大按钮+双击标题 → v3 工具栏双入口 tl2「📚 模块库」)，全对但**全错对象**——用户真正要的是主窗口 SystemSidebar。直到用户说"XSpace Studio 这个列表栏"才定位。识别线索: 提到 "XSpace Studio" / "System2 / Sys-12" = SystemSidebar; 提到 "模块库分组" = LibraryPanel。

SystemSidebar 折叠实现 (a7b3cabd): 标题行加 ◀ 按钮 + `collapse_requested` 信号 → 主窗口 `_collapse_sidebar`/`_expand_sidebar` (sidebar.setVisible(False) + 左缘 16px ▶ 展开条 + statusBar 提示)。offscreen 验证 14/14。

## 🎨 switch_theme 会把按钮白字替换成深色 → 按钮看不清

`switch_theme` 遍历所有 QWidget 把 stylesheet 里浅色值换成深色值。自定义按钮如果写 `color:#ffffff` 会被换成 `#1a1f2b` (深色)，蓝底深字看不清 → 老倪"找不到按钮"。
**修法**: 按钮样式用 mk_btn 同款浅底 (`background:#e9edf2; color:#1f6feb; border:#d0d7de`)，switch_theme 会正确转成深底蓝字。验证: 断言 styleSheet 无 `#ffffff` 且含 `#1f6feb`。

## 🗑 参考应用条整行删除 (fbc629d9)

用户第 2 次问"还没删掉?" = 要整行删，不是删几个重复模板。彩色工具栏按钮已覆盖: 三/五模型对比·VLA-Touch·AWE·总系统·ACT-Meta·数据闭环。删除 UI 循环即可，`REFERENCE_APPS` 数据保留 (load_reference_app_by_name/模块库完整条目仍用)。验证: 界面 findChildren(QLabel) 无"参考应用"文字 + 模板加载函数仍工作。

## 🗑 工作流过滤按钮行删除 (11cf1249)

「① 访问·标注数据…⑥ 集成·测试」6 个透明底小按钮 = 模块库过滤。老倪觉得没用占地方 → 整行删。连带删 `_filter_library` 方法 (引用已删的 `_wf_btns` 会 AttributeError)；`set_filter`/LibraryPanel.set_filter 保留无害。

## 🐛 SimLinkItem.paint pal NameError (11cf1249)

杀进程时暴露: `paint` 里 `QColor(pal["inactive"])` 引用已删主题字典 → 画布虚线连线**反复崩溃** (watch_patterns "Traceback" 刷屏)。修法: 未选中链路直接 `#8b949e`。**排查主题残留**: `grep -n 'pal\['` 检查所有 paint 方法都有 `pal = THEMES[_CUR_THEME]` 定义 (SimNodeItem L854/row_bg L1560 合法; SimLinkItem 是 bug)。

## 🌗 CICD/Pipeline 面板深色化 (b1702db6)

老倪: "数据闭环控制台改回深色背景，浅色不协调"。PipelinePanel + CICDPanel 全量改:
- 对话框背景 `#f6f8fa` → `#0d1117`
- 卡片/状态栏 `#e9edf2/#d0d7de` → `#161b22/#1e2740`
- 文字 `#1f2328/#24292f/#57606a` → `#c9d1d9/#8b949e`
- 6环节按钮 `#e9edf2` → `#21262d` (含 `_refresh` 里的动态 setStyleSheet else 分支!)
- QSpinBox/日志区同步

**坑**: `_refresh` 里的动态状态样式 (`if s==1/2/3 else` 分支) 和卡片重建样式也硬编码浅色，只改静态 _build 不够——`grep -nE "#f6f8fa|#e9edf2|#d0d7de"` 按类边界切片逐个清。

## 🎥 5 视频同屏对比: 固定尺寸并排超窗口 (2bea7f48)

InferenceVideoDialog 5 个视频框各 `lab.setFixedSize(400,300)` 并排 = 2000px，但窗口 `setMinimumSize(min(1280,...))` → **只有第 1 个可见** (老倪: "第一个能打开，第二个呢")。修法: QGridLayout 3+2 网格 (cols=3)，lab 改 `setMinimumSize(240,180)` 自适应，窗口 1500×700 + 置顶。单模型视频节点双击自动升级全模型对比 (画布探测五模型 → 全开 5 个)。

## 🐛 VLA-Touch rollout x0 修复 (692e65e6)

"拿不起来"残余: VLA-Touch Interpolant 扩散采样训练时 `q_sample(x0=轨迹前帧, x1=目标动作, t)`，但 rollout 里 x0 用了随机噪声 → 扩散从噪声走不到动作空间 → 动作 std=0.10。**修法**: rollout x0 用上帧动作 (act_hist 或 zeros 兜底) → std 0.46/max 1.05。验证: 60 帧 rollout 断言 std>0.3 (30 帧只到接近阶段幅度小，必须 60 帧)。

## 🔢 训练步数 50→10 统一 (0af2128c)

老倪: "改成训练10步吧，先跑通流程"。全仓 `"steps": 50` / `steps=50` / `p.get("steps", 50)` → 10 (simulink_module.py 17处 + node_logic.py 默认 + 2 个训练脚本 argparse default + config yaml)。注意 `n_action_steps=50` 是 ACT 推理参数**不动**。验证: 模板节点 params 全部 steps=10。

## 验证模式 (本会话 8 轮)

- 每次 GUI 改动: 生成 `/tmp/hermes-verify-*.py` (tempfile 路径, hermes-verify- 前缀) → `QT_QPA_PLATFORM=offscreen python3` 运行 → 断言 → 删除。**同一 execute_code 块内 生成→运行→清理** 最干净。
- heredoc 里含中文/emoji 断言字符串会 SyntaxError → 用 write_file 写脚本或直接 subprocess.run 生成。
- 类边界切片断言颜色残留: `range_seg(marker1, marker2)` 按行号切, 别用 awk 到文件末尾 (会误包含模板数据)。
- 截图诊断: `powershell.exe CopyFromScreen` → /mnt/c/temp/*.png → .venv/bin/python numpy/PIL ASCII 缩略图分析 (WSLg 窗口在 Windows 桌面, import/xwd 不可用)。
- offscreen 验证 window mask/`Unknown property cursor` 噪音 = 正常。
