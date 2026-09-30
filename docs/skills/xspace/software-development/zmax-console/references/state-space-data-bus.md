# 🔌 状态空间「数据总线」— CANoe Trace 风格接口数据监视 (2026-08-22)

用户需求: 参考 CANoe Trace 窗口, 把状态空间**所有接口数据**做成"数据总线" —
点 ▶运行 后能看到数据在六层节点间**时间顺序流动** (不是只看到静态最后一步快照)。

## 数据流 (四件套)

```
state_space_sim.py  run(io_every=25)
  → tr["io_trace"] = [(t, io_dict), ...]   每快照 9 模块 in/out 完整变量
  → model_tree.py   DataBusTrace.refresh()  QTableWidget 5列
  → simulink_module _ss_finish()            切到视图时自动 bus.refresh()
```

- 引擎 `run()` 原只保留 `last_io` (最后一步), 本次提取成 `_io_snapshot()` 方法 +
  新增 `io_every` 参数: 每 io_every 步(含最后一步) append 到 `tr["io_trace"]`。
- 每快照 **37 个接口** (不是 36): 9 模块 in/out 合计, 传感器融合 out 有 6 个
  (含 "├/│/└" 前缀子分解: 视觉39/当前帧/上一帧/目标/触觉4)。
- DataBusTrace 双模: 🔁时间顺序(每次传输一行, 默认) / 📌固定格式(每接口一行=最新快照)。
- 列: ⏱时间 | 🔗通道(模块) | 📋接口 | ⬅➡方向(▶IN青/◀OUT绿) | 📊数据(向量逐维展开)。
- 联动: 选中行 → `highlight_ss_links(模块名, "in"/"out")` (复用画布连线金色高亮)。

## 文件改动清单 (改/扩展此功能时必查)

1. `state_space_sim.py` — `_io_snapshot()` 方法 (九模块 in/out 结构) + `run(on_step, io_every)`
2. `model_tree.py` — `DataBusTrace` 类 (QTableWidget) + `cmb_view` 加 "🔌 数据总线" (index **9**)
   + `_switch_view` 加 `bus = idx == 9` 分支 + `self.bus` 实例化 (在 ss_tree 之后)
3. `simulink_module.py` — `_start_state_space_sim` 里 `sim.run(io_every=25)` +
   `_ss_finish` 里 `elif _idx == 9: _mt.bus.refresh()`

## 关键坑

1. **for 循环变量必须有名**: `for _ in range(n_steps)` 无法做 `step % io_every` 抽样,
   改成 `for step in range(n_steps)`。
2. **numpy 引用安全**: 快照里的 obs/u_ff/latent_pred/prior/z_k/u_fb 等每步都是新建对象,
   存进 io_trace 的旧引用不会被后续迭代覆盖 (residual/u/u_sat 源码已 .copy())。无需额外深拷贝。
3. **每快照 37 接口**: 断言/计数别按 36 算 (传感器融合 out=6 含子分解, 不是 5)。
4. **QTableWidget 列宽**: 数据列用 `Interactive + setColumnWidth(520)` (43D 向量可拖宽看全),
   接口名列 `ResizeToContents`; 若数据列用 Stretch 会被截断且无横向滚动条。
5. **`pkill -9 -f "studio.py"` 自杀坑**: shell 命令行本身含匹配串, pkill -f 会连自己一起杀
   (exit -9, 无输出)。重启前先 `pgrep -af studio.py | grep -v grep` 拿 PID 单独 kill, 或
   pkill 用不含自身命令行能命中的更窄 pattern。
6. **版本号不动**: 功能验收前只 patch 不改版本 (用户验收后再走 v2.5.x 升级 + commit/push + 技能沉淀)。

## 验证 (offscreen)

```python
os.environ["QT_QPA_PLATFORM"]="offscreen"; sys.path.insert(0, GUI); os.chdir(GUI)
from PyQt5.QtWidgets import QApplication; app=QApplication([])
from state_space_sim import StateSpaceSim; tr=StateSpaceSim().run(io_every=25)
class M:  # 假 module: 只要 _ss_tr + highlight_ss_links
    _ss_tr=tr
    def highlight_ss_links(self, a=None, b=None): pass
from model_tree import DataBusTrace; bus=DataBusTrace(M()); bus.refresh()
assert bus.table.rowCount() == len(tr["io_trace"])*37   # 时间顺序
bus.cmb_mode.setCurrentIndex(1); bus.refresh(); assert bus.table.rowCount()==37  # 固定格式
```
