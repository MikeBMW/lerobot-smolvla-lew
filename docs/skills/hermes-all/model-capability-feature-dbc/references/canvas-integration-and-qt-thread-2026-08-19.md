# 状态空间画布集成 + Qt 线程 Segfault 根治 (2026-08-19 后半)

## 1. 状态空间画布 = 能力落地视图

画布 `flows/state_space_obs.json` 是能力库的落地视图, 与模块库**同一数据源**
(`_load_state_space_library_group` 读同一 JSON — 改画布即同步库, 杜绝手抄漂移)。

分区 (从上到下, 全部 row_bg 同宽 1480, x=-20):
1. **数据层** — 📦 metaworld 数据源 (hardware, params.source=metaworld,
   policy/state_dim/action_dim) + 🔀 训练/推理模式开关 (type=mode_switch,
   params.mode ∈ {train,infer})
2. **感知层** — 🎯 YOLO 目标检测 / 📐 2D→3D 解算 / 🖐 触觉感知 / 🔍 外观质量检测
3. S1 时空感知前端 → S2 并行处理 → S3 认知决策 → 执行层

机制:
- 模式开关: 双击 `_toggle_mode` 切换, `_current_mode()` 读当前
  (画布上第一个 mode 参数的节点); `_apply_mode_highlight` 训练/推理节点高亮
- 数据源节点 params.run_env=True → on_node_activated 里在 source 分支**之前**
  检查 `params.get("run_env")` → `on_run_env`: train→on_train(policy=数据源配置,
  如 left_right) / infer→on_infer
- 感知节点名含 "YOLO" → NODE_RUN_ACTIONS ("YOLO", "on_yolo_sense") → 实际加载
  yolov8s.pt 跑检测 (tools/gui/yolo_perception.py)
- mode_switch 绘制: paint 分支 `t == "mode_switch"` 画绿点🚀训练/蓝点📷推理

**增量修改铁律** (用户: "不要改变当前的已有框架" / "摆放整齐"):
- 新增能力只**追加**节点/连线/端口 (ssobs inputs 扩 in2/in3), 不删不改现有链路
- 新节点字段仿照现有节点: id/name/type/icon/x/y/w/h/inputs/outputs/actions/
  color/params (params 带 state_space=True, desc, source)
- 连线 {id, f, t, f_port, t_port, label}; 改完校验无悬空
  (links 的 f/t 都在 nodes ids 里)
- row_bg 无 inputs/outputs 键 → 遍历用 n.get("inputs", []) 防御 KeyError
- 布局: 节点一排等间距 (宽 240, 间距 80), y = 背景.y + (背景.h-88)/2 垂直居中
- 改 JSON 后验证: `_load_state_space_library_group()` 节点数同步 + 悬空连线检查

## 2. Qt 线程 Segfault 根治 (QTimer 跨线程)

**根因链** (gdb 日志实锤):
```
QObject::killTimer: Timers cannot be stopped from another thread
QObject::~QObject: Timers cannot be stopped from another thread
Fatal Python error: Segmentation fault
```
= QTimer 在子线程创建 (无 parent 的 QTimer.singleShot 或跨线程 parent),
子线程退出/GC 时销毁 timer → Qt 跨线程 killTimer → SIGSEGV。
这是 08-18 崩过两次的同源问题, 表面现象是 GUI 卡死/闪退。

**高危模式**: 子线程回调里 `QTimer.singleShot(0, lambda: ...)` 回主线程 —
singleShot 内部 timer 无 parent, 归属子线程, 线程退出即崩。本会话抓到 3 处:
- `_on_ws_status` (WSClient on_status 在 WS 线程回调)
- `_cam_apply_later` (摄像头探测/轮询子线程)
- 训练完成回调 singleShot(800/5000) (主线程, 但统一改 _oneshot 更稳)

**修复: _oneshot 跨线程桥接** (studio.py 顶部):
```python
def _oneshot(parent, ms, fn):
    if QThread.currentThread() is parent.thread():
        t = _QTimerS(parent); t.setSingleShot(True)
        t.timeout.connect(fn); t.start(ms); return t
    _oneshot_bridge.sig.emit(parent, ms, fn)   # 子线程 → 桥接信号
    return None
```
桥接: 模块级 `_OneshotBridge(QObject)` + `sig = pyqtSignal(object, int, object)`,
创建于 import 时 (主线程), connect 到 _oneshot; 子线程 emit → 自动
QueuedConnection → 主线程执行 _oneshot → 主线程创建挂 parent timer ✓

注意: PyQt5 `QMetaObject.invokeMethod` **不接受 Python callable** (只收 str 方法名),
跨线程派发必须用桥接信号, 不能靠 invokeMethod。

**排查清单** (Segfault 复现时):
1. 日志找 killTimer/Cannot create children 行 → 定位哪个 QObject 跨线程
2. 搜所有子线程 (threading.Thread/QThread.run) 里的 QTimer/singleShot/_tq
3. 统一改 _oneshot; 主线程 singleShot 也改 _oneshot (挂 parent 防 GC 竞态)
4. faulthandler.dump_traceback_later(20, repeat=True) 已启用 — 崩溃时全线程栈可查

## 3. 导出/上传后台线程铁律
sshpass scp 等长操作跑主线程 = 按钮假死 (gdb: selectors.py select 60s)。
统一模式: 点击 → lbl 提示"⏳ 正在…" + 按钮 setEnabled(False) →
threading.Thread 跑 → pyqtSignal 回主线程更新 lbl + 恢复按钮。
类上声明 `export_done = pyqtSignal(str)`, 信号 connect 到槽。

## 4. QLabel 链接可选中/可点击
用户报"链接点不了选不中": QLabel 默认不可选。修复:
```python
lbl.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextBrowserInteraction)
lbl.setOpenExternalLinks(True)
lbl.setText(f'✅ 已导出: <a href="{url}" style="color:#58a6ff;">{url}</a>')
```

## 5. VcXsrv XCopyArea 半移复现 (滚动下半部残留)
08-18 修复时 XCopyArea 正常, 08-19 VcXsrv 会话状态变化后搬运也坏:
滚动时上半部(露出重绘)正常、下半部(搬运区)残留。修复 (SimCanvas):
```python
def scrollContentsBy(self, dx, dy):
    super().scrollContentsBy(dx, dy)
    vp = self.viewport(); w, h = vp.width(), vp.height()
    for y in range(0, h, 400):
        vp.repaint(0, y, w, min(400, h - y))   # repaint 同步不合并; update 会合并成大 region 失效
```
每块 400px = 小 XPutImage, 绕开 VcXsrv 大图只画顶 bug。根治仍需升级 VcXsrv。
