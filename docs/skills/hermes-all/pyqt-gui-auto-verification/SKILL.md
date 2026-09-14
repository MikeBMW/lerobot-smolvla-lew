---
name: pyqt-gui-auto-verification
description: Use when PyQt5 GUI 自动取证测试 — 驱动真实窗口截图作证据入报告。
---

# PyQt5 GUI 自动取证测试 (真人测试工程师自动化)

触发: 让 GUI 自动化"操作所有图表/窗口"做验证、每个用例要截图证据、报告要嵌图。
Z-MAX 仓库具体入口/机制见 `references/zmax-studio-automation.md`。

## 通用工作流
1. 环境: PyQt5 venv; 有 DISPLAY 用 X (3D/GL 窗口才能渲染), 无则 `QT_QPA_PLATFORM=offscreen` (3D/GL 项会失败 — 诚实记录 FAIL, 别假装)
2. 构造应用: `app = QApplication.instance() or QApplication([])` (模块可被 import 复用, 顶层建 app 也无妨; 无 widget 前可后建)
3. 实例化被测主窗口模块 (无参构造常见, 如 `SimulinkModule()`), 调其"打开目标画布/场景"方法 (替代人工点按钮)
4. 驱动数据准备: 引擎/仿真先真实跑一次 (轨迹缓存), 数据源若有独立缓存属性则留存引用 (`_ss_last_sim` 模式: 引擎对象留存供窗口取末帧)
5. 打开每个观察窗口: 优先调 UI 自身的统一打开入口 (`_open_viz_node(kind)` 式分派), 而不是每个窗口手写
6. 截图: `widget.grab().save(png)` + `app.processEvents()`; 查找顶层窗口按 `__class__.__name__` 过滤 `app.topLevelWidgets()` (等 0.1s×N 轮询出现)
7. 内容断言: PIL 读灰图算"非背景像素占比" (`(a>40).mean()`), 每类窗口给独立阈值 (直方图>0.002, 波形>0.005, 3D/视频>0.01); 另断言结构字段 (buffer 长度、投影 shape (512,2) 等) — 截图非空 + 结构字段双保险
8. 汇总: 逐项 {case, desc, pass, evidence, detail} → JSON; PDF 嵌图 (reportlab platypus Image, 中文用 wqy 字体); Excel 加 sheet
9. 多帧数据: 窗口若累积 N 帧才出图 (堆叠/散点), 测试脚本先开窗再逐帧喂真实数据 (如从训练 parquet 回放真实帧跑模型 forward → push 窗口), 别只喂末帧

## 坑 (已踩)
- **cv2 自带 Qt 平台插件污染**: 先 import cv2 (ultralytics 等) 后建 QApplication → Qt 从 `cv2/qt/plugins` 找 xcb → "Could not load the Qt platform plugin xcb" (缺系统依赖)。修复: 建 QApplication **之前**设 `QT_QPA_PLATFORM_PLUGIN_PATH=<site-packages>/PyQt5/Qt5/plugins` (遍历 sys.path 找含 platforms/ 的目录)。别只删 cv2 路径 — 显式指定 PyQt5 真实目录即可
- QApplication 只能在 import 任何 Qt widget 前创建一次; 被报告侧 import 时 (cv2 已加载) 也要先设插件 env 再建 app
- offscreen 平台弹窗 API (raise_/activateWindow) 报 "does not support raise()" — 无害, 忽略
- 窗口单例: 挂被测模块实例属性 (`module._xxx_win`), 让"双击打开"与"脚本驱动"共用同一窗口, 避免双窗口
- 引擎跑完只有末帧 probe: 若可视化要过程帧, 从数据文件回放真实帧 (诚实: 模型在真实历史 obs 上真实 forward), 别伪造中间帧
- 有 X 时后台跑脚本会短暂弹窗到桌面 — 可接受; 别用 nohup/后台静默跑 Qt 脚本 (信号/退出问题), 前台超时或 background+notify

## 报告集成
- 纯 CLI 测试报告生成器 (无 Qt) 集成 GUI 取证: import 取证模块前先设插件 env (见上), 调其 `run_viz()` 返回 results list
- PDF 结构: 摘要/环境/用例汇总/…/可视化证据章 (每图带 case+desc+PASS/FAIL)
- Excel: 原 sheet 外追加"可视化验证" sheet (用例ID/验证内容/结果/实测证据/证据文件)
- 一键重跑保持单一入口脚本 (CLI 用例 + GUI 取证 + PDF + Excel 一条命令)

## 相关文件 (Z-MAX 仓库实例)
- `tools/gen_viz_evidence.py` — GUI 取证参考实现 (构造 SimulinkModule → 画布 → 引擎 → 5 类窗口截图断言 → JSON)
- `tools/gen_verif_auto_report.py` — 报告集成参考 (PDF 8 章含可视化证据 + Excel sheet)
- `tools/gui/ff_hist_view.py` / `ff_attrib_view.py` — QPainter 自绘数据窗口带公开 push() API 的可测模式
