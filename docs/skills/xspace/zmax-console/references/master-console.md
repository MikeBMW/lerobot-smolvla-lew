# CICD 主控台 — 实现细节 (2026-08-02)

老倪需求原话: "控制台是主控点，能看到CICD的全局，你要在node上，要有所有链路上的主要node，要能运行；控制台，既要有metaworld的数据，又要有orin，又要有act模型，我可以随意切换如何训练" → 追加 "仿照simulink, 增加一个switch界定/switch节点"

## 设计原则

- 迭代开发: 全部复用 simulink_module.py 现有资产 (REFERENCE_APPS / CICDWorker / 节点状态色 / _ensure_training_data), 不重写
- 主画布 = CICD 主控: 全链路节点图上每个节点双击即运行/切换
- 数据源选择: **Switch 节点 (仿 Simulink Switch 块) 是路由中枢**, 旧"数据源节点互斥激活"机制保留但优先级低于 switch

## 代码锚点 (tools/gui/simulink_module.py)

1. **新增第 6 节点类型 `switch`** (NODE_TYPES: cn=路由, color=#f0a030):
   - **⚠️ 必须三处同步**: simulink_module.py NODE_TYPES + tools/ci/validate_flow.py NODE_TYPES + tools/gui/simulink_ci.py NODE_TYPES — 两个验证器各有**独立**枚举, 漏改 → validate --strict 报 "节点[i] 类型非法: 'switch'" rc=1 (实测踩过)。改完跑 `python3 tools/gui/simulink_ci.py test` 内置回归 + 主控台 flow 过 `validate_flow.py --strict`。
   - add_node 的 icon 字典必须加 "switch": "🔀" (KeyError 若漏)
   - LIBRARY system 组加 "S06 Switch 数据源" params {switch: orin}
   - paint 特殊绘制: 类型行显示 "🔀 SEL: orin/metaworld" (非节点类型名); 双输入端口 (左上 in1=orin / 左下 in2=metaworld, 选中侧绿点 r=7 其余 r=5) + 单输出 (右中)。其他节点仍单进单出。
   - 连线锚点仍是 src 右中 / dst 左中 (SimLinkItem._path 不区分端口), 双输入连线视觉上同汇左中, 可接受 (迭代优化项)

2. **REFERENCE_APPS[0] = "🎛 CICD 主控台"** — **7节点6连线**:
   - 📥 Orin 数据源 (hardware, source=orin) + 📦 metaworld 数据 (hardware, source=metaworld) → 🔀 Switch 数据源 (switch, params.switch=orin) → 🧠 ACT 训练 (model) → ✅ 模型验证 (condition) → 📦 集成打包 (action) → 🚚 部署 Orin (hardware)
   - 连线: (0,2)(1,2)(2,3)(3,4)(4,5)(5,6)
   - open_cicd_panel 画布空时加载 REFERENCE_APPS[0], 打开 CICD 即见全局主控
   - ⚠️ REFERENCE_APPS 首位已不是 "⚙️ CI/CD 默认流水线" (3节点), 旧测试假设会 FAIL

3. **SimNodeItem.mouseDoubleClickEvent** → `self.scene_ref.on_node_activated(self.node)` (不再直接开参数框)

4. **SimulinkModule.on_node_activated(node)** 分发顺序:
   - `params.get("source")` → `_toggle_source(node)` (数据源节点激活, 旧机制)
   - `params.get("switch") or node.get("type") == "switch"` → `_toggle_switch(node)` (switch 路由 orin↔metaworld, 双击即切)
   - 名称含 训练/验证/集成/部署 (NODE_RUN_ACTIONS) → `_run_node_stage(node, fn, label)`
   - 其他 → `BlockParamsDialog(node, None)`

5. **_toggle_switch(node)**: `p["switch"] = "metaworld" if p.get("switch","orin")=="orin" else "orin"` → item.update + scene.update → 日志 "🔀 Switch 切换到 → ..." → _sync()

6. **_switch_state()**: 遍历 nodes 返回**首个** switch 节点路由 ("orin"/"metaworld"/None, 非法值归一为 orin)

7. **_toggle_source(node)**: 当前节点 params["active"]=True, 其他 source 节点全 False (旧机制, 仍可用)

8. **_active_source()**: 返回激活 source 节点的 "orin"/"metaworld"/None

9. **_ensure_training_data() 数据源优先级** (在拉 relay 之前):
   - `sw = self._switch_state(); src = sw if sw is not None else self._active_source()`
   - src=="metaworld" → data/metaworld_act 存在则直接 return 占位集 (跳过 relay, **避免把 relay /latest 弹栈数据取走**); 不存在则回退自动
   - src=="orin" → 强制走 relay 拉取分支 (无数据时仍回退占位集)
   - 无 switch/数据源节点 → 原有自动逻辑 (先 relay 后占位)

10. **_run_node_stage(node, fn, label)**: 与 _start_worker 同款但绑定节点状态:
    - 防重入: `cur = getattr(self, "_worker", None); if cur is not None and cur.isRunning()`
    - node["status"]="running" → item.update; 完成 success/error → item.update + scene.update; 复用 self._worker (与工具栏按钮共用防重入)
    - fn 必须可后台执行 (on_train/on_validate/on_integrate/on_deploy 都是)

## 链路选中区分 — SimLinkItem._switch_active() (2026-08-02 用户实测反馈修复)

用户反馈: "我都选择metaworld了，为什么 orin那条线，点击运行后，也在显示流动呢？要有区分"。
根因: 流动动画 `_tick_flow` 只看**源节点** status ∈ (running, success)，不看链路是否被 switch 选中 — 采集轮询 `_poll_acquisition` 会把 hardware 节点标 running，Orin 源一旦 running 其连线就流动。

修复 (commit 0fe89d25):
- `SimLinkItem._switch_active()`: dst 是 switch 节点时, 源侧 `params.source` (兜底按名称含 orin/metaworld) 与 `dst.params.switch` 不匹配 → False; dst 非 switch → True。
- `_tick_flow`: 流动条件加 `self._switch_active()` — 未选中链路 `_flow_offset` 归零。
- `paint`: flowing 条件同样加 active; **未选中链路颜色覆盖为暗灰 #3a3f4b 实线** (选中链路保持类型色+虚线流动)。箭头色也随 color 变量。
- 切换路由立即生效 (每次 tick 重查 switch 当前值)。
- ⚠️ 补丁技巧: 给类加方法时若 new_string 里含 paint 而 old_string 只匹配 _tick_flow, 会产生**重复 paint 定义** (Pyright reportRedeclaration) — 只加辅助方法, paint 单独 patch。

验证: 加载主控台 → 源节点全标 running → 选中链路 `_flow_offset > 0` / 未选中 `== 0` → 双击 switch 切换后反转 → paint 不崩 (本会话 11/11 PASS)。

## 验证要点 (offscreen, monkeypatch 真实执行器避免网络/训练副作用)

- 模板: REFERENCE_APPS[0] 7节点6连线, 含 switch 节点且 params.switch=="orin"
- switch 切换: 双击 → metaworld → 再双击 → orin; _switch_state() 正确
- 分发: 环节节点 → _run_node_stage(on_train); 数据源/switch 双击不触发运行
- 真实 worker: 见 SKILL.md 陷阱 "offscreen 验证 QThread 异步信号" (processEvents 驱动, 别只等 isRunning)
- metaworld 时 _ensure_training_data 不碰网络直接返回占位集; orin 时 monkeypatch requests.get 返回 500 断言回退占位
- 主控台 flow 过 `validate_flow.py --strict` rc==0; `simulink_ci.py test` 内置回归 rc==0
