# RGB-D 多视角渲染窗口 (2026-08-23 老倪)

数据总线 DataBusTrace 右键视觉行 → 渲染真实 metaworld RGB-D 多视角窗口。
代码位置: tools/gui/model_tree.py (DataBusTrace._render_rgbd / _render_all_views / _show_render_window; render_rgbd_frame / _get_metaworld_view)

## 两个坑 (都实测踩过)

### 1. 后台线程 QTimer.singleShot 回主线程不触发
metaworld 渲染 150 步仿真慢 (3s/视角), 必须放 threading.Thread 后台渲染。
但用 `QTimer.singleShot(0, cb)` 从后台线程回主线程弹窗 → **回调永不执行**:
QTimer 绑定到发起它的线程, daemon 线程没有 Qt 事件循环, singleShot 根本不触发。
症状 = "等了很久没渲染", 但日志里 metaworld UserWarning 已出现 (渲染其实跑完了)。

正解: 类级 pyqtSignal emit 跨线程 (AutoConnection 自动队列投递到主线程):
```python
class DataBusTrace(QWidget):
    _render_done = pyqtSignal(str, float, object, object)  # camera_name, t_val, img(PIL), err
    def __init__(...):
        self._render_done.connect(self._show_render_window)
# 后台线程里:
self._render_done.emit(camera_name, t_val, img, err)
```

### 2. 渲染窗口模态拖动 (拖动它主窗口跟着动)
原实现 `QDialog(self) + dlg.exec_()`:
- 有 parent + 模态 → WM 把它当 attached 弹窗, 拖动它时主窗口跟着动;
- 模态阻塞, 一次只能开一个视角。

正解: 无 parent 独立顶层窗口 + 非模态 show():
```python
dlg = QDialog(None)          # 无 parent → WM 给独立标题栏可拖动
dlg.setWindowModality(Qt.NonModal)
dlg.show()                    # 非模态, 可同时开多个
# 保持引用防 GC
self._render_windows = [w for w in self._render_windows if w.isVisible()]
self._render_windows.append(dlg)
```

## 其他要点
- 7 相机视角 _MW_CAMERAS: corner2 / gripperPOV / behindGripper / topview / corner / corner3 / corner4。
- 右键菜单加「🖼 打开全部 7 视角 (并排)」→ 后台线程串行 for 循环渲染, 逐个 emit 弹窗 (渐进式弹出)。
- _get_metaworld_view 加模块级 threading.Lock 串行化环境创建 (并发开多视角防 EGL 上下文冲突)。
- 渲染 3s/视角, 全开 7 视角约 21s (首次 metaworld import 略久)。
- metaworld 渲染 `render_mode="rgb_array"` + `MUJOCO_GL=egl`, 帧 `np.rot90(..., k=2)` 180° 修正方向。
