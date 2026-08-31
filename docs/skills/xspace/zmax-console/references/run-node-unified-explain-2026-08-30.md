# 运行节点统一执行 · 代码讲解 · debug 逐行 · 查看数据集 · VSCode (2026-08-30 老倪)

一次会话落地的五组功能, commits 86d44554 → dfafff10。offscreen 验证脚本:
/tmp/verify_unified_run.py、/tmp/verify_explain.py、/tmp/verify_trace_exec.py、
/tmp/verify_dataset_info.py、/tmp/verify_vscode.py、/tmp/verify_codeedit_menu.py
(前 5 个已删除, 按本文内容重建即可)。

## 1. 统一执行入口 _run_node_single (86d44554)
- 单步 ⏭ 与右键「运行节点」现在走同一入口。分派:
  ① 环节节点 (名字匹配 NODE_RUN_ACTIONS) → `_run_node_stage` (worker 异步,
     running青 → success绿/error红, 含 execute_node_logic)
  ② params.run_env 数据层 → `_run_env_wrap` → `on_run_env` (按当前模式训练/推理)
  ③ 其他 → `_sim_node(node, keep_active)` (节点逻辑 + 数据流模拟)
- 统一: 执行前金色高亮 (_highlight_node; 环节/数据层 4000ms, 其他 2500ms) + 防重入
  (worker running → busy 提示) + 终端统一日志。
- 差异保留: 单步 keep_active=True (step_active 金色保持 = 当前步位置);
  右键运行 keep_active=False (完即绿)。
- **修了单步假绿 bug**: 原 _sim_node 里 execute_node_logic 对训练节点会启动 worker,
  但 _sim_node 立即标 success — 环节节点改走 _run_node_stage 异步状态后消失。
- 右键菜单改动: `_show_node_menu` 里 `a_run → self.module._run_node_single(...)`;
  _run_node_stage 日志文案 "⏳ 双击运行" → "⏳ 运行" (统一)。

## 2. 🧩 代码讲解 explain_node (2c8b7bff / 0ded9612)
- `node_logic.explain_node(name, module=None, out=None)` 返回多行文本:
  功能 (注册 doc) → 可修改区逐行 (代码+行尾注释, "语法:" 前缀) → 框架动作
  (return 行, "框架:" 前缀, ← 调度/激活动作) → 全局定位 (画布 N/总 + 上下游
  从 module.links 实时算, 名字去 emoji 前缀) → 数据空间 (params.dims/desc) →
  仓库路径 (_probe_data_root) → dataset/dataloader 比喻 → 趋势 (out)。
- **语法行上限 MAX_SYN=6**: train 等复杂节点 (39 行) 不刷屏, 超出输出
  "…(共 N 行, 其余省略 — 右键「查看/编辑节点逻辑」看全量)"。
- `_probe_data_root()`: 探测 data/ 下 closed_loop(Orin真实) → metaworld_peg_long
  → metaworld_peg → ss_insert_lerobot(状态空间), 读 info.json 输出
  "路径 · 帧数/集数 · 来源 · 特征[image,state,action]"。
  **目录层级坑**: node_logic.py 在 tools/gui/, 仓库根 = `../..` (两级);
  写成 `../../..` 会退到 /home/ubuntu, 探测永远 None (实测踩过)。
- 比喻 (老倪要 "形象解释"): 📦 数据源=原料仓库 → dataset=分拣台 (逐帧读取+
  算归一化 mean/std) → dataloader=传送带 (按 batch 送样) → 模型=机床 → checkpoint=成品。
- 接入: simulink_module._log_explain(node) 在 _run_node_single 三分支执行前调用。

## 3. debug 逐行执行 _trace_exec (44d0bed1)
- `node_logic._trace_exec(fn, ctx, log)`: sys.settrace 行追踪, 每行输出
  `  ▶ L行号: 代码 → var1=值  var2=值` (只显示新增/变化的变量)。
- **必须只追踪 fn 自身**: `if frame.f_code is not fn.__code__: return tracer` —
  否则递归进库代码/子函数刷屏。
- 大对象跳过: module/log/ctx/p/info 显示 `<类型>`; 标量显示 repr (截断 42 字符)。
- execute_node_logic(module, node, label, trace=None): trace 默认读
  `module._trace_nodes`。_run_node_single 开头 `self._trace_nodes = True`,
  finally 恢复 — 单步/右键/环节/数据层全部生效。
- **settrace 时序**: line 事件在下一行执行前触发 → 上一行赋的值在本行才显示,
  变量变化"延迟一行"。debugger 同款语义, 不是 bug。
- 输出顺序: 🧩 讲解 → ▶ 逐行 → 执行结果日志。
- settrace 只在主线程有效; execute_node_logic 都在主线程调用, 没问题。

## 4. 📊 查看数据集 _DatasetInfoDialog (7f68e242)
- 右键数据源节点 (params.source 且非 insert_video/report) 菜单加「查看数据集」。
- `show_dataset_info(node)`: 路径映射与 _ensure_training_data 一致
  (orin→data/closed_loop; ss_sim/状态空间→data/ss_insert_lerobot;
  metaworld→metaworld_peg_long→metaworld_peg) → _probe_dataset → 弹非模态
  _DatasetInfoDialog (_show_nonmodal + _popup_on_main_screen)。
- 对话框 (深色, 620x560): 来源标签 + 路径 (📋复制) + 属性网格 8 项 +
  说明 (LeRobotDataset 从这里逐帧读取) + 4 按钮:
  📂打开目录 (WSL explorer.exe / xdg-open 自适应) / 🎬浏览内容
  (DatasetViewer("local","",parent,local_root=dp)) / 🚀跳转数据集管理
  (`self.window().home.module_clicked.emit("dataset")` — 主窗口导航信号链) / 🔄刷新。
- **坑1: _probe_dataset 只读 dp/info.json, LeRobot 标准布局 info.json 在
  meta/ 子目录 → 补 `if not exists: ij = dp/meta/info.json`** (修前帧数/特征丢失)。
- **坑2: 特征 key 是 "特征 observation.state" 前缀式**, 显示要合并
  `[f"{k[3:]}: {v}" for k in info if k.startswith("特征 ")]`。
- 需要模块级 import QGridLayout (原来只在函数内 import, 类定义处 NameError)。

## 5. 🚀 打开 VSCode 调试 open_in_vscode (15d71a4f / 13b7928b / 48845a93)
- 右键任何节点菜单加「打开 VSCode 调试」→ `open_in_vscode(node)`:
  1. 写 `.vscode/settings.json`: python.defaultInterpreterPath =
     gui-venv311/bin/python + python.terminal.activateEnvironment=True
  2. 写 `.vscode/launch.json` 两配置: 「Z-MAX 控制台 (gui-venv311)」
     (program=tools/gui/studio.py) / 「工具脚本 (lerobot-venv)」
     (program=${file}, justMyCode=False) — 前者 F5 断点单步 GUI,
     后者调试任意打开的脚本
  3. `code root -g path:line`: 打开工程 + 定位当前节点真实源码
     (node_logic.get_node_location: node_logic.py 或外部映射文件)
- **老倪两次反馈 "VSCode 里源代码是空的"**: ① 旧版只 `code root` 不开文件 →
   加 -g; ② 「打开源代码」菜单对数据源节点原来只弹提示框 → 也改为直接
   open_in_vscode(node)。日志明确输出 "📂 … → VSCode 打开运行逻辑: node_logic.py:740 (函数 …)"。
- 诊断 VSCode 是否真打开文件:
  - `xdotool search --name "node_logic"` 有窗口 = 文件 tab 已打开
  - 内容是否空白: `xwd -id <wid> -out f.xwd` → `xwdtopnm f.xwd > f.pnm` →
    PIL+numpy 分析编辑器区亮像素占比 (>0.5% = 有文字)
- 注意: 测试 monkeypatch subprocess.Popen 捕获 cmd 断言 [code, root, -g, file:line]。

## 6. 代码编辑区右键菜单全黑 (ac89b3d3)
- 症状: 节点逻辑/源码/JSON 编辑区选中后右键, 菜单背景全黑, 鼠标滑过才显示文字
  (标准 context menu 无 QSS, 当前 Xorg 渲染黑屏)。
- 修复: 子类化重写 contextMenuEvent:
  ```python
  class _CodeEditor(QPlainTextEdit):
      _MENU_QSS = ("QMenu { background:#161b22; color:#e6edf3; border:1px solid #30363d; } "
                   "QMenu::item { color:#e6edf3; padding:6px 22px; } "
                   "QMenu::item:selected { background:#1f6feb; color:#ffffff; }")
      def contextMenuEvent(self, e):
          menu = self.createStandardContextMenu()
          menu.setStyleSheet(self._MENU_QSS)
          menu.exec_(e.globalPos())
          menu.deleteLater()
  ```
  与 _LogBox 同款。应用: NodeLogicDialog.self.edit 改用 _CodeEditor();
  SourceViewDialog 的 _CodeEditor 自动生效; simulink_module 场景 JSON 编辑框
  用 _CodeEdit (同款)。
- **顺手修 QSS f-string 拼接遗留**: `f"QPlainTextEdit {{ ... }}" + " ...; }}"`
  — 结尾 `}}` 在普通字符串段是字面双大括号 → QSS 语法错, 一直
  "Could not parse stylesheet" 警告 (背景仍生效, 解析器容忍尾部)。
  修: 结尾 `}` 只在 f-string 段转义。
- 验证: 逻辑 (菜单 actions 含 Copy/Select All + qss 含 #161b22) +
  真实渲染 (DISPLAY=:0 弹菜单截图 avgRGB≈(34,39,46) 深色 + 亮像素>3% 文字)。
  亮像素阈值别定 5% — 只有 2 项的小菜单文字面积小, 4.9% 已正常。

## 7. 节点逻辑字体 (dfafff10)
- NodeLogicDialog 编辑区原 QSS font-size:17px — **QSS px 是逻辑像素 ≈12.75pt**,
  老倪 "字体太小看不清"。改编程式 `QFont("DejaVu Sans Mono", 18)` (point size,
  与 SourceViewDialog 的 QFont 风格统一, 17→18pt)。
- 验证: `dlg.edit.font().pointSize() == 18`。
- 通用: 代码编辑区一律编程式 QFont 控制字号, 别用 QSS font-size px
  (QSS px vs QFont pt 数值感差 25%+; 且 QSS 选择器对子类匹配怪癖多)。

## 8. 环境/工具杂项 (本会话)
- pip/uv 装 metaworld 系会僵死 (resolver 卡 0% CPU): 正解 = curl 拿 wheel →
  `unzip -t` 校验 → `--no-deps` 安装或 unzip 解包进 site-packages → 逐个补
  import (glfw/imageio/scipy/PyOpenGL, aliyun 源快)。系统库需
  libglfw3-dev libosmesa6-dev patchelf。
- GitHub push 网络抖动: 重试脚本模式
  `for i in $(seq 1 10); do git push ... && break; sleep 15; done` 后台跑
  notify_on_complete — 一次成功可连推积压的多个线性 commit。
- pkill 自杀坑第三次复踩: 命令串里只要含明文 "studio.py" (哪怕在 git commit
  消息里), `pkill -f "[s]tudio.py"` 也会杀自己 shell → pkill 与其它操作
  必须分开成独立 terminal 调用, 或 PAT 变量 + 确认命令串无明文目标名。
