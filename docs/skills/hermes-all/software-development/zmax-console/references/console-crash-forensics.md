# 控制台崩溃取证与跨线程纪律 (2026-09-18 实测, 全部来自 core dump / 日志实证)

三连崩三个不同根因, 按"能不能一分钟区分"排列 —— 先分类, 别猜。

## 0. 一分钟分类

| 症状 | 日志特征 | 根因类别 | 去哪找 |
|---|---|---|---|
| 点一下就整个进程消失, 无弹窗 | `Fatal Python error: Aborted` + **Python traceback** (栈顶在某个 Qt 槽/`paint()`) | Qt 槽/绘制路径里**未捕获的 Python 异常** → PyQt5 qFatal → SIGABRT | traceback 直接给出文件和行号 |
| 用着用着(~40-90s)进程消失, 无弹窗 | 只有线程转储, **没有 traceback**, systemd 报 `status=11/SEGV` | **原生段错误** (C/C++ 侧) | core dump + gdb, 看栈顶的库 |
| 日志里刷 `Cannot queue arguments of type 'QTextCursor'` | 之后常伴随上面第 2 类 | **后台线程操作 Qt 文本控件** (文本引擎被污染 → 下次重绘段错误) | 搜 `threading.Thread` + 谁的 `_log` / `QTextEdit.append` 没设防 |

命令:
```
journalctl --user -u <svc> --since "…" --no-pager | grep -viE "Unknown property cursor|Debugger warning|frozen modules"
systemctl --user status <svc> --no-pager | head -12      # Active / code=dumped / status=11/SEGV
```
`code=exited, status=0/SUCCESS` 也可能是"先 closeEvent 收尾、再在析构里 abort", 别被 exit code 骗了 —— 以 `Fatal Python error:` 行为准。

## 1. 槽内未捕获异常 (本会话实例: 模式下拉 → "local")

```
Traceback (most recent call last):
  File "tools/gui/studio.py", line 7321, in _on_mode_changed
    self._populate_nodes(Z700_ROS2_NODES[modes[idx]])
KeyError: 'local'
Fatal Python error: Aborted
```
`modes = ["sim","local","real"]` 而 `Z700_ROS2_NODES` 只有 `sim` / `real` 两个键 → 下拉第 2 项直接打死整个控制台。
**通用修法**: 槽体整体 `try/except` 兜底 (异常只记日志, 绝不冒泡) + 未知/越界键退回安全默认值 + 如实打一行日志。
同类历史: 2026-09-14 `Z700_ROS2_NODES["real"]` 被当 dict 调 `.get()` (它是 list) → AttributeError → 同样整进程中止。

## 2. 原生 SIGSEGV: 先开 core, 再 gdb

systemd 用户服务默认 `LimitCORE=0` = 什么都不留 → 崩溃现场白丢。一次性打开:
```bash
mkdir -p ~/.config/systemd/user/<svc>.service.d
cat > ~/.config/systemd/user/<svc>.service.d/core.conf <<'EOF'
[Service]
LimitCORE=infinity
EOF
sudo sysctl -w kernel.core_pattern=/tmp/core.%e.%p
systemctl --user daemon-reload      # 下次启动生效
```
崩了之后 (core 文件名里的 `%e` = 可执行名, `%p` = pid):
```bash
ls -lt /tmp/core.*
gdb -q -batch -ex "set pagination off" -ex "bt 40" \
    /home/ubuntu/lerobot-smolvla-lew/gui-venv311/bin/python /tmp/core.python.<pid>
```
⚠️ gdb 的第一个参数必须**就是那个解释器** (venv 里的 python, 不是系统 python), 否则符号对不上。
缺 `.gnu_debugaltlink` 之类的 warning 可以忽略。

### 本会话真实栈 (跨线程写日志框)
```
#0 __pthread_kill_implementation (no_tid=0, signo=11, ...)
#4 faulthandler_fatal_error ()              ← faulthandler 收到段错误后重发信号以落 core
#6 QFontEngineFT::recalcAdvances(...) const  (libQt5XcbQpa.so.5)
#7 _hb_qt_font_get_glyph_h_advance (...)     (libQt5Gui.so.5, HarfBuzz 回调)
#12 QTextEngine::shapeTextWithHarfbuzzNG(...)
#17 QTextLine::draw(...)
#24 QTextEditPrivate::paint(QPainter*, QPaintEvent*)
#33 sipQApplication::notify(...)
Current thread ... File "tools/gui/studio.py", line 12125 in main   (主线程正在跑事件循环)
```
读法: **崩在 QTextEdit 重绘时的字体整形**。这不是"字体坏了", 而是该 `QTextEdit` 的文本引擎被**别的线程**动过
(日志前一行就是 `Cannot queue arguments of type 'QTextCursor'`), 于是下次 shaping 踩到坏状态。
→ 顺着告警去找"谁在后台线程 append 到文本控件"。

## 3. 修法: 在**写日志的唯一出口**收口 (不要每个调用方各写一套)

```python
def _log(self, msg):                                   # SimulinkModule._log
    # ① 文件留档与 GUI 无关, 两条路都写
    try:
        with open("/tmp/simulink_log.txt", "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass
    # ② 非主线程 → 排队回主线程再 append (禁止跨线程碰 QTextEdit)
    import threading as _th
    if _th.current_thread() is not _th.main_thread():
        from PyQt5.QtCore import QMetaObject, Qt, Q_ARG
        QMetaObject.invokeMethod(self.log_box, "append", Qt.QueuedConnection, Q_ARG(str, msg))
        return
    self.log_box.append(msg)
    self.log_box.verticalScrollBar().setValue(self.log_box.verticalScrollBar().maximum())
```
要点:
- 只改 `_log` 一处, 所有调用方 (含各模块后台线程) 自动变安全 —— 老倪的"收口"原则在 GUI 侧同样适用。
- 主窗 `studio.py:_log` 早就是线程安全的 (非主线程 → 队列 + 200ms QTimer flush), 可作为参考实现。
- `QTimer.singleShot` / `invokeMethod` 的跨线程语义在 PyQt5 下有丢消息的历史坑, 故主窗用轮询队列;
  模块内的单行 append 用 `invokeMethod(..., QueuedConnection)` 已实测可用。

## 4. 附带修掉的两个"图片链路"隐患 (同一批改动)

- **写图非原子** (`open(path,"wb").write(png)`) → 读者拿到**半张 PNG**。
  改 `写 tmp + os.fsync + os.replace` (同目录同文件系统, 读者永远看到完整帧)。
- **读图不能把坏数据交给 Qt**: 先整块读入内存 → `cv2.imdecode(..., IMREAD_COLOR)`;
  **cv2 可用时它就是权威** (解不出 = 这帧不可用 → 返回 None), 不要再 fallback 到
  `QtGui.QPixmap(path)` —— 截断 buffer 会走 Qt 解码路径, 无 QApplication 的环境直接
  `QPixmap: Must construct a QGuiApplication` → SIGABRT; 有 QApplication 也只是白解坏数据。
  阴性对照 (实测): 真帧可解 → (480,640,3); 截断/空/缺失 → 一律 None, 不抛。
