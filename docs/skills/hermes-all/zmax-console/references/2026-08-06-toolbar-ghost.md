# 2026-08-06 下午 — 工具栏归类 / 防重入提示 / emoji 标题乱码 / 对话框幽灵残留 / 流程时钟

提交链（本段）：e82e8ae0 工具栏归类 → e66ecd00 删重复时钟 → f2d2234d 画布标题emoji → 38677ef2 防重入详细提示

## 1. 工具栏归类：工具类 | 分割线 | 数据应用（e82e8ae0）
老倪要求把两行工具栏合并成一行并归类：
```
[▶运行 ⏭单步 ⏹停止 🧭引导 ⛶浮动 💾另存为 📂加载 💾保存模型 🔴录制 ⏹停止录制]
┃ 分割线 (QFrame.VLine, setFixedHeight(28))
[🎯数据闭环控制台 🔬三模型 🔬五模型 🖐VLA-Touch 🧿AWE 🎛总系统 ⬅返回总系统] 右侧 t=0.00s
```
- 删掉原第二行 tb2/tl2/lbl_op（QFrame 44px 行整个移除，outer.addWidget(tb2) 去掉）
- 合并时注意：lbl_clock 易重复定义两处（t=0.00s 出现两次）——merge 后必须 grep 查重
- 分割线用 QFrame + setFrameShape(QFrame.VLine) + setFixedHeight(28) + 样式 width:1px

## 2. 老倪 UI 精简铁律（本次再次验证）
- "没用就删掉" 是最高频反馈：按钮/控件/整行 UI 只要用户觉得没用直接删，不要保留"以防万一"
- 本段删除清单：CICD 默认流水线+取料100G 模板、工作流过滤行(①访问·标注数据)、参考应用条整行、🪟画布窗口按钮+show_canvas_win、时间10.0s/dt 控件、🖥Scope 工具栏按钮、🧠ACT-Meta 引导按钮、📚模块库工具栏按钮
- 入口去重原则：同一功能只留一个入口（彩色按钮 vs 白字参考条重复 → 删参考条整行）
- Scope 从工具栏移入左侧 node 库：LIBRARY 新增 `("system", "📊 评估 (3)", [...])` 分组，节点双击走既有 NODE_RUN_ACTIONS ("Scope","on_scope") 链路，零额外代码
- 删按钮前必查引用：btn_scope/btn_actmeta/show_canvas_win 等被别处调用会 AttributeError；删控件前查 .value() 读取（start_sim 读过 sp_dt.value() → 改 getattr 兜底）

## 3. ⚠️ "左侧列表/模块库" 歧义——改错对象浪费 3 轮（本段最大教训）
老倪三次反馈"左侧模块库没隐藏"，我改的是 SimulinkModule 的 LibraryPanel（画布左侧小面板）——**用户实际指的是 XSpace Studio 主窗口左侧 SystemSidebar**（240px，含 XSpace Studio logo + System2/Sys-12 卡片，studio.py 主窗口 root 布局第一个 widget，注释写"可隐藏"但从未实现）。
- 教训：GUI 布局问题先确认用户看到的窗口。诊断手段：
  - PowerShell 截图: `powershell.exe -NoProfile -Command "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; $b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds; $bmp=New-Object System.Drawing.Bitmap($b.Width,$b.Height); $g=[System.Drawing.Graphics]::FromImage($bmp); $g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size); $bmp.Save('C:\temp\x.png')"`
  - 读窗口标题: `Get-Process | Where-Object {$_.MainWindowTitle} | Select ProcessName, MainWindowTitle`
  - PIL 分析截图（/mnt/c/temp/x.png）找 #f6f8fa 面板色/按钮色分布
- SystemSidebar 折叠实现（a7b3cabd）：类加 `collapse_requested = pyqtSignal()` + 标题行 ◀ 按钮；主窗口 root 加 16px ▶ 展开条（_sb_expand_bar）；_collapse_sidebar/_expand_sidebar 方法

## 4. WSLg/MSRDC 标题栏 emoji 乱码（f2d2234d）——"01F 5A5"之谜
老倪问"标题栏出现 01F 5A5 这是啥"——真相：**画布子窗口标题「🖥 画布 · Simulink 模型」里的 🖥 emoji (U+1F5A5) 在 MSRDC 标题栏渲染成十六进制码点乱码**。MDI 子窗口激活时 Qt 自动把子标题附加到主标题（`主标题 - [子标题]`），乱码进窗口标题栏。
- 诊断：`Get-Process msrdc | Select MainWindowTitle` 直接读到完整标题
- 修复：窗口标题（尤其 MDI 子窗口标题，会被附加到主标题）**不要用 emoji**，纯文本最稳
- 其他对话框标题的 emoji（Scope 📊/视频对比 🎥）在各自标题栏也可能乱码，但只在用户反馈时改

## 5. 防重入提示详细化（38677ef2）——"什么叫上一个任务还在跑？"
老倪粘贴日志：ACT 训练完成（✅ 曲线已存）后点运行仍提示"上一个任务还在跑"×2——**这是设计行为**：五模型对比的 5 训练走 _flow_queue 串行队列，ACT 完成后 _flow_next 自动启动下一个（SmolVLA...），此时再点运行被防重入拦截。但旧提示太模糊。
- 修复：_start_worker 启动时记录 `self._busy_info = {"name": ..., "start": time.time(), "queue_len": len(_flow_queue)-1}`；4 处防重入点（_start_canvas_flow/_start_worker/_run_full_flow/_run_node_stage）统一提示：
  `⏳ 正在运行「ACT 训练」已 25s · 队列还有 3 个任务, 完成后自动继续`
- busy_info 名称提取：`(busy_msg or stage or "任务").split("(")[0].strip().lstrip("⏳ ")`
- 无 busy_info 时兜底提示 "worker 运行中"
- patch 技巧：4 处相同旧文本用 replace_all 一次替换（否则 "Found 2/3 matches" 报错，需加上下文行区分）

## 6. 真实流程 vs 仿真 tick——运行 t 时间不变
lbl_clock（t=0.00s）只在仿真路径更新（start_sim→_timer→_tick→step_sim→lbl_clock）。**画布有训练环节节点时 start_sim 走 _start_canvas_flow（worker 真实流程），不走仿真 tick → t 永远不动**。
- 修复：_start_canvas_flow 启动独立流程时钟 `_flow_clock = QTimer(self)` 1s tick，_flow_clock_tick 里 `_sim_t += 1.0; lbl_clock.setText(f"t = {_sim_t:.0f}s")`
- 停时钟点：_flow_next 队列空时 + stop_sim 手动停止时

## 7. PyQt 对话框关闭后"幽灵残留"（视频对比只能打开一次）
现象：InferenceVideoDialog 关闭后再打开不行。诊断：offscreen 打开→accept→再打开，`topLevelWidgets()` 计数 1→2→3→4（旧 dialog 不释放，timer 继续跑）。
- 根因：_show_nonmodal 的 `_done` 闭包捕获 dlg 形成循环引用（dlg.finished → _done → dlg），deleteLater 后 Python wrapper 不释放
- 修复：_done 里先 `dlg.finished.disconnect(_done)` 打破循环再 deleteLater
- **offscreen 验证坑**：`QApplication.sendPostedEvents(None, 52)`（52=QEvent.DeferredDelete）才会真正释放 DeferredDelete；processEvents() 不够。真实 GUI 主事件循环会处理，offscreen 测试必须显式 sendPostedEvents
- 诊断确认：accept 触发 finished（探针 fired=[1]），但 C++ 对象在 sendPostedEvents 前仍在 topLevelWidgets 中

## 8. 验证模式（本段延续）
每改动 offscreen tempfile 脚本（hermes-verify-*.py，QT_QPA_PLATFORM=offscreen，实例化 SimulinkModule 断言按钮存在/折叠状态/布局结构，跑完删除）。断言注意：findChildren(QPushButton) 会把模块库 QToolButton 也算进来——工具栏按钮无 ⬡ 前缀、库按钮有 ⬡ 前缀，要区分；类边界切片用精确 marker（"class X" 到 "class Y"），勿用 awk 到文件尾（会包含模板数据）。
