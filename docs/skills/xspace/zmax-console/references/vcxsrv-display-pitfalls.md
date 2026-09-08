# VcXsrv 显示栈坑族 (2026-08-12 实战, 老倪控制台)

## 1. QMenu 深色 QSS → 黑屏无字 (最典型)
- **现象**: 右键菜单弹出来是黑块/黑屏, 或"有的白底有的黑条", 或菜单项变黑块
- **根因**: VcXsrv(Windows X 服务器)对 QMenu 的 QSS 渲染失败:
  a. 局部菜单 QSS(menu.setStyleSheet) → 整菜单黑屏
  b. **全局 QSS**(app.setStyleSheet 里的 QMenu/QMenu::item 规则)对**所有**菜单生效, 只删局部没用
  c. 菜单项文本带 emoji(📖⚙️📂▶) → 缺字形渲染成黑方块
- **修法**: 局部+全局 QMenu QSS 全删(用系统默认菜单), 菜单项去 emoji 用纯文字
- **查残留**: `grep -n "QMenu {" studio.py simulink_module.py` 必须零命中(注释除外)
- 注意: QMenuBar(菜单栏)样式可保留, 黑屏的是弹出 QMenu

## 2. QGraphicsItem hover 事件在 VcXsrv 下不触发/迟钝
- **现象**: 悬停显示的内容(如节点 ID)要么"点击一下才显示", 要么"头几次显示后失灵", 要么"不消失"
- **根因链**:
  a. SimNodeItem 类**默认没有 hover 机制** —— setAcceptHoverEvents 只在 SimLinkItem(连线类)里! 节点类要自己补
  b. SimCanvas(QGraphicsView)必须 `setMouseTracking(True)`, 否则无按键时 mouseMove 不分发
  c. 即使都开了, VcXsrv 网络 X 的鼠标事件流不可靠 → 漏更新
- **修法(三层)**:
  1. 节点类补 hover: `setAcceptHoverEvents(True)` + `_hover=False` + hoverEnterEvent/hoverLeaveEvent(设 _hover + update)
  2. view 开 `setMouseTracking(True)`
  3. **mouseMoveEvent 里 itemAt 直接驱动**(不依赖 hover 事件流): 移入设 _hover=True+update, 移出清除
  4. 兜底: QTimer 150ms 轮询 QCursor.pos()(鼠标不动跳过防狂闪; isVisible/underMouse 检查; parent=self 防关闭崩溃)
- **崩溃陷阱**: hover_items 集合引用已删除的 item 会崩 → 清除时检查 `it.scene() is not None`

## 3. VcXsrv 崩溃 = "狂闪+闪退" 的真相
- **现象**: 屏幕狂闪几下 → GUI 闪退
- **根因**: 不是代码 bug! VcXsrv 进程挂掉 → display 连接断开 → Qt 启动/运行时报
  `qt.qpa.xcb: could not connect to display` → exit 134
- **诊断**: `tasklist.exe | grep vcxsrv` + `echo > /dev/tcp/172.18.80.1/6000`
- **重启**: `powershell.exe Start-Process 'C:\Program Files\VcXsrv\vcxsrv.exe' -ArgumentList ':0','-ac','-multiwindow','-clipboard','-wgl'`
  - ⚠️ 参数必须带 `-wgl`; `-softgl`/`-nowgl` 不被支持 → 进程起来但内存 13MB 端口不通
- **守护**: ~/scripts/vcxsrv_watch.sh + cron `*/2 * * * *`(查 6000 端口, 挂了自动拉起, 日志 /tmp/vcxsrv_watch.log)

## 4. WSLg 备选(不推荐当前用)
- 需 `wsl --shutdown` 重启 WSL 才启用图形栈(weston/Xwayland 进程), 会中断所有会话
- 启用后 xdotool 无效, 窗口坐标曾飞到屏幕外(需 studio.py 强制进屏幕逻辑)
- 检测: `ps aux | grep -iE "weston|Xwayland"` + `/tmp/.X11-unix/X0` socket

## 5. explorer.exe 从 WSL 启动静默失败
- **现象**: 打开视频/文件没反应(rc=0 但无窗口)
- **根因**: WSL 启动时 cwd 是 UNC 路径(\\wsl.localhost\...), 和 cmd start 同样问题
- **修法**: 统一 `cmd.exe /c start "" "C:\path\file.mp4"` + `cwd="/mnt/c/Windows"`(记忆铁律)
  - explorer.exe 仅用于打开**目录**(资源管理器, 已验证链路)
- **验证**: `cd /mnt/c/Windows && cmd.exe /c start "" "C:\...mp4"` → rc=0 无输出 = 成功弹播放器

## 6. 启动闪烁 + 卡死几秒
- **现象**: 窗口出现前屏幕使劲闪 + 卡几秒
- **修法**: 重量级组件延迟初始化 —— 主窗口构造期不建 SimulinkModule(200+ 模块/画布),
  `QTimer.singleShot(400, self._init_simulink)`, 创建后 `stack.insertWidget(原index, sim)` 保 tab 位
  → 启动 27s → 8s
- **反模式**: `win.show()` 后再 hide + 80ms 再 show 会**加重**闪烁, 别用

## 7. 多实例残留(用户:"你怎么打开两个控制台")
- `pgrep -f "python3 studio.py"` 会匹配 hermes 的 bash 包装 shell → 数不准
- **准确计数**: `ps aux | grep "python3 studio.py" | grep -v grep | grep -v bash`
- `pkill -f "studio.py"` 会匹配**命令自身**(-9 自杀) → 分步: 先 pgrep 再 xargs kill, 或 ps 管道过滤
- 清窗口: `xdotool search --name "XSpace Studio" | xargs xdotool windowkill`

## 8. xdotool 在 VcXsrv 重启后枚举异常
- 窗口实际显示正常, 但 xdotool search 返回 0
- **可靠确认**: `powershell.exe Get-Process | Where MainWindowTitle -match 'XSpace'`
  (vcxsrv 进程持有 MainWindowTitle = 窗口可见)

## 9. node_logic.py 注册模式(每个节点都要有代码)
- 用户要求: 画布每个节点「查看/编辑节点逻辑」都必须有实际代码
- `_reg(key, matches, doc, fn)` 注册; 新函数体第一行必须 `log = ctx["log"]`(否则 NameError,
  现有函数的标准模式; 勿在 docstring 里用 log)
- `_EXTERNAL_LOC[key] = (路径, 行号, "class/def 符号名")` —— sym 必须是**真实符号名**,
  且不要多个节点误指同一符号(State Adapter 曾误指 YoloStateAligner → 与 YOLO 3D 显示相同, 用户指出)
- 数据流节点(State Adapter/obs)无独立实现 → 不挂外部映射, 显示自身函数(可编辑区)
- 验证: `node_logic.match_node(name)` + `execute_node_logic(FakeMod(), ...)`(FakeMod 要 _log + __getattr__ 兜底)

## 10. 节点 ID 显示规范(老倪 2026-08-12 定稿)
- simulink 画布节点 ID = **VEH.5.顺序号**(加载后按 y→x 布局排序 001-020, `_assign_veh5_ids`),
  不是模块库跳跃编号(LIBRARY_SEQ 全局编号+同名覆盖 → 编号跳跃, 勿用)
- 显示时机: **悬停显示**, 常显被否; 移开即消失
- 颜色: **白色** #e6edf3(蓝色被否); 位置: **右下角**(右上角/上方/底部都试过被否, 会和标题/desc 重叠)
- row_bg 背景行不显示 ID
