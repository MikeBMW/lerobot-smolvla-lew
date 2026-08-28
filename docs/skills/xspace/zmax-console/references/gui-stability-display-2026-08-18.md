# GUI 稳定性与显示规范补充 (2026-08-18 晚, 状态空间操作视频/波形迭代实测)

> 本文件记录与 gui-crash-pitfalls.md / gui-discipline.md 同域的增量坑, 待 curator 合并。

## 1. 启动解释器版本 = 崩溃根治前提 (最重要)

**必须用 /root/gui-venv311/bin/python (Python 3.11)**。
误用 /root/gui-venv (Python 3.12 + sip 6.16) 时, 即使线程纪律全遵守, 点「运行」→
仿真完成 → 后台渲染线程启动后仍崩:
```
QObject::killTimer: Timers cannot be stopped from another thread
QObject::~QObject: Timers cannot be stopped from another thread
Fatal Python error: Segmentation fault
#0 QCoreApplication::notifyInternal2   ← SIGSEGV
#1 QTimerInfoList::activateTimers()    ← timer 批次撞 NULL receiver
```
gdb 栈定位 activateTimers = NULL receiver 竞态。3.12+sip6.16 是已知不稳组合,
3.11 根治 (PyQt5 5.15.10 + Qt 5.15.2)。启动前核对:
```bash
/root/gui-venv311/bin/python -c "import sys; assert sys.version_info[:2]==(3,11), sys.version"
```

## 2. gdb 抓崩溃栈 (免交互)

```bash
gdb -batch -ex "set pagination off" -ex "handle SIGSEGV stop print" \
  -ex run -ex "bt 30" -ex "info threads" \
  --args /root/gui-venv311/bin/python studio.py > /tmp/gdb_crash.log 2>&1
```
崩溃自动 dump C 栈; Python 栈看 stderr "Fatal Python error" 段 (Current thread + File/line)。
用户复现一次即可, 不用反复试。

## 3. 操作视频 rot180 伪装副本

「发送_MLP插拔成功.mp4」文件名不含 rot, 但字节数与 mlp_insert_success_rot180.mp4
完全相同 (318957) = rot180 变体复制改名。只按文件名排除会漏 → 播放时 HUD 文字倒 +
画面反。**排除必须按字节比对去重 (md5/文件大小), 不能只信文件名**。
默认不旋转 (正版 HUD/画面同向); 播放器留「转正 180°」按钮手动调。

## 4. VcXsrv 下 emoji = ?? / □

wqy 字体无 emoji 字形 → 窗口标题栏/按钮/QLabel 的 🎥📊⏳⏸⏮⏭🔄 渲染成 ??/□。
修复: 弹窗标题、按钮文字、提示 QLabel 一律纯文字 (禁 emoji); 画布节点名可留 emoji。

## 5. 弹窗规范 (用户要求: 大 + 可调 + 详细)

- 画布节点标准 150x50, 双击弹独立大窗口
- 弹窗: resize(1280, 820) + setMinimumSize(1024, 700) + setSizeGripEnabled(True)
  + setWindowFlags(| Qt.WindowMaximizeButtonHint)
- QLabel 存原始 pixmap, resizeEvent 里重新 scaled (KeepAspectRatio) — resize 不卡
- 曲线 QPainterPath 批量画 (500点 path <5ms vs 逐点 drawLine 2000 次卡顿);
  线宽 2.5 + 标题字号 14
- 图表必须有横轴标注 (右下角 "t (s)") + 纵轴单位 (标题内, 如 "距离孔位 (m)")
