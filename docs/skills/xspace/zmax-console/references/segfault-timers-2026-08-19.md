# Segfault 连环排查实录 (2026-08-19) — QTimer 跨线程 + 类型注册 + VcXsrv

控制台一天崩 9 次，最终实锤三根因 + 一个环境根。排查方法论和结论如下。

## 根因 1: 新节点类型未注册 → 加载中断 → 连线全没 + Segfault (最阴险)

**现象**: 状态空间画布"连接线全没了" + 切画布必崩。
**根因**: 在画布 JSON 里新增 `mode_switch` 类型节点后，`add_node()` 的
`icon` 字典和 `NODE_TYPES` 没有该类型 → `dict["mode_switch"]` KeyError
→ `load_flow_file` 的 nodes 循环中断 → **links 循环根本没执行**（连线全不建）
→ 半加载状态（部分节点在场）→ 后续渲染/交互访问缺失对象 → Segfault。

**铁律**:
- 画布新增任何节点类型，必须同步注册:
  1. `NODE_TYPES["新类型"] = {"cn": "...", "color": "#..."}`
  2. `add_node` 的 icon 字典加 `"新类型": "图标"`
  3. `node_logic.py` `_reg("新类型", ...)`（若有双击逻辑）
- 否则 KeyError 被 `except Exception` 吞掉 → 静默半加载，比直接崩更坑。

## 根因 2: QTimer/singleShot 跨线程 (killTimer from another thread)

**gdb 栈实锤**: `QTimerInfoList::activateTimers() → notifyInternal2` —
timer 激活时 receiver 已删（悬垂）。前置警告 `QObject::~QObject: Timers
cannot be stopped from another thread`。

**修复 4 层**（缺一不可）:
1. **所有 QTimer 必须挂 parent + PreciseTimer**
   `QTimer(self); t.setTimerType(Qt.PreciseTimer)` —
   CoarseTimer 批处理合并 → activateTimers 批次内 NULL receiver 竞态。
   simulink_module 的 `_tq()` 已是; simulink_scope/dataset_viewer 漏了,补上。
2. **QTimer.singleShot 从子线程调用 = 死刑**
   timer 在子线程创建（无 parent），线程退出 GC → killTimer cross-thread。
   studio.py 统一 `_oneshot(parent, ms, fn)`:
   - 跨线程调用经 `_OneshotBridge` 信号（QueuedConnection 自动排队）
     派发回主线程创建挂 parent timer — 注意 pyqtSignal(object,int,object)
     传函数对象本身在 WS 线程仍会制造临时 QObject → 见 3。
3. **WS/网络线程零 Qt 接触（最终根治）**
   回调线程只写纯 Python `queue.Queue`, 主线程 100ms PreciseTimer 轮询消费:
   ```python
   self._ws_queue = queue.Queue()
   self._ws_poll = _tq(self); self._ws_poll.timeout.connect(self._drain_ws_queue); self._ws_poll.start(100)
   # 回调线程: self._ws_queue.put(evt)   ← 不建 QObject 不 emit 信号
   ```
4. **CICDWorker(QThread) 对象永不 GC**
   `self._worker = worker` 下次任务覆盖时旧 QThread 被 GC，其内部 timer
   注册在已退出的 worker 线程 → 延迟 killTimer 爆炸。
   → 全部 worker 挂 `self._workers.append(worker)`（进程生命周期不清除）。

## 根因 3: VcXsrv 不稳定（最终环境根）

**二分实验**: offscreen 平台压测（stress_offscreen.py: 每 2s 模拟切画布/切模式/
开弹窗/重绘, 10 分钟 300 步）**零崩溃** → 代码问题清零 → 崩溃在 X11 层。

**根治**: 容器内 Xvfb + x11vnc, 摆脱 VcXsrv:
```
Xvfb :99 -screen 0 1600x900x24 &
DISPLAY=:99 x11vnc -display :99 -forever -shared -nopw -rfbport 5900 &
DISPLAY=:99 python studio.py
```
Windows 侧: `netsh interface portproxy add v4tov4 listenport=5900
listenaddress=127.0.0.1 connectport=5900 connectaddress=<容器IP>` + VNC Viewer。

## 排查方法论（复用）

1. 崩溃日志先看 "Fatal" 前最后一个 faulthandler dump 的线程归属
2. faulthandler 只有 Python 栈 → C/Qt 层崩溃用 gdb batch 包裹:
   `gdb -batch -ex run -ex "thread apply all bt full" --args python studio.py`
   （studio_gdb.sh 已入库）
3. **验证必须走真实加载路径 `load_flow_file()`**（add_node 重建 + id_map），
   不是 `load_flow()`（直接 dict）——后者会掩盖类型注册等 bug
4. offscreen 压测二分 X11 vs 代码（stress_offscreen.py 已入库）
5. WS/训练线程在崩溃 dump 里"在睡觉"≠无辜——延迟爆炸很常见（根因 2-4 都是）

## 其他本会话坑

- **模式开关持久化**: `_toggle_mode` 只改内存，切走画布重载即重置 → 切换时
  `_save_mode_to_flow` 按节点名写回画布 JSON（`_flow_path` 在 load_flow_file 记录）。
- **模式切换引导**: 切换后日志给明确操作引导 + `_highlight_node(数据源, ms=5000)`。
- **simulink_scope 弹窗关闭后 singleShot**: 全部改挂 parent 的 oneshot + PreciseTimer。
