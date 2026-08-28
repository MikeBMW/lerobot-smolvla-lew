# RGB-D 渲染窗口 — 多视角独立拖动 (model_tree.py DataBusTrace)

## 触发场景
数据总线 (DataBusTrace) 右键视觉信号行 →「🎨 渲染 RGB-D 图片」→ 弹窗显示该时刻
真实 metaworld 视角 (RGB+D 并排)。老倪需求 (2026-08-23): 窗口能独立拖动、能同时
开多个视角并排对比。

## 原 bug 根因 (两个问题, 同一处代码)
`model_tree.py::_render_rgbd` 原实现:
```python
dlg = QDialog(self)      # ① parent=self
dlg.exec_()              # ② 模态阻塞
```
1. **拖动带动主窗口**: 有 parent 的模态对话框被窗口管理器 (GNOME mutter / WSLg) 当作
   attached modal, 拖动它时父窗口 (studio 主窗) 跟着动 — 老倪 "一拖动整个窗口都动"。
2. **一次只能开一个**: exec_() 进入自己的事件循环阻塞主窗, 无法同时开多视角。

## 修复模式 (已落地 model_tree.py)
1. **独立顶层窗口**: `dlg = QDialog(None)` (无 parent) → WM 给独立标题栏, 自由拖动,
   不跟随主窗口; `show()` 非模态。
2. **保持引用防 GC**: `self._render_windows` 列表; append 前清理 `not w.isVisible()`
   的旧窗口 (QDialog 关闭默认不析构, 引用还在, 别让列表无限膨胀)。
3. **后台线程渲染**: metaworld 150 步 env.step 很慢, 放 `threading.Thread(daemon=True)`,
   渲染完 `QTimer.singleShot(0, lambda: ...)` 回主线程建 QImage/QPixmap/QDialog
   (Qt 控件非线程安全 — 同崩溃铁律: worker 线程禁 QObject 操作)。
4. **打开全部 N 视角**: 后台串行 `for cam in _MW_CAMERAS: render → singleShot 弹窗`,
   逐个弹出 (不用等全部完成); lambda 用默认参数捕获循环变量 `lambda c=cam, e=err, i=img:`。
5. **metaworld 懒加载加锁**: `_MW_RENDER_LOCK = threading.Lock()`, `_get_metaworld_view`
   整个函数体 `with _MW_RENDER_LOCK:` — 防并发开多视角时 EGL 上下文冲突。
6. **高分屏缩放**: 大图 `pm.scaled(max_w, max_h, KeepAspectRatio, SmoothTransformation)`
   窗口别超屏 (192DPI 坑, 见 hidpi-192dpi.md)。

## 涉及代码 (model_tree.py)
- `_render_rgbd(row, camera_name)` — 入口, 解析行→idx→_spawn_render
- `_spawn_render(idx, t_val, camera_name)` — 后台单视角渲染
- `_render_all_views(row)` — 后台串行渲染全部 7 视角
- `_show_render_window(camera_name, t_val, img, err)` — 主线程弹非模态独立窗口
- `_get_metaworld_view(camera_name)` — 锁内懒加载 metaworld 环境 + 专家策略轨迹
- `_MW_CAMERAS` — 7 个相机视角 (corner2/gripperPOV/behindGripper/topview/corner/corner3/corner4)

## 通用铁律 (可复用)
- **要「独立拖动 + 同时多窗口」的弹窗: QDialog(None) + show() + 列表保引用**;
  需要阻塞确认才用 exec_ (且 parent=None 时仍要注意 WM attached 行为)。
- 渲染/网络等慢操作一律后台线程 + QTimer.singleShot 回主线程改 UI。
- 并发懒加载共享资源 (metaworld/GPU 上下文) 加锁串行化。

## 开发闭环 (改完 model_tree.py 重启)
老倪的 studio.py 是 terminal(background=true) 起的: 直接 `process(action='kill',
session_id=...)` 杀比 `pkill -f "[s]tudio.py"` 干净 — pkill 与 `$(...)` 命令替换拼
一条命令会被 Hermes hardline parser 误拦 (block); 若用 pkill 必须单独一条、不带命令替换。
改完 → ast.parse 验证 → kill 旧进程 → background 重启 → sleep 5 确认 pid + xwininfo 窗口。
