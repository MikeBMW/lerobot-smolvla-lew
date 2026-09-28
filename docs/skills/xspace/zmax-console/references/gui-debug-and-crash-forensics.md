# 控制台 (studio.py) 断点不命中 + 崩溃取证

## A. 「断点进不去」—— 三步定性, 一步一个判据 (按顺序做, 别跳)

### 1. 进程里到底有没有调试器
- 控制台窗口标题后缀 `⚠️非调试模式` = 没有。studio.py 只在 env `ZMAX_DEBUG=1` 时
  `debugpy.listen(("127.0.0.1", 5678))` (默认不 listen: 无 attach 时会阻塞 Qt 主线程 map 窗口)。
- 判据: `ss -ltnp | grep 5678` 无监听 ⇒ VSCode 里的断点只是"画"在那儿, 进程里没人去停。
- 两条路(二选一):
  · F5「🚀 全新调试进程 (studio.py)」—— debugpy 在进程内, 断点直接生效 (justMyCode 已 false);
    注意它与桌面那个实例**共用同一份画布 JSON**, 别两边同时改画布。
  · 想让**正在用的那个**实例能断: 用 `ZMAX_DEBUG=1` 起 launch_studio.sh, 再 F5「🔌 Attach 现有控制台 (5678)」。

### 2. 自己代码里的追踪器有没有把调试器顶掉 (最容易误判成"代码不执行")
- 节点"逐行执行 / 变量数值变化"链在 `lerobot/engineering/runtime.py::_trace_exec`: 它先查
  `debugpy.is_client_connected()`; 为假就 `sys.settrace(逐行 tracer)` ⇒ **覆盖 debugpy 的 tracer, 断点静默不命中**; 为真则直接调用, 把断点交还调试器。
- 判据必须在**执行过程中**读 `sys.gettrace()`: 函数 `finally: sys.settrace(None)` 会在返回前清掉,
  返回之后再读永远是 None ⇒ 只看返回值会把排查带偏。探针要在**函数体第一行**记录 `sys.gettrace()`:
  未 attach = `<tracer: tracer>`; 已 attach = None。
- 结论: attach 没成功时表现就是"断点永远进不去", 先修连接再怀疑代码。

### 3. 动态装载的模块照样能绑断点
- 按文件路径 `spec_from_file_location` + `module_from_spec` + `exec_module` 装载的模块(不走 sys.modules)
  **能**命中断点, 前提是 `os.path.realpath(文件)` 与工作区路径逐字一致 —— 先 `readlink -f` 核对路径里有没有软链成分。
- 附带好处: 这类模块**每次点击都从磁盘重新 exec** ⇒ 改它不用重启控制台, 下次点运行即生效。
- 断点只打**真源文件**: `grep -rn "class 名字" --include=*.py .` 全仓确认没有第二份副本/另一个检出。

### 4. 触发路径确认
- 节点只在 ▶运行 / 单步 / 右键运行 时执行, 且跑在 **Qt 主线程**(不是 worker 线程) ⇒ attach 后主线程断点正常命中。
- 光改文件不点运行, 永远不会经过断点 —— 这不是断点的问题。
- 源码视图/位置类疑难: 节点"双击看源码"的行号来自注册表里的 `_EXTERNAL_LOC`(外部实现文件的符号行),
  与实际行号会差几行(分隔注释等) ⇒ 看着像"文件不对"时先 `grep -n "^class 名字"` 核对真行号。

## B. 崩溃(窗口消失 / Aborted)取证清单

现场在 `/tmp/studio_launch.log` 尾部: `QThread: Destroyed while thread is still running` +
`Fatal Python error: Aborted` + faulthandler 的全线程栈; 主线程 `<no Python frame>` = 崩在 Qt C++ 侧。

逐条排除(先排除再定性, 不要跳过):
1. 不是被 kill/正常退出: `grep -c "收到信号" /tmp/studio_launch.log` = 0 ⇒ 无信号也出现同一签名,
   别默认归因关机/kill(那条只覆盖 kill 路径)。
2. `Unknown property cursor` 是新窗口/对话框的样式表警告, 一份日志里几百行属日常噪音, 不是崩溃信号。
3. 谁把窗口拉回来的: `tr '\0' '\n' < /proc/<pid>/environ | grep GIO_LAUNCHED_DESKTOP_FILE` ——
   是桌面图标 = **用户自己点回来的**, 不是自愈。
4. 别指望自愈: `systemctl --user status zmax-studio.service`(Restart=no, 且 ExecStart 可能仍指向旧共享检出);
   `tools/gui/studio_watch.sh` 是 docker 时代的 gdb 看门狗(本机不跑); `/tmp/studio_ctl.log` 只记 studio_ctl.sh 的动作。
5. QThread 自查: `grep -n "Worker(" tools/gui/studio.py` —— 实例没挂到 `self._workers`(或 self 属性)上的,
   就是 `Destroyed while thread is still running` 的候选(仓库里已有"QThread 永不 GC"的历史修复注释)。

归因缺口(要如实讲): dump 只有各线程**当前**状态, **不记录是哪个点击/命令触发** ⇒ 不能说"崩溃前点过 X 所以是 X"。
要对下一次归因, 加崩溃记录器: 启动即 `faulthandler` 全栈落盘 + 最近 N 条界面操作/命令通道事件写
`~/zmax_data/studio_crash_<时间>.log`。

排除无关项: 网页/推流由 `cam_live_stream.py` 独立进程提供, 控制台只是开浏览器指向它 ⇒
控制台崩溃与"页面改动"无关, 用进程边界说清, 别让用户以为改页面把控制台搞崩了。
