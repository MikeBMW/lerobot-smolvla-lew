---
name: pyqt5-gui-development
description: Use when developing/debugging PyQt5 GUIs on WSL/WSLg.
---

# PyQt5 GUI 开发 (WSL/WSLg 环境)

PyQt5 桌面控制台/画布类 GUI 的开发和调试通用指南。覆盖 WSLg 下的窗口行为、QSS 陷阱、验证模式与安全改代码方法。

## 触发条件
- 修改/调试 PyQt5 应用（QMainWindow/QDialog/QWidget 类、QSS 样式、QGraphicsScene 画布）
- WSL (WSLg) 下运行 GUI、offscreen 验证、打开外部链接
- 对大型 GUI 单文件做批量改动（studio.py 类 8k 行单文件）

## 核心陷阱 (都是实测踩过的)

### 1. Qt QSS 8 位 hex 颜色 = #AARRGGBB (alpha 在前!)
- `#00d4aa88` 会被 Qt 解析为 **alpha=0x00（全透明）** → 边框/背景完全不可见
- 症状: 某层边框"默认看不到、hover 才出现"；其他层"有边框但颜色错乱"（实际是 alpha 高字节当颜色用了）
- 修复: 用 `rgba(r,g,b,0.40)` 或 6 位全色 hex；**绝不用 8 位 hex 做半透明**
- 排查: 检查 styleSheet 里的 `#RRGGBBAA` 写法（Qt 只认 `#AARRGGBB`）

### 2. WSLg 弹窗: exec_() 模态假死
- WSLg 下 `QDialog.exec_()` 模态窗口不显示/假死 → 一律非模态 (`show()`)
- 小窗口/气泡也禁用；反馈用 按钮+日志框+气泡，不用弹窗

### 3. WSL 打开外部链接/文件: QDesktopServices 失效 + cmd.exe UNC 坑
- WSL 通常无 xdg-open → `QDesktopServices.openUrl()` 返回 False 静默失败
- **cmd.exe start 必须带 `cwd="/mnt/c/Windows"`** (2026-08-12 实测: WSL 里 Popen cmd.exe 的当前目录是 UNC `\\wsl.localhost\...`, cmd 报"UNC 路径不受支持" → start 静默不执行, 用户反馈"链接没打开"; 诊断/复现也要从 /mnt/c/Windows 目录跑 cmd.exe)
- 打开 URL: `subprocess.Popen(["cmd.exe", "/c", "start", "", url], cwd="/mnt/c/Windows")`（Windows 默认浏览器，可靠）
- **打开有默认关联程序的文件（视频 mp4/图片/PDF）用 cmd start + cwd 修正**（2026-08-12 实测: explorer.exe 从 WSL 启动受 UNC cwd 影响**静默失败**——用户反馈"点视频节点播放器没弹出"; 改 `cmd.exe /c start "" "C:\...mp4"` + `cwd="/mnt/c/Windows"` 后正常弹 Windows 默认播放器; 测试也要 cd /mnt/c/Windows 再跑 cmd）
- **打开目录/无关联文件（.py/.md/文件夹）用 explorer.exe + Windows 反斜杠路径** (cmd start 打开无关联程序的 .py/.md/目录 会静默失败 → explorer.exe 目录型弹资源管理器; 无需 cwd hack)
- **反复弹出型动作（弹播放器/打开窗口）必须防抖**（2026-08-12 老倪"怎么弹出好几次视频" — 双击重复触发/多次点击会弹多个播放器）: 记 `self._last_xxx_pop` 时间戳, 15s 内重复调用直接 return + 日志提示; 用户多次点击只弹一次
- **Windows 路径 `C:\...` 在 Linux 是相对路径**: shutil 复制/读写目标一律用 `/mnt/c/...`(WSL 路径), 只有 explorer/cmd 展示参数才用 `C:\...`(os.path.join 后 `.replace("/", "\\")` 统一反斜杠); 混用会在仓库 cwd 留下 `C:\zmax_src_view` 之类残留目录(需 find+rm 清理)

### 8. VcXsrv 下 QMenu 深色 QSS = 黑屏无字 (2026-08-12 实测)
- 症状: 右键菜单弹出来只有小黑块, 没有菜单文字
- 排查: ①去掉 `border-radius`(圆角触发半透明合成失败)仍黑 → ②**完全去掉 `menu.setStyleSheet`, 用系统默认菜单最稳**
- 规律: VcXsrv 对 QMenu 自定义深色样式整体渲染失败 — 主窗口/弹窗的深色 QSS 正常, 但菜单是独立 popup X window 容易黑; 别再给 QMenu 上深色 QSS; 验证用 regex 提取 setStyleSheet 实际内容断言(注释里提到 border-radius 会让 naive grep 误报)
- **★ 全局 QSS 也会黑**: studio.py 的 `app.setStyleSheet` 里若有 `QMenu { background:... }` 规则, 同样作用所有 QMenu(删了局部 QSS 仍黑) — 搜全部文件里 `QMenu {{`/`QMenu::item`, 两处都删干净(保留 QMenuBar); 删 QSS 块时注意三引号字符串边界别截断(闭合 `"""` 放错位置 = SyntaxError)
- **★ 系统默认菜单下 emoji 渲染成黑块** (2026-08-12 老倪"有的是白色背景,有的有个黑条"): 菜单项文本带 emoji(📖⚙️📂▶)在系统默认字体缺字形 → 黑色方块条; 菜单项一律纯文本(去 emoji), 画布/按钮上的 emoji 不受影响

### 9. QGraphicsView/QGraphicsItem 悬停事件 (2026-08-12 实测)
- QGraphicsItem 的 hoverEnterEvent 触发需两个前提, 缺一不触发: ①view 要 `setMouseTracking(True)`(QGraphicsView 默认无按键时不分发 hover 给 items) ②item 要 `setAcceptHoverEvents(True)` + 实现 hoverEnterEvent/hoverLeaveEvent(内部 `self._hover=True/False; self.update()`)
- 排查"悬停不生效": 先 grep item 类是否有 setAcceptHoverEvents + hover 事件(本会话 SimNodeItem 完全没有 hover 事件, 只有连线类 SimLinkItem 有 — _hover 恒 False), 再查 view 是否 setMouseTracking; 两处都补才生效
- **VcXsrv 下 hover 事件流仍迟钝 → 终版: view 的 mouseMoveEvent 里 `itemAt(e.pos())` 直接驱动** (2026-08-12 用户报"ID就第一次显示,感觉反应很迟钝"): 每次鼠标移动算 itemAt, 目标 item 设 `_hover=True+update()`, 移出(或移到其他 item/空白)对旧 hover item 设 `_hover=False+update()`; 用 `self._hover_items` 集合跟踪当前 hover 项 — 鼠标位置即状态, 移出即消失, 完全绕开 hover 事件分发; 适合悬停提示(显示 ID/tooltip)类需求
- offscreen 验证 hover 渲染用**像素 diff**(_hover False vs True 两图差异像素>15), 别用绝对颜色计数(节点固有元素会误命中); 模拟 mouseMove 驱动: 构造 QMouseEvent(MouseMove, viewport 坐标) 调 view.mouseMoveEvent, viewport 坐标用 `view.mapFromScene(item.scenePos()+offset)`
- **VcXsrv 下无按键 mouseMove 事件根本不达画布** (2026-08-12 终版, 老倪"你怎么非得用鼠标点击一下呢,改成悬停显示" — 点击按下才有 mouseMove): mouseMove 驱动仍会"头两次显示然后不显示" → **终版 = QCursor 轮询兜底**: `_hover_timer = QTimer(self)` 150ms + `_poll_hover()`: `QCursor.pos()` 与 `_last_hover_pos` 相同则直接 return(**鼠标不动不重绘, 防狂闪** — 初版 80ms 轮询无守卫导致"屏幕狂闪"被否), `isVisible()/underMouse()` 检查 + `mapFromGlobal` → `_update_hover_at`; `_clear_hover()/_update_hover_at` 遍历 `_hover_items` 必须 `it.scene() is not None` 才 update(**删节点后旧 item 引用 update() 会崩溃闪退**), 全部 try/except 兜底; mouseMove 即时 + 轮询兜底共用 `_update_hover_at(vp_pos)`
- **悬停提示类 UI 的用户偏好 (2026-08-12 老倪多轮纠正, 最终形态)**: 仅悬停显示(常显被否)、白色粗体 9px(`#e6edf3`, 蓝色被否)、放节点**右下角**(右上角与标题重叠被否、上方浮动被否)、不遮挡节点内容、背景行(row_bg)不显示 ID; 改 UI 视觉前先确认最终形态, 别按中间猜测迭代 6 轮

### 10. VcXsrv 崩溃/守护 + 窗口验证 (2026-08-12 实测)
- **"屏幕狂闪 + 闪退" = VcXsrv(X 服务器)挂了, 不是代码 bug**: Qt 崩溃日志特征 `qt.qpa.xcb: could not connect to display <ip>:0` + exit 134 — 连接断开 Qt 起不来/崩; **狂闪是 VcXsrv 假死的前兆**; 诊断三连: ①`ps aux | grep "python3 studio.py" | grep -v grep | grep -v bash`(pgrep -f 会连 hermes bash 包装一起数, 误导) ②`tasklist.exe | grep -i vcxsrv`(进程没了 = 挂了) ③`timeout 3 bash -c 'echo > /dev/tcp/<GW>/6000'`(端口不通 = X 挂了); 修复 = PowerShell 重启 VcXsrv, 端口通后重起 GUI; 别在代码上反复排查(轮询/timer 都背过锅, 实为 X 服务器死)
- **VcXsrv 启动参数只有原配方有效**: `-ArgumentList ':0','-ac','-multiwindow','-clipboard','-wgl'`; **`-softgl`/`-nowgl` 不被支持**(进程起来但内存 ~13MB = 初始化失败, 6000 端口不通) → 保持 -wgl
- **守护脚本**: `/home/xspace/scripts/vcxsrv_watch.sh`(检测 6000 端口, 挂自动 taskkill + PowerShell 重启) + cron `*/2 * * * *` — 挂了自己拉起, 不用手动救
- **WSLg 可能未启动**: 查 `ps aux | grep -iE "weston|Xwayland"` 无进程 + `/mnt/wslg/runtime-dir` 有 socket 但图形栈没跑 → 启用需 `wsl --shutdown`(会中断当前会话, 别在会话中做); 选显示方案前先确认 WSLg 进程在不在
- **xdotool 在 VcXsrv 重启后查询失效**(search 返回 0 但窗口实际显示) → 验证窗口用 **Windows 侧**: `powershell.exe -NoProfile -Command "Get-Process | Where-Object { \$_.MainWindowTitle -match 'XSpace' }"`(vcxsrv 持有窗口标题)

### 11. 启动卡顿/闪烁: 延迟创建重量级组件 (2026-08-12 实测)
- 症状: "打开前屏幕使劲闪 + 卡死好几秒" — 主线程构造里同步建重量级组件(200+ 按钮的模块库面板/画布) → VcXsrv 每次窗口映射全屏合成一次 → 闪 + 卡
- `win.hide() + QTimer.singleShot(80, win.show)` **无效且加重**(更闪+卡死, 已 revert) → **正解: 构造期不建重量级组件, `QTimer.singleShot(400, self._init_heavy)` 后置创建**(记录 `self._stack_index = stack.count()` + 完成后 `insertWidget(index, widget)` 插回原 tab 位, try/except 兜底 statusBar 提示); 实测启动 27s→8s
- 规律: VcXsrv 下启动慢 = 主线程同步构造重组件; **延迟创建(QTimer 后置)比 show 时机 hack 有效**; 延迟回调里访问延迟组件时它已就绪(400ms < 2.5s 等); Pyright 对 `self.attr = None` 后访问报 OptionalMemberAccess 是静态误报

### 12. QGraphicsScene 节点双击: canvas 拦截 press 是隐性杀手 (2026-08-12 实测)
- 症状: 用户反复报"双击节点没反应" — 双击 ▶生成视频/数据源切换全不生效, 只有右键菜单"运行节点"能用
- **坑①: item 类可能从未实现 mouseDoubleClickEvent** (SimNodeItem 只有连线类 SimLinkItem 有 — 加之前双击完全不处理)
- **坑② (更隐蔽): canvas 的 mousePressEvent 左键分支拦截了 press** — 节点主体分支(选择/手动拖动) `item.setSelected(...); return` **不调 `super().mousePressEvent(e)`** → QGraphicsScene 收不到 press → **Qt 双击事件(发给接受 press 的 item)也不发** → 就算给 item 加了 mouseDoubleClickEvent 也永不触发!
- 正解: **canvas 手动检测双击** — mousePressEvent 节点主体分支开头:
  ```python
  import time as _t
  _now = _t.time()
  if (getattr(self, "_last_dbl", None) and _now - self._last_dbl[0] < 0.4
          and self._last_dbl[1] is item):
      self._last_dbl = None
      self.module.on_node_activated(item.node)   # 双击语义
      return
  self._last_dbl = (_now, item)
  ```
  0.4s 内同节点二次 press → 触发; 单次 press 只记录; 超时自动失效
- 验证: offscreen 构造两次 QMouseEvent(MouseButtonPress, 同 viewport 坐标, 间隔 0.1s) 调 view.mousePressEvent → 断言 on_node_activated 收到节点名; 单次 press → 不触发; 间隔 0.5s → 不触发
- 排查顺序: ①item 类有 mouseDoubleClickEvent 吗 ②canvas press 对节点分支是否 return 拦截了 super() — **凡自定义 canvas 吞了 press 的, item 事件(含双击/hover 按压)都不可信, 一律在 canvas 层手动实现**


- 大段 patch（>8K tokens）或 execute_code 字符串切片 → 流超时/误截文件（曾把 8k 行文件截到 1.2k 行）
- 修复: 小 patch 多次提交；整段删除用 `sed -i '<a,b>d'`（先 cp 备份）；**绝不用 execute_code 大段字符串操作改大文件**
- **★ 含 shell 命令的 f-string 行绝不用 patch 工具改（2026-08-09 实测 6+ 轮浪费）**：patch 的反斜杠转义层层加倍
  （`"` → `\\"` → `\\\\\\"`），`awk '{print \$2, \$4}'` 一行修了 6 轮。**正解：execute_code 行级重建**——
  Python 读行→定位（先 `grep -n` 精确行号，条件匹配会误中多处）→ `chr(92)` 拼反斜杠构造新行→写回；
  改完三验：`ast.parse` + `eval` 该 f-string 看渲染 + **真实执行命令断言 exit 0**（repr 里 `\\`=1 个反斜杠，别被双重转义显示骗）。
  其他坑：f-string 里嵌 `{cfg.replace('.yaml','')}` 引号冲突 → 预计算变量或 `{cfg[:-5]}` 切片；
  行级重建循环**绝不 break**（截断文件后半）；拼接列表中间行必须以 `,` 结尾（丢逗号 = "forgot a comma" 语法错）；
  改坏直接 `git checkout -- <file>`。详见 zmax-console `references/fstring-patch-escaping.md`

### 5. 跨线程 GUI 操作 = 崩溃（后台线程碰控件/日志区）
- 症状（2026-08-08 容器管理实测）: 点上传/轮询按钮后 GUI 整体崩/窗口消失（守护拉起新进程）。根因: 后台线程里直接 `self.log_text.append()` 或 `btn.setEnabled()`——Qt 控件非线程安全
- 修复模式（两处都要）:
  - **日志方法线程安全化**: `_log()` 里检测 `threading.current_thread() is threading.main_thread()` → 主线程直接追加；非主线程入队，主线程 QTimer flush（见下）
  - **控件状态恢复回主线程**: 线程 finally 里 `QTimer.singleShot(0, lambda: self._btn.setEnabled(True))`，绝不跨线程 setEnabled/setText
- **★ 2026-08-09 实测: `QTimer.singleShot(0, fn)` 跨线程在 PyQt5 下丢消息**（症状: 按钮点击只出主线程第一条日志，线程里后续日志全丢 → 用户以为功能没反应；`QMetaObject.invokeMethod(字符串槽)` 也只认 C++ 原生槽，Python @pyqtSlot 不一定调到）
  - **正解: 线程安全队列 + 主线程 QTimer flush**:
    ```python
    # __init__:
    self._log_queue = []
    self._log_flush_timer = QTimer(self)
    self._log_flush_timer.timeout.connect(self._flush_log_queue)
    self._log_flush_timer.start(200)
    # _log():
    if _th.current_thread() is _th.main_thread():
        self._append_log(text)
    else:
        self._log_queue.append(text)   # 非主线程只入队, 不碰控件
    # _flush_log_queue(): 交换队列 + 遍历 self._append_log(t)
    ```
  - 验证: offscreen + monkeypatch `_append_log` 计数, 调线程函数, 断言全部子线程日志出现（修复前只有 1 条, 修复后全出）
- 排查: GUI 崩但无 Traceback（守护静默拉起）→ 先查后台线程里的所有 GUI 属性访问

### 6. 老倪 UI 极简偏好：复杂状态机 → 几个点选控件
- 2026-08-08 实测纠偏: 容器管理先做"状态机单选 UI"（QButtonGroup + 点击到达状态 + ▶ 执行当前模式按钮 + 状态标签），老倪直接否:"逻辑太复杂，简单点，就做成几个点选控件"
- **正确做法**: 一行 QRadioButton（同 parent 自动互斥，不需要 QButtonGroup）+ 状态标签 + 一个操作按钮，`toggled` 里记 `self._ct_mode = key` 即可
- 规律（印证记忆铁律）: 老倪要的是"点一下即选中"的极简控件，不要执行流程/状态切换/多按钮组合——功能块越简单越好，逻辑藏内部

### 7. QTextEdit QSS padding 上下留白 → 光标/行距视觉两倍 (2026-08-09 实测)
- 症状: 日志区"光标太大了，相当于两倍行高" — 实际是 QSS `padding: 8px` 的上下留白把 QTextEdit 内每行的视觉间距撑成两倍（光标高度=行高）
- 修复: `padding: 8px` → `padding: 2px 4px`（上下 2px 左右 4px，保留左右舒适度、消掉上下虚高）
- 排查: 用户报"光标/行高两倍"先查 QSS padding 和 font-size，别先怀疑字体设置

## node_logic 节点逻辑面板源码映射 (2026-08-12 实测)
「📖 查看/编辑节点逻辑」面板显示代码的机制与坑 (node_logic.py + node_logic_dialog.py):
- 流程: `NodeLogicDialog._key = node_logic.match_node(node_name)`(最长关键字匹配) → `get_external_source(key)`(_EXTERNAL_LOC 映射外部真实源码) → 无则显示自身注册函数源码
- **_EXTERNAL_LOC 映射 = (绝对路径, 行号, 符号名)**: 定位用**符号名搜索**(`ln.strip() == sym or startswith(sym + "(")`), 行号仅兜底 — 行号错位时(映射写 59 实际 60)源码截取从空行开始 → 面板只有"源码结束"标记行(用户报"没有字")
- **sym 必须是真实符号名** (`class RightBrainWM` / `def pixel_to_ray`): 描述文字("grasp 阈值参数")定位失败 → 空白
- **无独立实现的融合/参数节点(State Adapter)不挂 _EXTERNAL_LOC** → 显示自身注册函数(可编辑区); 误指到别的源码(如指向 YoloStateAligner)会被用户发现"两个节点代码一样"
- **逻辑函数开头必须 `log = ctx["log"]`**: execute_node_logic 把 `module._log` 注入 ctx, 函数内是局部变量不是全局 — 新注册函数漏了这行 → 双击执行 NameError; 批量补插时用正则 `(def fn\(ctx\):.*?\n)(    )` 插入, **heredoc 里 `ctx[\"log\"]` 的反斜杠转义会写坏文件**(`\\"` 残留在代码里 → SyntaxError), 用 python 脚本处理时避免字符串里写反斜杠字面
- **用户铁律: 每个节点都得有代码** — Z700 全部 20 个功能节点都注册 `_reg(key, [匹配关键字], doc, fn)`, 无独立逻辑的节点也给描述型逻辑函数(数据源/状态机阶段/方案介绍等); 数据源节点逻辑里写"源码 tools/gen_metaworld_data.py"引导
- 验证: `match_node` 对画布全部节点名遍历 → 无 None + `execute_node_logic(FakeMod(_log), node)` 全部可执行(21/21 PASS)

## 训练产物权限 600 崩 GUI (2026-08-12 实测)
- docker(root)训练产物默认 `-rw------- root root` → 当前用户 xspace 读不了 → **GUI 启动崩溃**(DatasetModule 遍历 outputs/train/ 时 `os.path.getsize` 抛 PermissionError, exit 1)
- 修复双层: ① `sudo find outputs/train/ -type d -exec chmod 755 {} + && sudo find outputs/train/ -type f -exec chmod 644 {} +`(全量! 历史产物同样 600, 只改本次目录不够) ② GUI 遍历加 try/except 容错(sz 回退 0) — 权限问题不再崩启动
- ls 显示 `-?????????`(元数据读不到)= 父目录权限问题, chmod 目录后正常

## 验证模式 (ad-hoc fresh 验证)
- 环境: `QT_QPA_PLATFORM=offscreen` + 系统 python3（GUI 依赖 PyQt5/numpy/PIL/cv2 在系统 python，训练依赖在 .venv）
- tempfile 脚本: `hermes-verify-<主题>-*.py` 写 /tmp → 运行 → 删除（不跑正式测试套件）
- 覆盖**每个 changed path** 的语法 + 静态断言 + 运行时构造验证，输出 ✓/✗ + 退出码
- 陷阱:
  - QWidget 子类 `__new__` 免构造会缺信号/属性（module_clicked 等）→ 真实构造或 monkeypatch 依赖
  - 断言别写 f-string 字面（`"_mx 步"` vs `"{_mx} 步"`）；属性名先查（ModuleCard 无 .title/.sys_label 属性——用 findChildren(QLabel) 查文本）
  - 运行时验证用对解释器（torch 类脚本必须 .venv）

### 静默失败陷阱 (try/except 吞异常 = 功能看似没生效)
- **QDockWidget 挂到 QWidget 上 = 侧栏/停靠面板一直没出现 (2026-08-14 实测)**: `self.addDockWidget(Qt.RightDockWidgetArea, dock)` 只有 QMainWindow 才有 — 宿主是 QWidget 时抛 AttributeError, 被集成处 try/except 吞掉(日志一句"加载失败") → 面板静默缺失, 用户反复问"右侧的栏怎么一直没有"且排查多轮都查不到(代码看着都在)。**排查口诀: "右侧/停靠面板一直没出现" → ① 先 grep 宿主类定义是不是 QMainWindow(QWidget 无 addDockWidget) ② 再查 try/except 是否吞了异常(临时 `except Exception as e: print(repr(e))` 暴露)**; QWidget 容器加侧栏 = 水平 QSplitter 加一列 `split.addWidget(panel); split.setStretchFactor(split.indexOf(panel), 0)`(固定宽可拖), 面板基类 QWidget + `setLayout(lay)`(QDockWidget 的 setWidget(root)/setFeatures/setAllowedAreas 全删)
- **QSpinBox 无 `.decimals()`** (QDoubleSpinBox 才有): `spin.setValue(int(val) if spin.decimals()==0 else val)` 对 QSpinBox 抛 AttributeError → 被 except 吞 → 参数永不更新。修复: 先 `try: spin.setValue(val)` (QDoubleSpinBox) `except: spin.setValue(int(val))` (QSpinBox) 双回退。
- **`dict.get(name, {默认}[name])` 默认参数无条件求值**: Python 先算默认参数再调 get → 即使 get 命中, 默认 dict 缺 key 照样 KeyError (实测: tag dict 无"官方专家"→ 切模型时方法在 arch 段前崩, 参数区永远不动)。修复: `a.get(name) or b.get(name, fallback)` 链式, 不用 get 默认参数。
- **正则不锚定缩进**: config 里 `  lr: 1e-4` (optimizer 下缩进) 用 `^lr:` 匹配不到 → 读不到值。用 `^\s*key:`。
- 排查"功能没生效": 临时把 `except Exception: pass` 改成 `except Exception as e: print(repr(e))` 暴露被吞的异常, 定位后再还原 (比猜快)。

## 模块库全节点覆盖模式 (Simulink 式画布 + 左侧可拖库)
- **需求**: 所有模板（模型对比/VLA-Touch/AWE/总系统/CICD 等）的每个节点都要能从左侧模块库拖出，功能一致
- **盘点差集** (关键步骤): 模板节点集 vs LIBRARY 条目集取差集 → 精准补缺，不盲改
  ```python
  # REFERENCE_APPS 模板的 tpl[1](节点定义) + tpl[3](布局行) 收集节点名
  lib_names = {it["name"] for _, _, items in LIBRARY for it in items}
  missing = sorted(tpl_nodes - lib_names)   # 逐个补 LIBRARY 条目
  ```
- **分类**: 补条目按组归类（模型主干/训练/ActionHead/仿真推理视频/硬件别名…）；同构批量条目用列表推导式生成（`for m in [模型列表]`）
- **模板名 vs 库条目名不一致** → 在 LIBRARY 补"别名条目"（同功能不同名，如 H00 Orin Nano vs "Orin Nano"、"🧠 ACT 训练" vs "🚀 ACT 训练"），不改模板
- **改名/删除条目的引用完整性** (老倪铁律"注意数据源别改没了"):
  - `replace_all` 改名后必须验证: 旧名 0 残留 + 新名统一 + **模板加载正常**（load_reference_app_by_name 后数据源节点在）
  - 删条目用 patch 精确删，**删前确认**同类条目/画布数据源仍在
- **主数据注册**: LIBRARY 节点同步注册进全局数据空间（data_space.py `_scan_nodes()` — 节点即主数据，node↔主数据映射）

### 新节点类型三步注册（漏一步就 KeyError/静默缺失）
新增节点类型（如 `coord_overlay`）必须同时改 3 处，少一处就出具体故障:
1. **类型注册表**（NODE_TYPES/COLORS 映射，如 `"coord_overlay": {"cn": "坐标叠加", "color": "#58a6ff"}`）
2. **icon 字典**（`add_node` 里的 `"icon": {...}[ntype]`）→ 漏了报 **`KeyError: '<ntype>'`**（模板加载即崩，症状在 add_node 行）
3. **node_logic 注册**（`_reg("coord_overlay", [...], node_func)`）→ 漏了双击无逻辑
排查顺序: 先 grep 类型名出现在哪几个文件/字典，逐个对照；另一会话可能只加了 1、3 漏了 2。

### 模板同名节点 = 多实例（每定义一个）
- 模板加载机制: 遍历 node_specs 定义 → 每个定义按布局同名位置放一个 → **同名定义 N 次 = N 个独立节点**（各自 params 独立可改）
- 布局（tpl[3] 行网格）引用了节点名但 node_specs 无定义 → 该节点**静默缺失**（不报错）→ 用盘点差集脚本找
- 共享节点（数据源/评估）是同一个定义名出现在多行（shared 参数），区别于多定义
- **共享节点下放/移除模式 (2026-08-08 结构条件)**: 节点从公共感知链移到每模型行 (布局名加后缀如 "🧩 结构条件 · ACT") 时, **保留原共享定义不删** (定义索引=edges 引用索引, 删了全表索引 -1 大改) + **加载器守卫跳过**: 加载循环里 `if not cands and "结构条件" in nm and "·" not in nm: continue` (无布局位置且是共享定义→不创建)。edges 用定义索引引用, 行级新定义追加在 node_specs 末尾 (索引 58-62), 加载时 index→id 映射自动对应。
- 布局列距 = `base_x + c * 200` (120 起); 断言位置先算列: 列4 = 120+4*200=920, 别用 520 猜。

## 多会话协作（飞书端/其他会话改同一文件）— 对账流程
Z-MAX 有多个会话（CLI + 飞书 gateway）会改同一份本地代码，症状: 用户"飞书端说改了，我没看到"。
- **根因**: 另一会话改了本地文件但**未 git 提交 + GUI 未重启**（画布还是旧代码）
- 对账: `git status --short tools/gui/` 查未提交改动 → 检查关键注册（类型表/icon 字典/node_logic）完整性 → 补全后**重启 GUI** 才生效
- 外部会话产物（训练目录 act_peg_overlay 等）先 `ls -t outputs/train/` 确认，别动其进行中的训练

## auto_restart 守护进程（kill -9 后自动复活）
- 场景: studio.py 父进程链指向 Hermes gateway（`hermes_cli.main gateway run`）拉起的 bash 守护（`/bin/bash -lic "set +m; cd ... && python3 studio.py > /tmp/studio_restart*.log"`），检测到 GUI 退出就自动拉起
- **kill -9 GUI 后 2 秒内出现新 PID = 守护在拉**；要彻底停: 先杀守护 bash（`ps -o ppid` 沿父链找），再杀 GUI
- **pkill -f 自杀陷阱**: `pkill -f 'studio.py'` 会匹配**调用 shell 自身的命令行**（ps 参数含该字符串）→ 终端进程被自己杀掉（exit -9）。先 `pgrep -f` 列出 PID 再 `kill -9 <pid>` 逐个杀
- 多实例重复: 旧实例 + 守护拉的新实例并存 → 先全杀再手动起一个干净的（gateway 432 保持存活，别误杀）

## xdotool 窗口操作（WSLg，清理多弹窗/定位窗口）
- 装: `sudo apt-get install -y xdotool`（WSLg 可用）
- 枚举窗口: `DISPLAY=:0 xdotool search "" | while read w; do xdotool getwindowname $w; done`（找标题）
- 关多开的弹窗（2026-08-08 实测 "7 模型 rollout 对比" 开了 8 个）: 按标题匹配 `case "$t" in *"rollout 对比"*) xdotool windowkill $w;; esac`
- **盲点坐标点击不可靠**（找不到控件坐标，点导航/按钮常点空）——老倪要求"操作窗口按钮"时，优先走 GUI 内部触发（`.click()`/信号注入）或让用户点；xdotool 只用于清窗口/激活（`windowactivate`）

## GUI 行为原则
- 打开视图**永远先显示历史数据**（视频/曲线），新 checkpoint 只提示不自动重生成（白屏根治）
- 外部进程（非 GUI 启动的训练）状态监视: `pgrep -f lerobot_train` + 最新输出目录 ckpt 步数 + config steps → 显示 `训练中: <dir> · 步 N/M (P%)`；去重（状态变化才 append）；结束提示一次

## 相关
- 打包分发/Windows exe CI 见 `pyqt5-distribution`；Z-MAX 控制台项目维护见 `zmax-console`（用户技能）
- 会话案例细节: `references/session-cases.md`
