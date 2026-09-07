# 🔌 数据总线 (CANoe Trace 风格) — 状态空间接口数据监视 (2026-08-22)

参考 CANoe Trace 窗口, 把状态空间画布六层节点间的所有接口数据做成"数据总线"。
右侧 model_tree 下拉新增「🔌 数据总线」视图 (cmb_view index 9)。

## 三件套 (改状态空间接口数据必查)

- `state_space_sim.py`: `run(io_every=25)` 记录 `tr['io_trace'] = [(t, io_dict), ...]`;
  `_io_snapshot(...)` 构建单步 9 模块 I/O 快照 (37 接口)。io_every=None 兼容旧调用(只留 last_io)。
- `model_tree.py`: `DataBusTrace` 类 (QTableWidget 5列: 时间|通道|接口|方向|数据)。
- `simulink_module.py`: `_start_state_space_sim` 调 `run(io_every=25)` + `bus.begin_stream()`;
  `_ss_tick` 逐帧 `bus.feed(t, io)`。

## 双模 (用户明确要求两种, 都要动态)

- 🔁 时间顺序 (index 0): `append_snapshot()` 每次传输追加一行, 滚动 (数据流形态)。
- 📌 固定格式 (index 1): `update_snapshot()` 信号固定行不变, 时间/数据列实时刷新
  (CANoe「固定格式显示」: 同报文ID同行, 只更新时间/数据场)。
- `feed(t, io)` 统一分发: index 0→append, index 1→update。切视图时 `refresh()` 完整重建。

## 卡死根因 & 动态生成 (2026-08-22 实锤)

- ❌ 一次性 `bus.refresh()` 填充 629 行 → 真实 GUI 下重绘假死 (not responding)。
  **offscreen 验证快 ≠ 真实快** (offscreen 无 viewport 重绘)。
- ✅ 改逐帧: `_ss_tick` 每帧 feed 一个快照 (37 行), 边跑边滚动, 不卡。
- 诊断 GUI 卡死: `sudo gdb -p <pid> -batch -ex "info threads" -ex "thread 1" -ex "bt"`
  — 主线程停在 `poll()` = 正常事件循环 (非死循环, 是瞬态卡顿)。ptrace_scope 需 sudo。

## 字体 (96 DPI)

- 表格 13px 太小 → 17px (对齐右侧树形 QTreeWidget); 表头 15px。
- ⚠️ `setDefaultSectionSize(24)` 固定行高会裁 17px 字 → 必须同步调到 34 (字大框小坑, 通用 QTableWidget/QTreeWidget)。

## patch 陷阱 (半替换)

- patch 只替换 `last_io = {` 开头 → 原 dict 字面量(几十行)残留, 每步构建两次 dict。
  `old_string` 必须覆盖完整块 (含结尾 `}`), 或用正则 DOTALL 删整段。

## 引擎数据量

- 500 步 / io_every=25 → 17 快照 (t=0→7.86s, 插入完成提前 break)。
- 9 模块 37 接口/快照 (传感器融合 out 含 6 个 obs 子分解: 43D/视觉39/当前18/上一18/目标3/触觉4)。
- 引擎耗时 44ms (run+io_every) vs 21ms (无 io_every) — 非瓶颈。

## pkill 自杀坑 (通用)

- `pkill -9 -f "studio.py"` 会匹配到自己 shell 命令行 → 把自己也 kill (exit -9)。
- 正确: `pgrep -f` 拿 PID → `ps -o comm= -p $p | grep -q python` 过滤 comm==python → kill -9。
