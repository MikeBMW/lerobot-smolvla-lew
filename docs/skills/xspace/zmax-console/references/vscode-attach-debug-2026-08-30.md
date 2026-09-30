# VSCode 断点调试集成 + 代码讲解/debug逐行/查看数据集 (2026-08-30)

老倪连续四轮需求: 打开 VSCode 工程 → 打开实际源代码 → 设置断点单步 → 不要启动新控制台。
最终形态 = **attach 模式**。commit 4862b2f0 / b336959c / 13b7928b / 48845a93。

## 0. ⚠️ 2026-08-31 变更: 默认 F5 = 「🚀 全新调试进程」(commit f16fdae5)

老倪: "找不到 attach 现有控制台 5678 → 增加: 点击 start debugging 后全新开启一个调试进程"。
**根因**: attach 需控制台已启动且 5678 在监听; 控制台没跑时 F5 attach 直接失败/找不到。
**落地**: launch.json 三配置重排, **第一位 = launch 全新 studio.py 实例 = 默认 F5**
(program=tools/gui/studio.py, python=gui-venv311, cwd=root, console=integratedTerminal,
justMyCode:false); 第二位 = 🔌 Attach 现有控制台 (5678) 保留备用; 第三 = 工具脚本。
open_in_vscode (simulink_module.py 10951) 生成逻辑同步, 右键重新生成一致。
studio.py main() 仍 debugpy.listen(5678) 不阻塞 (attach 备用), 提示语更新。
⚠️ 附带教训: 上次会话改的 .vscode/launch.json + settings.json 一直没 commit
(HEAD 里还是旧的 "Debug SmolVLA Train" xspace 路径) — VSCode 工程配置改完也要提交。
控制台无实例在跑时不需要重启 (下次启动即新代码)。

## 1. 右键「打开 VSCode 调试」= open_in_vscode(node)

- 写 `.vscode/settings.json`: `python.defaultInterpreterPath` = `<root>/gui-venv311/bin/python`
  + `python.terminal.activateEnvironment: true` (VSCode 状态栏/终端自动用 Py3.11 GUI 环境)
- 写 `.vscode/launch.json` (3 配置, **Python dict 生成**):
  1. `Attach 现有控制台 (5678)` — request=attach, connect 127.0.0.1:5678, justMyCode:false (**默认 F5**)
  2. `Z-MAX 控制台 断点调试 (gui-venv311)` — request=launch (备用, 启动新实例)
  3. `工具脚本 (lerobot-venv)` — program=${file}, python=~/lerobot-venv/bin/python
- 命令: `code <root> -g <path>:<line>` — 打开工程 + 定位节点真实源码
  (get_node_location: node_logic.py 或外部映射文件; 行号 = 函数定义行)

## 2. attach 模式 (核心)

- **studio.py main() 开头**: `debugpy.listen(("127.0.0.1", 5678))` 启动即监听, **不 wait_for_client 不阻塞**
- 使用: VSCode F5 (默认 attach 配置) → 连上现有控制台 → 在 node_logic.py 函数内打断点 →
  画布右键运行节点 → 断点命中 → F10 单步, 变量面板看数值
- 验证: `ss -tlnp | grep 5678` 端口 LISTEN; TCP connect 127.0.0.1:5678 可达
- gui-venv311 已装 debugpy 1.8.21

## 3. 演进教训 (三轮纠偏)

1. 第一版: execute_node_logic 埋 `debugpy.breakpoint()` (env ZMAX_DEBUG_BREAK=1 条件触发) —
   老倪反馈: ①"没看到断点" (埋点不是 VSCode 可见红点) ②"没必要再启动一个控制台"
   (F5 launch 新实例和现有控制台并存很乱) ③"我打的断点没起作用" (普通进程不受调试器控制)。
2. 正解 = **启动即 listen + F5 attach**: 现有进程在听, 断点直接生效, 不新开实例。
3. debugpy.breakpoint() 无调试器时是 no-op (无害, 可保留); attach 后用户自己打的断点生效,
   不需要自动断点。

## 4. 坑

- **launch.json 是 Python dict 生成**: dict 项里写 `//` 或 `#` 行内注释 = Python SyntaxError
  (invalid character '🆕'); JSONC 只认 `//` 不认 `#`。注释放 dict 内 `#` 行 (Python 合法, 生成 JSON 时去掉)。
- **VSCode 里看不到源码**: 只 `code <root>` 不传文件 → 打开工程根 (欢迎页/资源管理器), 编辑器空。
  必须 `-g path:line`。88 个节点 get_node_location 全部存在且非空 (脚本验证过)。
- 「打开源代码」菜单 (open_node_source) 对数据源节点原来只弹提示框 → 也改走 open_in_vscode(node)。
- `code` 命令在 /usr/bin/code (WSL shim); 实测 `code root -g file:line` 打开正常 (窗口标题含文件名)。

## 5. 同会话其他功能 (unified-run 系列, 详见 run-node-unified-explain / python-env-probing)

- **_run_node_single 统一执行入口** (单步 ⏭ 与右键运行共用): ①环节节点→_run_node_stage
  (worker 异步 running→success/error) ②run_env 数据层→_run_env_wrap→on_run_env ③其他→_sim_node。
  执行前 _log_explain (🧩 代码讲解) + _highlight_node 金框; 修了单步环节节点假绿
  (execute_node_logic 启动 worker 后立即标 success)。
- **explain_node 代码讲解** (node_logic.py): 功能 doc + 可修改区逐行 (代码+行尾注释, 上限 6 行
  防 train 刷屏) + 框架动作 + 全局定位 (画布位置/上下游) + 数据空间 (dims) + 仓库路径
  (_probe_data_root: closed_loop→metaworld_peg_long→metaworld_peg→ss_insert_lerobot,
  info.json 读 total_frames/features) + 比喻 (仓库→dataset分拣台→dataloader传送带→机床→成品)。
- **_trace_exec debug 逐行** (sys.settrace): 只追踪目标函数自身行 (frame.f_code is fn.__code__),
  line 事件输出 ▶ L行号: 代码 → 变量=具体值 (新增/变化的 locals, 跳过 module/log/ctx/p 大对象)。
  注意 settrace line 事件在下一行执行前触发 → 变量变化显示延迟一行 (pdb 同语义)。
- **_DatasetInfoDialog 查看数据集**: 右键数据源节点「查看数据集」→ 非模态对话框
  (路径📋复制 + 属性网格 帧数/episodes/fps/特征/大小 + 4 按钮: 打开目录 explorer/xdg-open 自适应 /
  DatasetViewer 浏览 / 跳转数据集管理 home.module_clicked.emit("dataset") / 刷新)。
  ⚠️ _probe_dataset 修过: LeRobot 标准布局 info.json 在 **meta/** 子目录 (原只读一级找不到)。
- **右键菜单黑屏**: QPlainTextEdit 标准右键菜单 (createStandardContextMenu) 无 QSS → 全黑。
  子类 _CodeEditor/_CodeEdit + contextMenuEvent + 显式深色 QSS (#161b22 白字, 与 _LogBox 同款)。
  渲染验证: 菜单截图 avgRGB≈(34,39,46) 深色底 + 亮像素>2% (文字) = 正常; 全黑时亮像素≈0。
- 字体: NodeLogicDialog 编辑区 QSS 17px (≈12.75pt) 太小 → 编程式 QFont 18pt 与 SourceViewDialog 统一。
- QSS f-string 拼接遗留: 多段拼接时普通字符串段的 `}}` 不转义 → QSS 尾部多 `}` 解析警告
  (f-string 段要 {{ }}, 普通段要单 { })。

## 6. 磁盘/模型状态

- 本机无 left_right 双脑模型 (磁盘红线清光), 唯一 fallback outputs/rl_peg/full_pipeline.pt
  与 metaworld 3.1.1 物理不匹配 (contact_head 0.30-0.41 徘徊, 12/12 seed 卡转移, peg 抓空)。
  出视频需训练新模型或从 4090 拉。data/metaworld_peg 5400帧/30集, ss_insert_lerobot 3273帧。
