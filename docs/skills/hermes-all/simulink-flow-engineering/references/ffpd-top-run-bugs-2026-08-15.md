# 前馈 PD 顶层画布点运行两次 bug 修复 (2026-08-15)

用户现象: ① 前馈 PD 顶层画布点▶运行 → 跳到 Z700 画布 ("跳动就很奇怪了");
② 修复①后点运行 → 疯狂显示单步刷屏 ("我点击的是运行")。

## Bug ①: 点运行跳 Z700

**根因**: `start_sim` (~4445 行) 有 2026-08-05 旧逻辑 — 画布无环节节点
(训练/推理等 NODE_RUN_ACTIONS) 时, 自动找 `params.subsystem` 块展开重试
(为"🔬总系统/Scope观察模板"设计: 无环节 → 自动下钻子系统)。前馈PD顶层画布
(flows/ff_pd_top.json) 含 🔬Z700 子系统节点 (`params.subsystem:"z700_sub"` +
`params.z700_subsystem:True`) → 点运行被当空模板自动 `_open_subsystem()` 下钻进 Z700。

**修复**: sub_node 查找排除 z700_subsystem:
```python
sub_node = next((n for n in self.nodes
                 if n.get("params", {}).get("subsystem")
                 and not n.get("params", {}).get("z700_subsystem")), None)
```
只排除 Z700, 其他 subsystem 模板(总系统等)行为不变。

## Bug ②: 点运行疯狂单步

**根因**: 排除 z700_subsystem 后顶层画布落入"观察模式"分支 → `_timer.start(16ms)`
→ `_tick()` 调 `step_sim()`(2026-08-12 单步改造后 step_sim 每次只执行 1 个节点)。
但 step_sim **不推进 `_sim_t`** → `_tick` 的停止条件 `if self._sim_t >= self._sim_t_end:
stop_sim()` 永不满足 → 一轮走完 `_step_order=None` 自动重置再来 → **无限循环单步刷屏**。
这是 2026-08-12 单步改造引入的回归: `_tick` 没跟着改。

**修复**: 顶层画布(z700_subsystem)点运行不走 timer — 一次性拓扑执行完即停:
```python
if any(n.get("params", {}).get("z700_subsystem") for n in self.nodes):
    self._log("▶ 前馈 PD 顶层系统 — 拓扑仿真: 📡参考输入 → 🔬Z700子系统(黑盒) → 🖥Scope/⚙️PD分析")
    self._sim_t = 0.0; self._step_order = None; self._step_idx = 0
    self._sim_running = True
    for n in self.nodes: n["status"] = "idle"; it=...; it.update()
    self._exec_topological()          # 一次性执行全部节点
    self._sim_running = False
    self._log("✅ 顶层系统仿真完成 ...")
    self.btn_run.setText("▶ 运行"); self.btn_run.setEnabled(True)
    self.btn_stop.setEnabled(False)
    self._refresh_status(); self._tutorial_on_action("run")
    return
```
同时 `_exec_topological` 补排除 row_bg 背景行 (与 step_sim 一致):
```python
order = [nid for nid in self._topo_sort()
         if self._by_id(nid).get("type") != "row_bg"]
```

## 验证 (offscreen)

```python
m = sm.SimulinkModule(); m._sync = lambda: None
m.load_flow_file(FLOW, confirm=False)   # ff_pd_top.json
timer_starts=[]; m._timer.start = lambda *a,**kw: timer_starts.append(a)
step_calls=[]; m.step_sim = lambda *a,**kw: step_calls.append(1)
m.start_sim()
assert not timer_starts   # 不启动 16ms timer
assert not step_calls     # 不走单步
assert m.btn_run.text()=="▶ 运行" and m.btn_run.isEnabled()
assert not m._sim_running
```

## 规律

- 排查"点运行卡死/刷屏/跳转"先读 start_sim 分支序:
  LeftRightPolicy → 环节节点(_canvas_stage_nodes) → subsystem自动展开 → 观察模式。
- 凡"无环节节点画布"点运行要审视观察模式路径: 观察模式 timer 循环只对
  "有 _sim_t 推进"的模板成立; 新画布模板要确认运行语义(一次性拓扑执行 vs 动画仿真)。
- 单步改造(step_sim 语义变化)后必须同步检查所有调用方(_tick/_exec_topological),
  别只改 step_sim 本身。
