# Xvfb 显示栈 + 崩溃守护 + 视频线程修复 (2026-08-19 实测)

## 1. Xvfb 必须挂 openbox (窗口无标题栏/关闭按钮)
- Xvfb 是裸 X server **无窗口管理器** → 所有窗口没有标题栏/装饰 → **没有关闭按钮**
  (用户报"视频窗口没有关闭按钮, 关闭不了")。
- 修复: `apt-get install -y openbox` + `DISPLAY=:99 openbox &`。
- **openbox 启动后现有窗口不会被 reparent** — 必须先起 openbox 再启动 studio,
  或起 openbox 后重启 studio 才有装饰。
- 验证: `xwininfo -root -tree -display :99` 出现带标题的 frame 窗口
  (客户区位置 +1+20 偏移 = 有标题栏)。

## 2. 崩溃归属修正: Xvfb 上也崩 → 不能全怪 VcXsrv
- 2026-08-19 当日: VcXsrv 通道崩 2 次 (killTimer 跨线程), 切 Xvfb 后**也崩** —
  同样是 `QObject::killTimer: Timers cannot be stopped from another thread`。
- 结论: 代码层仍有漏网的子线程 QTimer/信号路径, VcXsrv 只是放大了频率。
- 静态审查 4 层修复都在 (_tq PreciseTimer+parent / _oneshot 桥 / worker append 防 GC /
  WS 线程零 Qt) → 剩余是偶发竞态, 靠 watchdog 自动恢复兜底 + faulthandler 攒规律。

## 3. MLPRolloutDialog 抽帧线程悬垂信号 (视频窗口崩溃修复)
- 症状: 用户开视频窗口 → 播放 → 关闭 → 之后崩溃 (killTimer/SIGSEGV)。
- 根因: `_frames_ready = pyqtSignal(str)` 类属性信号, 抽帧线程 (threading.Thread
  daemon, ffmpeg 120s 超时窗口) 完成后 `self._frames_ready.emit()` —
  **窗口已关闭销毁时 emit 到悬垂 QObject → 崩溃**。
- 修复 (双重保护):
  ```python
  def _work():
      from PyQt5 import sip
      ... ffmpeg 抽帧 ...
      if sip.isdeleted(self) or getattr(self, "_closed", False): return
      self._frames_ready.emit(...)
  ```
  - `__init__` 加 `self._closed = False`
  - `closeEvent` 置 `self._closed = True` + stop timer
  - 异常分支的 emit 同样包 isdeleted 检查
- 通用教训: **任何子线程回调 (信号/单次 timer) 访问可能已关闭的对话框,
  必须先 sip.isdeleted 检查** (不只在主窗口侧查 _mlp_dlg, 线程内部也要查)。

## 4. watchdog 守护 + 双实例竞争
- 守护脚本 (~/.hermes/scripts/watchdog_studio.sh): 每 8s pgrep studio, 崩了
  `setsid env DISPLAY=:99 nice -n 10 ... studio.py &` 拉起, 日志 /tmp/studio_watchdog.log,
  崩溃栈 /tmp/studio_run.log。
- ⚠️ **有守护时不要手动再拉起实例** (实测踩坑): 手动拉起与守护拉起的实例撞车 →
  双实例 8 窗口重叠。要手动操作必须先停守护 (process kill watchdog)。
- 守护拉起的实例不在 Hermes 管理下 (无 watch), 靠守护日志判断。
- pkill -f "studio.py" 会误杀 Hermes 包装 bash (命令行含同串) → 用精确 kill PID。

## 5. 训练开关 (train_gate) 静默拦训练 (用户"点运行+训练怎么不训练")
- 根因: 画布「☑ 训练开关」节点默认没打勾 → on_train 入口 `_train_gate_state()`
  为 False → **静默跳过训练** (日志面板一行小字, 用户看不到)。
- 修复: 用户主动双击数据源运行 (on_run_env) 时传 `_from_run=True` → on_train 里
  开关关时**自动打开全部 train_gate 并继续训练**, 日志明确提示
  "⚡ 训练开关未打勾 → 主动运行已自动开启全部训练开关, 强制训练";
  整画布跑流程 (非主动运行) 时开关语义不变。
- 教训: 用户主动动作 (点运行) = 明确意图, 不应被画布编排开关静默拦截;
  跳过原因必须醒目输出。

## 6. GUI 日志不在 Hermes process log
- GUI 的 _log/log_signal 打到控制台日志面板, 不一定进 stdout →
  查"用户点了 X 为什么没反应"时, Hermes process log 看不到 GUI 日志是正常的,
  要看日志面板内容或 log_signal 的目标。
