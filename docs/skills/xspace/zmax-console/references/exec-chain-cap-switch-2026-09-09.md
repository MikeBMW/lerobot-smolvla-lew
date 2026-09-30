# 能力档位开关 + 执行链纪律 + 重启修复 (2026-09-09, v5.4.2)

状态空间画布三个连续用户实测 bug 同根:执行链(`_ss_order`/`_ss_step_order`)
内容没按"用户视角的执行语义"构建。本文是修复后的纪律,新画布/新节点照此。

## 执行链构建纪律 (单步 ⏭ / 播放 ▶ 共用)

`_ss_step_order`/`_ss_order` 构建时**必须排除三类节点** + 按档位过滤:

```python
_cnum = self._ss_cap_num()
self._ss_order = [n for n in self.nodes
    if n.get("type") != "row_bg"                    # ① 背景行
    and not n.get("params", {}).get("cap_switch")   # ② 开关节点 (执行=切档副作用)
    and not self._ss_is_observer(n)                 # ③ 观察器/质量门
    and self._ss_node_cap_level(n) <= _cnum]        # ④ 档位过滤
```

位置:simulink_module.py 三处 (6286 单步 / ~11100 真实播放 / ~11240 引擎播放)。

### ① 开关类节点 (cap_switch) 必须排除 — 实锤 L4→L2 自动切档
能力档位节点注册了 node_ss_cap,其逻辑语义 = "双击循环切档"。单步/播放把它当
普通节点"路过执行"→ 每轮自动 L4→L2。开关节点只响应**用户手动操作**
(单击 radio 直选 / 双击循环),任何自动执行链都不得包含。同类:train_gate /
yolo_gate / mode_switch 本就无 _reg 所以无害,cap 有 _reg 才踩中。

### ② 观察器/质量门 (viz_kind / verif_layer) 必须排除 — 实锤窗口轰炸
单步真实执行(demo=False)可视化观察器节点(直方图/归因/3D/操作视频/波形 =
params.viz_kind;Feature/Test = params.verif_layer)→ **自动弹真实窗口**
(3D GL 渲染 + 操作视频同时播 5 个视频)→ 4-5 重窗叠开 → GUI not responding。
观察器语义 = 用户手动双击才打开 (与 Scope 排除自动流程同一原则, 2026-08-04)。
判定 helper:
```python
def _ss_is_observer(self, node):
    p = node.get("params", {})
    return bool(p.get("viz_kind") or p.get("verif_layer"))
```

### ③ 档位过滤 — L2 档高亮 L4 行实锤
档位 L2 时单步/播放仍遍历全画布非背景节点 → L4 行(流形专家/接触/性能流形)
被高亮执行。过滤 = 节点所在 row_bg 色带层级 ≤ 当前档位:
```python
def _ss_node_cap_level(self, node):   # 按 node.y 落进哪个 row_bg → 4/3/2/0(基础恒包含)
def _ss_cap_num(self):                # {"L2":2,"L3":3,"L4":4}.get(_cap_level, 2)
```
基础·回路外行(数据源/大模型层/验证/可视化)返回 0 恒包含(注意观察器仍被②排除)。

### ④ 切档必须重置执行序 — 切 L3 不进 VLM/ActionHead 实锤
执行序只在首次点单步时构建;L2 建过(35 节点)后切 L3 不重建 → 永远走旧 L2 序。
`_toggle_cap` 切档时清 `_ss_step_order`/`_step_order` (+ 非播放中清 `_ss_order`,
播放中 tick 正用不能清)。用户验收口径:切档 → 点单步 → 日志节点数应变化
(L2=35 / L3=37 / L4=42 含 VLM+Flow-Matching)。

## 🔄 重启按钮 (2026-09-09 用户两次纠正, 语义推翻 09-04)

- **09-04 定**: "停止→清缓存→立即重新仿真"。**09-09 用户两次抱怨**
  "一点重启又跳到运行" → 改为 **永不自动运行**: 停止 → 清缓存 → 复位待命,
  要跑点 ▶ 运行 (▶ 停止态即从头跑;重启增量价值 = 清缓存强制引擎重跑)。
  tooltip/注释同步改, 别按旧注释实现。
- **崩溃修复 (mujoco C segfault 实锤)**: 真实化引擎是 daemon 线程且**从不终止**
  (旧注释"跑完即弃"), 🔄重启 stop 后立即 start = 新引擎与旧线程的 metaworld
  env 并发 → mujoco segfault (崩溃栈: metaworld reset_model → do_simulation)。
  修复三件套:
  1. 引擎 run() 循环首行查 `getattr(self, "_abort", False)` → log+break;
     `__init__` 置 `self._abort = False`
  2. GUI `_start_real_sim` 保存线程句柄 `self._real_thread` (单行 start 处)
  3. `stop_sim()` 开头: 置 `_rs._abort=True` → 轮询 `is_alive()` + processEvents
     (≤10s, 与训练 worker 停止同款, 禁裸 join 卡 UI)
- 验证 abort: 预置 `sim._abort=True` → `run()` 0 步退出 (R0 太快自然跑完测不出,
  必须预置才可证循环首行生效)。

## 契约坑: GUI 档位大写 "L4" vs 引擎判小写 "l4"
node_ss_cap/_toggle_cap 用 "L2"/"L3"/"L4", 引擎 `run(cap)` 判 `cap == "l4"`
→ L4 恢复预算×2 从未生效 (静态 grep 核实)。引擎入口一律归一化:
`cap = str(cap).lower() if cap else None`。跨层传参先 grep 两端大小写。

## 画布孤立节点 = "没有输入输出" 排查 (ssmani_exp 实例)
用户报节点"没有输入输出"时, 检查顺序:
1. `python3 -c` 统计 flow json 每节点入度/出度 (links f/t) → 入0出0 = 孤立
2. grep node_logic.py/simulink_module.py 该节点 id → 零匹配 = 无注册/无源码映射
3. 引擎 `_io_snapshot` 有无该节点名 channel → 无 = 播放/数据总线无数据
补齐三件套: ①flow 加真实连线 (参照同层节点同源) ②执行/注册 (或确认
match_node 关键词已命中现有注册) ③引擎 io_trace 发布 channel (值进
`_mani_out`/引擎每帧真算的旁路也要发布, 否则播放 demo 永远空)。
布局语义按用户: "XX 应该在 YY 的前面" = 数据流上游 + 画布 x 前排, 同层重排
时把下游节点右移让位 (flow 坐标 int)。

## 引擎短轮验证 predictor 每帧真调 (L4 档)
```python
RealStateSpaceSim(seed=104, vision=False, mode="full",
                  log=lambda *a: logs.append(...))
tr = sim.run(max_steps=80, cap="L4")   # GUI 同值大写
# 证据: 日志含 "🏆 L4 自主恢复档" + "JEPA 预测流形旁路已接"
#       + len(tr["mani_pred"])==80 且非全零帧 80
```
R0 vision=False ~0.01s/步, 80 步 <1s。predictor 旁路恒开与档位无关 —
诚实边界: 每帧真调 ≠ 驱动决策 (trained=False 随机权重, L4 恢复=引擎分级回退+预算)。
