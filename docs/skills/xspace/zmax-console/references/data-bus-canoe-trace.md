# 🔌 数据总线 (CANoe Trace 风格) — 状态空间接口数据监视 (2026-08-22 实测)

## 需求
参考 CANoe Trace 窗口, 把状态空间六层节点的**所有接口数据**做成"数据总线":
点击 ▶运行 后看到数据在总线上**流动** (时间顺序逐行), 而非静态快照。

## 三文件改动 (完整落地链路)
1. `state_space_sim.py` — 引擎 `run(io_every=25)` 记录 `tr["io_trace"]` 抽样快照
   - 提取 `_io_snapshot(force, obs, u_ff, act4, latent_pred, prior, z_k, corrected,
     residual, contact_p, r_scalar, u_fb, u, stage, u_sat, u_vec, force_norm)` 方法
     (九模块 in/out 完整变量, 数值为 numpy 数组引用 — 每步新建对象, 引用安全不覆盖)
   - 循环里 `if io_every is not None and (step % io_every == 0 or done):
     tr["io_trace"].append((round(t,3), last_io))` → 每 25 步 + 最后一步记录
   - `tr["io"]` 保留最后一步 (兼容旧 ss_tree 树形变量监控)
   - 引擎耗时: io_every=25 约 44ms / 无 io_every 约 21ms (纯 numpy, 非瓶颈)
2. `model_tree.py` — `DataBusTrace` 组件 (QTableWidget 5列: ⏱时间/🔗通道/📋接口/⬅➡方向/📊数据)
   - `cmb_view` 加「🔌 数据总线」(index 9), `_switch_view` 加 `bus = idx == 9` 分支
   - 双模: 🔁时间顺序(每传输一行=数据流) / 📌固定格式(每接口一行, 值=最新快照)
   - `begin_stream()` 清空表格+切时间顺序; `append_snapshot(t, io)` 逐帧追加不清空
   - 选中行 → `highlight_ss_links(模块名, "in"/"out")` 画布连线金色高亮 (复用 2026-08-20 联动)
3. `simulink_module.py` — 运行流程接线
   - `_start_state_space_sim`: 动画开始前若在数据总线视图 → `bus.begin_stream()`
   - `_ss_tick`: `n_rounds = len(io_trace)` 驱动帧数, 每帧 `bus.append_snapshot(io_trace[self._ss_round])`
   - `_ss_finish`: 仅固定格式模式才 `bus.refresh()` (时间顺序已动态填满)

## 关键坑 (全部实测踩过)

### ⚠️ QTableWidget 一次性填充大表格 → 真实 GUI 假死 (not responding)
- **offscreen 验证快 ≠ 真实 GUI 快**: offscreen 无 viewport 重绘, setItem 秒回; 真实 GUI 每次 setItem 触发重绘。
- 629 行一次性 `setRowCount` + 逐格 `setItem` → 主线程阻塞数秒 → GNOME 弹 "not responding"。
- **修**: 增量追加 — 每帧只 `append_snapshot` 37 行 + `scrollToBottom()`, 17 帧滚完, 不卡。
- **铁律**: 大数据量表格展示必须"增量追加"而非"一次性灌入"; offscreen 通过 ≠ 真实 GUI 不卡。

### 用户偏好: 数据展示要"动态生成" (实时滚动), 不要运行完一次性静态填充
- 老倪原话: "数据总线怎么不动呢？我点运行的时候，应该是动态生成数据"。
- CANoe Trace 的语义 = **实时捕获数据流**, 不是事后导出静态表格。仿真类数据显示必须跟动画逐帧联动。

### patch 删旧代码要删干净 (提取方法后旧 dict 字面量残留)
- 症状: `last_io = self._io_snapshot(...)` 之后又被原 dict 字面量 `last_io = {...}` 覆盖 → 每步构建两次 dict。
- 功能"看起来对" (io_trace 里存的是 _io_snapshot 结果), 但冗余、费 CPU、且易误导后续维护。
- 检查: 提取方法后 grep 旧代码块是否残留; `ast.parse` 过不等于没冗余。

## 卡死/进程诊断工具 (GUI 无响应定位)
- 主线程卡在哪: `sudo gdb -p <PID> -batch -ex "info threads" -ex "thread 1" -ex "bt"`
  - `poll()` + `QEventDispatcherGlib::processEvents` = 正常空闲事件循环 (**没卡**, 是短暂假死已恢复)
  - `PyEval_EvalFrame` / Qt 渲染函数 = 卡在 Python/Qt 代码
  - ptrace 权限: 需 `sudo` (yama ptrace_scope), 免密 sudo 可直接用
- `pkill -f "关键词"` 会匹配到**自己的 shell 命令行** (命令字符串含关键词) → 把自己 SIGKILL, exit_code -9。
  - 修: `pgrep -f` 先拿 PID + `ps -o comm= -p $p` 过滤掉 bash/shell, 再对纯 python PID `kill -9`。
- 进程 CPU 判读: 多线程 GUI 的 %CPU 是 37 线程总和, 单看 %CPU 17% 不代表死循环; 看 `cat /proc/<PID>/stat` 的 utime 增量 + gdb 主线程栈更准。
