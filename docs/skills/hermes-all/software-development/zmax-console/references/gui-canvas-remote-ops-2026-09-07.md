# GUI 远程操作实战 (2026-09-07 晚, studio.py v5.0.0 画布操作)

承接 nav-cmd-file-trigger-2026-09-07.md。老倪远程指挥时看着屏幕,
要求"操作画布"→ 打开状态空间 → 看原子技能层 → 运行。本文件 = 那轮实战的
补充技能: 命令通道扩 ss_run + 画布平移手法 + 重启双实例坑 + 窗口遮挡处理。

## 1. 命令文件触发扩 ss_run (▶ 运行状态空间仿真)
studio.py `_poll_nav_cmd` 增加分支 + 新方法 (v5.0.0+):
```python
elif line == "ss_run":
    _oneshot(self, 300, self._run_ss_cmd)
...
def _run_ss_cmd(self):
    if getattr(self, "simulink", None) is not None:
        self.simulink.start_sim()
        self.statusBar().showMessage("▶ 状态空间仿真已启动 (命令触发)", 2000)
```
用法: `echo ss_run > /tmp/zmax_nav_cmd`。注意 start_sim 是画布当前 flow 的
▶运行 (状态空间画布 = RealStateSpaceSim / 普通画布 = 拓扑仿真), 触发前需先
ss_canvas 确保画布已加载, 且 simulink 初始化完成 (~4s, 看 /tmp/zmax_simulink_init.log
的 "post-_build" 时间戳)。

## 2. 画布平移 = 鼠标中键拖拽 (不是左键!)
SimCanvas(QGraphicsView) mousePressEvent: `Qt.MiddleButton` → `_panning=True`
(setCursor ClosedHandCursor), mouseMove 平移场景。**左键 = 选中/连线/拖动节点,
不是平移** — 用左键"拖画布"会误选节点或没反应 (老倪: "拖的不是画布")。
- 中键拖拽 = 场景跟手: 想看到**下方/右侧**内容 → 鼠标向**上/左**拖 (场景随鼠标动)。
  实操: 向右看 → `xdotool mousedown 2` + 多次 `mousemove_relative -- -120 0`
  (向左移 = 内容向右), 每步 sleep 0.1s, 再 mouseup 2。
- **必须慢速分步**: 一次大幅 mousemove_relative 后 Qt 可能不识别为拖拽 (0% 变化);
  分 6-14 步、每步 <150px、步间 sleep 0.1-0.15s 才可靠。
- 画布垂直滚动: 滚轮/Page_Down 走 QScrollBar (有滚动条时); 无滚动条或到底后用中键。
- 画布很大时 (状态空间 51 节点含 4+ row_bg 行), 原子技能层在底部行 — 先
  Page_Down/中键下拖几次, 再中键左右拖找「🧩 原子技能层」SK01-08 节点行。

## 3. ⚠️ 重启 GUI 双实例坑 (老倪: "状态空间怎么没了")
restart_gui.sh 里 `pgrep -f 'gui-venv311/bin/python studio.py'` 可能**只杀到一个**,
旧实例 (如 21:41 起的 PID 56027) 若没死透, 会跟新实例 (22:37 的 62475) 抢 X:
- 症状: 用户看到旧窗口 (旧代码/旧画布), 命令通道写新实例也"没反应" (写给了 62475,
  但屏幕显示 56027 的窗口); 或窗口标题带 [画布] 但内容区是旧的。
- **判定**: `ps aux | grep '[s]tudio.py'` 数进程 — >1 就是双实例;
  `xdotool search --name "XSpace Studio"` + `xdotool getwindowpid <wid>` 逐个对 PID,
  找到旧窗口的 wid 再精确 `kill <oldpid>`。
- **防再犯**: 重启脚本杀进程后必须 `sleep 3` + 复查 `pgrep -f ... | wc -l` 归 0 才启动新实例;
  汇报时给 新 PID + 启动时间 + `xdotool getwindowpid` 映射, 别只说"已重启"。

## 4. 窗口被遮挡 / 不在前台 (Chromium/日历等盖住画布)
- 症状: 截图分析"中央大片黑"或内容区亮度极低 — 先列窗口:
  `xdotool search --onlyvisible --name '.*'` + getwindowname/getwindowgeometry,
  常是 Chromium (千问) 全屏窗口盖在 GUI 上。
- **置顶**: `xdotool windowactivate <wid>` 可能报
  `XGetWindowProperty[_NET_WM_DESKTOP] failed` (Mutter 老问题) → 用 **wmctrl**:
  `DISPLAY=:0 wmctrl -i -a <decimal wid>` (先 `printf '%d' 0x<hex>` 转十进制,
  或 xdotool 直接给十进制)。wmctrl 比 xdotool activate 可靠。
- 前台确认: `xdotool getactivewindow getwindowname` 应返回 XSpace Studio 标题。
- 遮挡物是系统弹窗 (日历/update-notifier) 且不需要 → 关掉再继续。

## 5. 状态空间画布加载成功判据
- 窗口标题带 `- [画布]` 后缀 = 画布模式激活 (open_state_space 是 load_flow_file
  到 SimulinkModule 自身, **不是新窗口**)。
- 内容区彩色节点占比 2-3%+ = 节点渲染了 (深色主题节点小, 别拿亮块占比当判据)。
- simulink init log `/tmp/zmax_simulink_init.log` 尾部应见 "post-_build"。

## 相关
- zmax-console SKILL.md § 状态空间画布 / simulink_flow_and_buttons
- references/nav-cmd-file-trigger-2026-09-07.md (ss_run 分支已并入该命令通道)
