# Qt 桌面程序"硬崩"取证手册 — 先分类, 再上 gdb (2026-09-18 实测)

补充 SKILL.md「坑 0」: 硬崩有两族, 解法完全不同, **先用一条日志行区分**。

| 症状 | 日志特征 | 类别 | 解法 |
|---|---|---|---|
| 点一下就整个进程消失, 无弹窗 | `Fatal Python error: Aborted` + **Python traceback** (栈顶在槽 / `paint()`) | Qt 槽内**未捕获 Python 异常** → PyQt5 qFatal | 槽体/函数入口 `try/except` 兜底 + 类型归一 (见坑 0) |
| 用着用着 (~40-90s) 消失 | 只有线程转储, **无 traceback**; systemd `status=11/SEGV` | **原生段错误** (C/C++ 侧) | 开 core dump + gdb 看栈顶库 (本文件) |
| 日志刷 `Cannot queue arguments of type 'QTextCursor'` | 之后常接上面第二行 | **后台线程操作 Qt 文本控件** | 在写日志的唯一出口做线程收口 (见下) |

⚠️ `systemctl status` 可能报 `code=exited, status=0/SUCCESS` (先 closeEvent 收尾、再在析构里 abort) ——
**以 `Fatal Python error:` 行为准**, 别被 exit code 骗。

## 开 core + gdb (systemd 用户服务默认 `LimitCORE=0` = 现场白丢)

```bash
mkdir -p ~/.config/systemd/user/<svc>.service.d
printf '[Service]\nLimitCORE=infinity\n' > ~/.config/systemd/user/<svc>.service.d/core.conf
sudo sysctl -w kernel.core_pattern=/tmp/core.%e.%p
systemctl --user daemon-reload && systemctl --user restart <svc>
# 崩了之后 (core 名里 %e=可执行名, %p=pid)
ls -lt /tmp/core.*
gdb -q -batch -ex "set pagination off" -ex "bt 40" <venv>/bin/python /tmp/core.python.<pid>
```
要点: gdb 的第一个参数**必须就是崩的那个解释器** (venv 里的 python, 不是系统 python), 否则符号对不上;
`.gnu_debugaltlink` / `libthread_db` 之类 warning 可忽略。

## 实例: 跨线程写日志框 → 字体整形段错误

真实栈 (截取):
```
#0 __pthread_kill_implementation (no_tid=0, signo=11, ...)
#4 faulthandler_fatal_error ()                 ← faulthandler 收到 SIGSEGV 后重发信号以落 core
#6 QFontEngineFT::recalcAdvances(...) const    (libQt5XcbQpa.so.5)
#7 _hb_qt_font_get_glyph_h_advance (...)        (libQt5Gui.so.5 / HarfBuzz 回调)
#12 QTextEngine::shapeTextWithHarfbuzzNG(...)
#17 QTextLine::draw(...)
#24 QTextEditPrivate::paint(QPainter*, QPaintEvent*)
Current thread ... studio.py, line 12125 in main   ← 主线程正在跑事件循环
```
读法: 崩在 **QTextEdit 重绘时的字体整形**。不是字体文件坏了, 是该控件的文本引擎被**别的线程**动过
(前一行日志就是那条 `QTextCursor` 告警) → 下次 shaping 踩坏状态。
修法 = 在日志的唯一出口做线程收口:
```python
def _log(self, msg):
    ...                                        # 文件留档: 与 GUI 无关, 两条路都写
    import threading as _th
    if _th.current_thread() is not _th.main_thread():
        from PyQt5.QtCore import QMetaObject, Qt, Q_ARG
        QMetaObject.invokeMethod(self.log_box, "append", Qt.QueuedConnection, Q_ARG(str, msg))
        return
    self.log_box.append(msg)
```
- 只改一处 → 所有调用方 (含各模块后台线程) 自动安全 (收口原则在 GUI 侧同样适用)。
- 主窗 `studio.py:_log` 早就是线程安全的 (非主线程 → 队列 + 200ms QTimer flush), 可作参考实现;
  模块内单行 append 用 `invokeMethod(..., QueuedConnection)` 已实测可用。
- **验证方式**: 修完重启, `journalctl --user -u <svc> --since "-5min" | grep -c "QTextCursor"` 应为 0,
  且存活时间超过历史崩溃点 (本机原先 40-90s 必崩)。

## 同批修掉的两个图片链路隐患 (会伪装成"崩溃/没图")

1. **写图非原子**: `open(path,"wb").write(buf)` = 先截断再写 → 10Hz 轮询的读者可能拿到**半张 PNG**。
   改 `写 tmp + f.flush() + os.fsync + os.replace(tmp, path)` (同目录同文件系统 → 读者永远见完整帧)。
2. **读图别把坏数据交给 Qt**: 先整块读入内存, 再 `cv2.imdecode(buf, cv2.IMREAD_COLOR)`;
   **cv2 可用时它就是权威** —— 解不出 (含截断 buffer) 直接返回 None, **不要**再 fallback 到
   `QtGui.QPixmap(path)`: 截断 buffer 会走 Qt 解码路径, 无 QApplication 的环境直接
   `QPixmap: Must construct a QGuiApplication` → SIGABRT; 有 QApplication 也只是白解坏数据。
   阴性对照 (实测): 真帧 → (480,640,3); 截断 / 空 / 缺失 → 一律 None, 不抛异常。
