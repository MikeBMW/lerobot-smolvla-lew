# 状态空间执行链/开关节点/重启修复 (2026-09-09 v5.4.2 实锤)

老倪当天连环反馈驱动的 7 个坑 + 修复,全部有日志/代码实锤。

## 1. 单步/播放执行链 = 画布"所有非 row_bg 节点",副作用节点被路过执行

`_ss_order`/`_ss_step_order` 原构建 = `[n for n in self.nodes if type != "row_bg"]`(3 处:
⏭单步 `_state_space_step` ~6286、真实轨迹播放 `_real_finish` ~11098、引擎播放 ~11236)。
**任何"有副作用的配置/观察节点"只要注册了 node_logic 就会在单步/播放时被自动执行**:

- **能力档位 (sscap, node_ss_cap)**: 注册词 "能力档位" → 单步执行它 = `_toggle_cap(level=None)` 循环切档
  → 用户 "L4 自己跳到 L2, 我没切换" 实锤。开关类节点 = 配置, 只应响应用户单击/双击。
- **观察器节点 (viz_kind: 🧠直方图/🎯归因/🧭3D视图/🎥操作视频/📊波形)**: 单步执行 = 真实弹窗
  (demo=False 走真实 fn) → 4-5 个重窗口(3D GL + 视频播放)叠开 → GUI not responding。
  观察器语义 = 用户手动双击才打开 (同 Scope 观察节点排除原则)。

修复(三个执行序构建处统一追加过滤, 顺序无关但条件要齐):
```python
_ss_step_order/_ss_order = [n for n in self.nodes
    if n.get("type") != "row_bg"
    and not n.get("params", {}).get("cap_switch")      # 开关类 (切档副作用)
    and not self._ss_is_observer(n)                    # viz_kind/verif_layer (弹窗/跑用例)
    and self._ss_node_cap_level(n) <= self._ss_cap_num()]  # 档位过滤
```

## 2. 档位过滤: L2 档单步/播放不得高亮 L3/L4 行功能

用户 "选了 L2, 怎么 L4 的功能也高亮了"。行归属 = 节点 y 落在哪个 row_bg 色带
(按 name 含 "L2/L3/L4" 判层; 数据源/大模型/验证/可视化等回路外行 = 0 恒包含):
```python
def _ss_node_cap_level(self, node):   # 节点 y → 所在 row_bg 色带 → 4/3/2/0
def _ss_cap_num(self):                # self._cap_level → {"L2":2,"L3":3,"L4":4}, 缺省 2
```
L2 档 35 节点 / L3 37(含 VLM+ActionHead) / L4 42(加 5 个 L4 行节点)。

## 3. 切档后必须重置执行序 (否则 L3 永远进不了 VLM)

`_ss_step_order` 只在 `is None` 时重建 → L2 档建过 35 节点序后切 L3, 旧序仍被单步使用
→ "选 L3 为什么不进入 VLM/Flow Matching"。修: `_toggle_cap` 内重置
`_ss_step_order/_step_order = None` (+ 播放中不动 `_ss_order`, 防 tick 崩)。

## 4. 🔄 重启两次行为纠正: 只复位不自动跑 (09-04 "立即重跑" 语义作废)

用户两次 "一点重启就跳到运行" → `restart_sim` 去掉尾部 `start_sim()`,
= stop_sim → 清缓存(_ss_step_tr/_ss_order/_ss_timer 等置 None) → log "已复位待命 (点 ▶ 运行)"。
tooltip 同步改。

## 5. 🔄重启崩溃 = 真实化引擎 daemon 线程无终止 → 双 metaworld env 并发 mujoco segfault

崩溃日志铁证: `Segmentation fault` in `metaworld reset_model → gymnasium mujoco_env._step_mujoco_simulation`
(旧引擎线程还在 mujoco 里, 重启立刻 new RealStateSpaceSim → 同进程双 env → C 崩)。
原 stop_sim 注释 "daemon 线程跑完即弃" 是隐患。

修三件套:
1. 引擎 `RealStateSpaceSim.__init__`: `self._abort = False`; `run()` 主循环第一行:
   `if getattr(self, "_abort", False): log(...); break`
2. `_start_real_sim`: 保存线程句柄 `self._real_thread = threading.Thread(...); start()`(勿留裸 .start())
3. `stop_sim()` 开头: 置 `_rs._abort = True` → 轮询 `_rt.is_alive()` + `processEvents()` 200×50ms (≤10s, UI 不冻结)
   → 等线程退出后才允许开新引擎。

验证: 预置 `sim._abort = True` 再 run → 0 步即退 (CLI 探针)。

## 6. 引擎 cap 大小写 bug: GUI "L4" vs 引擎判 "l4" → L4 预算×2 从未生效

`sim.run(cap="L4")` 引擎内 `if cap == "l4"` 永不命中。修: run 开头
`cap = str(cap).lower() if cap else None`。GUI 档位恒大写 L2/L3/L4。

## 7. 画布节点字体 09-09 二次降档 (08-28 之后用户又嫌大)

192 DPI (logicalDotsPerInch=192, 10pt=27px):
- 普通节点标题循环 `(10,9,8)` → `(9,8,7)`; 徽章/悬停 ID 10→9; row_bg 大字 fs=10 起→9 起 (下限 8→7);
  row_bg "▤ 背景行" 小标 9→8。改处加 🐛 注释留痕。

## 8. 断点"进不去"快速判定: 5678 无 ESTAB = 未 attach

`ss -tlnp | grep 5678`: 只有 LISTEN 无 ESTAB = debugpy 无客户端 → 断点永不命中 (非代码问题)。
09-06 起 studio.py main() 需 `ZMAX_DEBUG=1` 才 `debugpy.listen(5678)`(桌面默认不开防黑窗口);
窗口标题 2s 后变 "⚠️非调试模式" 可自证。修复 = ZMAX_DEBUG=1 重启 + VSCode attach。
单步"卡在节点不动"先查这个 + py-spy do_wait_suspend(断点冻结), 别急着改代码。

## 9. ff_hist 波动视图尖峰 = 阶段切换模式重排 (正常信号, 已实测)

wave 视图画的不是激活能量, 是 **‖Δx‖ = 每层激活帧间变化量** (push 里 `dlt[i]=‖a-prev‖`;
标题 "激活变化事件 ‖Δx‖"; ener 存了但 wave 画 dlt)。实测真实化 R1 seed104 352 步:
- 三层基线 L1=0.124 < L2=0.159 < L3=0.249 (深层累积, L3 紧挨输出)
- 插入→接触切换: L1 4.3x / L2 4.8x / L3 5.1x 尖峰 (硬切换 peg 触底)
- 物理: 阶段切换 = 引擎换目标/限速/夹爪 → obs 输入突变 → 网络一帧内把 512 单元从上一动作模式
  扭到新模式 → 深层传播后 L3 全域重排最大 = "执行转换层"。切换后 2-3 帧回落 = 健康, 持续振荡才是病。
窗口 _cap_text 已加自解释文案 (老倪问 "啥意思" = 图没自解释, 铁律: 可视化必自解释)。
