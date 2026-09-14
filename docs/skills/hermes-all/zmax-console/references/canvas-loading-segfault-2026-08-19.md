# 画布加载崩溃 + Segfault 排查 (2026-08-19)

## 事件: 状态空间画布"连线全没" + 反复 Segfault (5 次)

### 根因 (最终实锤)
`tools/gui/simulink_module.py` 的 `add_node()` 里:
```python
"icon": {"condition": "❖", ..., "coord_overlay": "🧩"}[ntype],   # KeyError!
```
**icon/COLORS 字典缺 `mode_switch` 类型**。给状态空间画布
(`flows/state_space_obs.json`) 加「🔀 训练/推理」节点 (type=mode_switch) 后,
用户切画布走 `load_flow_file` → `add_node(ssmode)` 抛 **KeyError** →
`for spec in nodes` 循环中断 → **links 循环根本没执行 → 21 条连线全不建** +
画布处于半加载态 (部分节点在) → 后续渲染/交互访问缺失对象 → **C 层 Segfault**。

### 调试链 (重要教训)
1. **离屏验证过了但仍崩** — 因为测试走的是 `m.load_flow(data)` (直接 dict),
   真实路径是 `m.load_flow_file(path)` (逐节点 `add_node`)。**两条路径不同**,
   前者跳过 add_node 的字典查找。**验证画布加载必须用 load_flow_file**。
2. 连线渲染逻辑 (`_draw_links`) 只依赖 `_items.get(f/t)` 存在性 — 连线消失 =
   节点没建, 不是渲染问题。先查数据, 别先怀疑 VcXsrv 渲染。
3. 一度误判"VcXsrv 渲染贝塞尔曲线崩溃"把 cubicTo 改成折线 — **错误的假设**,
   真根因是 KeyError。改回 cubicTo (视觉更好)。
4. faulthandler dump 只有 Python 栈 (main 在 exec_); C 层崩溃要 gdb:
   `tools/gui/studio_gdb.sh` (gdb batch, 崩溃自动 thread apply all bt)。

### 规则 (防复发)
- **画布 JSON 加新类型节点 → 必须同时补**: `NODE_TYPES` + `add_node` 的 icon 字典。
  本次漏了 mode_switch (node_logic.py 已注册但 add_node 字典没有)。
- **画布 JSON 是唯一数据源** (flows/state_space_obs.json 同源同步模块库) —
  改 JSON 后必须用 `load_flow_file` 离屏验证 24 节点/21 连线全建。

## 跨线程 QTimer Segfault (QObject::killTimer from another thread)

### 根因模式
**QTimer.singleShot 从子线程调用 (无 parent)** → timer 属于子线程 →
子线程退出/GC 时销毁 → Qt `killTimer cannot be stopped from another thread`
→ SIGSEGV。之前只堵了 `_oneshot` 创建路径, 漏了 3 处:
- `studio.py _on_ws_status` (WS 线程回调 → singleShot 回主线程)
- `studio.py _cam_apply_later` (摄像头探测/轮询子线程 → singleShot)
- `simulink_module.py` 训练完成回调 singleShot(800/5000) (主线程, 统一改稳妥)

### 修复模式 (studio.py 顶部)
```python
class _OneshotBridge(_QObjectS):
    sig = _pyqtSignalS(object, int, object)
_oneshot_bridge = _OneshotBridge()
_oneshot_bridge.sig.connect(lambda p, m, f: _oneshot(p, m, f))

def _oneshot(parent, ms, fn):
    if QThread.currentThread() is parent.thread():
        t = _QTimerS(parent); t.setSingleShot(True)
        t.timeout.connect(fn); t.start(ms); return t
    # 跨线程 → 桥接信号自动 QueuedConnection 回主线程创建 (挂 parent 防 GC 竞态)
    _oneshot_bridge.sig.emit(parent, ms, fn)
```
注意: PyQt5 `QMetaObject.invokeMethod` **不接受 Python callable** (只收 str 方法名),
桥接信号是正确方案。创建/销毁/回调全在主线程 = 根治 killTimer 跨线程。

### 纪律
- **子线程回主线程: 一律 `_oneshot(self, 0, lambda: ...)`, 禁用 QTimer.singleShot**。
- 主线程 singleShot 也尽量统一 _oneshot (挂 parent 防 08-18 wrapper GC 竞态)。
- 排查 Segfault: 先看 faulthandler 栈; 无 Python 栈 → C 层 → gdb batch 包裹。
