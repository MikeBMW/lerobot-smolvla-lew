# PyQt5 NULL receiver 终局: Qt 库降级 + 守护脚本 + 画布视频降帧 (2026-08-18 第五轮)

配合 `pyqt5-null-receiver-glib-terminal-fixes.md` 使用。QT_NO_GLIB 后仍崩 (存活 241s→172s),
最后手段与配套工程。

## Qt C++ 库降级 (pyqt5-qt5 5.15.19 → 5.15.2) — 根治尝试
- 理由: gdb 栈证明宿主 = Qt 5.15.14 的 glib timer 批处理 (NULL receiver), 该 bug 是较新 Qt5
  版本的回归; 5.15.2 (2020 稳定版) 久经考验
- 命令 (pip 缺失时用 uv):
  ```bash
  uv pip install --python /root/gui-venv/bin/python "PyQt5-Qt5==5.15.2"
  # 输出: - pyqt5-qt5==5.15.19 → + pyqt5-qt5==5.15.2
  ```
- **⚠️ 版本验证必须用运行时 qVersion()**:
  ```python
  from PyQt5.QtCore import qVersion   # 运行时库版本: 5.15.2
  from PyQt5.QtCore import QT_VERSION_STR   # 编译时版本: 仍 5.15.14 — 误导, 别用
  ```
- 降级后启动验证: `qVersion()` 5.15.2 + SimulinkModule 加载 OK + 窗口出现

## 守护脚本 studio_watch.sh (崩溃自愈 + gdb 留证)
用户"总崩溃没法干活"时的兜底: 崩溃自动重启, 5s 内恢复, 用户无感。
```bash
#!/bin/bash
cd <gui_dir> || exit 1
export DISPLAY=host.docker.internal:0
N=0
while true; do
  N=$((N + 1))
  echo "[$(date '+%F %T')] 第 ${N} 次启动 studio (gdb 监控)" >> /tmp/studio_watch.log
  gdb -batch -x /tmp/gdb_cmds2.txt --args <venv>/bin/python studio.py >> /tmp/gdb_studio.log 2>&1
  RC=$?
  if [ "$RC" -eq 0 ]; then   # 正常退出 (用户关窗口) → 守护结束
    echo "[$(date '+%F %T')] 正常退出 (rc=0) — 守护结束" >> /tmp/studio_watch.log
    break
  fi
  echo "[$(date '+%F %T')] 崩溃 (rc=$RC) — 5s 后自动重启" >> /tmp/studio_watch.log
  sleep 5
done
```
- 启动: `terminal(background=true)` 跑脚本; 验证: `pgrep -f "gdb -batch"` + xwininfo
- 杀守护: 先 kill session, 再 `pkill -f "gdb -batch"` (残留 gdb 才杀)

## 画布内嵌视频 = VcXsrv 狂闪 → 降帧
- 症状: 画布内嵌视频 (item.update() 每 66ms) → 用户"狂闪, 没法干活"
- 根因: VcXsrv 无硬件加速, QGraphicsItem update() 每帧全量上传 340×260 区域 → 带宽/渲染扛不住
- 修复: 播放 timer 66ms → **150ms (~6.6fps)**, 动作可辨但不闪
- 排查顺序: 用户报"狂闪"先想高频重绘源 (视频轮播/仿真播放/高亮动画), 别先怀疑 X server

## 崩溃排查的工程纪律 (多轮实战总结)
1. **每个修复用"崩溃前存活秒数"当验证指标** (60s→173s→210s→241s 递进 = 方向对)
2. 最小复现要覆盖真实场景: 纯 QTimer churn 不崩 ≠ 用户场景不崩 — 压力测试要加
   QWidget/QDialog/QTableWidget 创建销毁 + QPixmap (用户操作面板的等价物)
3. 孤儿 timer 身份结论: 顶层 QObject 的 superClass() 返回 NULL → 记录 super="?" 是正常,
   不是损坏; "活着激活的孤儿" (无害) vs "已删对象表残留" (rdi=0x0, 崩溃源) 要区分
4. 业务逻辑层也可能有 15s/45s 周期 timer 误触发 (Model Zoo 轮询误判训练完成 → 自动交付
   线程并发) — 崩溃时间规律 (全在启动后 45s+) 是业务 bug 的信号
