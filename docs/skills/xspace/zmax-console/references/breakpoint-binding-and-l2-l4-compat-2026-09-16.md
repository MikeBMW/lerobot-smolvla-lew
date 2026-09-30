# 断点绑定 + 执行证据 + L2/L4 兼容接线 (2026-09-16, v5.6.9~v5.6.12 实测)

老倪连问四轮「这段 forward 在 L4 运行时为什么进不了断点 / 为什么很久才进」，根因有**四层**，
逐层都实测过。下次同类问题按顺序查，别跳。

## 一、断点永不命中的四层根因 (按命中概率排序)

1. **方法被实例属性覆盖 → 真身一次都不进**（最常见，且和调试器无关）
   `tools/gui/state_space_sim_real.py:399`
   ```python
   if os.environ.get("SS_USE_MLP") == "1": print("🧠 分层伺服 …")
   else: self.accel.forward = self.accel.analytic_forward   # 实例属性遮蔽类方法
   ```
   全仓唯一读 `SS_USE_MLP` 的地方；GUI 任何档位都不设它 ⇒ `parallel.py:143` 的 `def forward`
   **永不执行**。判别（不靠调试器）: `"forward" in accel.__dict__` 为 True + `n_mlp==0`
   **且 `n_guard==0`** —— guard 也是 0 说明连域判定都没跑到，所以**不是 D_GUARD/DOMAIN_SIGMA
   挡的**（老倪和我都先猜错了这个方向）。
   修法: 档位内接线（见三），或 `SS_USE_MLP=1`。

2. **模块用 `spec_from_file_location` 加载 → debugpy 断点不绑定**（更隐蔽）
   引擎 `_load(name)`（state_space_sim_real.py:136）加载六层模块 (parallel/perception/
   cognition/execution/safety) 用的就是 spec 加载 ⇒ 函数真执行、日志有输出，VSCode 就是不停。
   修法（已落地）: `exec(compile(src, 真实绝对路径, "exec"))` + `types.ModuleType` + 注入
   `__file__`/`__name__` + 注册 `sys.modules`；失败退回 spec 加载并 **print 出来**（不静默降级）。
   验收判据（逐模块跑，0 例外才算过）:
   ```python
   for k, v in vars(mod).items():
       if isinstance(v, type):
           for n, f in vars(v).items():
               cf = getattr(getattr(f, "__code__", None), "co_filename", None)
               assert cf is None or os.path.abspath(cf).startswith(os.path.abspath(SS_DIR))
   ```
   实测: parallel/cognition/execution = 0 例外；exec 加载后跑 20 步
   `实例覆盖 forward=False · forward 指向 FeedforwardAccelerator.forward @ parallel.py · n_mlp=20 · n_guard=0`。

3. **断点设在 `def` 行 / docstring 行 → 无可命中字节码**
   `def forward(self, obs):` 下一行是 docstring 时，这两行都没有可执行字节码。断点必须设在
   **函数体第一条语句**（本例 `obs = np.asarray(obs, dtype=float)`）。

4. **档位走的是另一条链**（不是绑定问题，是代码不在链上）
   L4 档默认「🤖 L4 用 INTACT 节点执行」= 引擎路径 (有 FeedforwardAccelerator)；
   不勾 → L4Demo 演示链（独立 env/控制器，**没有这个类**，断点永远不可能命中）。
   另外必须 F5 启动（直接 `python studio.py` 是"非调试模式"，标题栏带 ⚠️）+ 改码后重启 GUI。

## 二、让"是否执行"与调试器解耦（这次最有用的一招）

```python
# parallel.py::forward 真身开头
if os.environ.get("SS_FF_BREAK") == "1":          # 硬停: 不依赖断点绑定, 必停一次
    try:
        import debugpy as _dbg
        if _dbg.is_client_connected(): _dbg.breakpoint()
    except Exception: pass
self.n_calls = int(getattr(self, "n_calls", 0)) + 1
if self.n_calls % 100 == 1:
    print(f"🧠 前馈加速器: MLP 真身执行 #{self.n_calls} (域内 {self.n_mlp} · 守卫 {self.n_guard})")
```
并把计数直接挂到老倪正在看的那行引擎进度日志（`state_space_sim_real.py` 每 25 步那行）:
`[25/4000] 阶段=… · YOLO 检出率 … · 前馈 MLP真身 26/守卫 0`；未启用时补
`(未启用: SS_USE_MLP≠1 → forward 被解析覆盖)`。
**诊断口径**: 日志 N>0 而断点不停 ⇒ 绑定/断点位置问题；N==0 ⇒ 档位/勾选问题（或函数根本没进）。
实测两臂: `SS_USE_MLP=1 → n_mlp=30/30 守卫 0 · n_calls=30`；`不设 → 0/0 · n_calls=-1（一次没进）`。

## 三、"很久才进断点" = 装配链耗时, 不是断点问题

实测（gui-venv311，`RealStateSpaceSim` 构造 + 直接 run）:
```
vision=True : import 0.98s → 构造(含 YOLO 对齐器) 2.13s → 第一次进 forward 3.52s
vision=False: import 0.92s → 构造                1.96s → 第一次进 forward 1.96s
```
所以引擎侧只要 2~3.5s；老倪体感的"几分钟"在**更前面的装配**：
`ensure_scene()` 生成场景 XML → worker 起 → L4 档默认勾 INTACT ⇒ 起 **INTACT 子进程 (独立 venv/py3.10)
+ 加载权重 + 首次真推理**（CPU 单步 ~0.11s）→ 勾「🧩 L2 兼容」再加载 **YOLO 对齐器**（历史实测首次
10~40s，主线程）→ 之后才 `run()` 第一步。
再叠加架构口径: **▶运行 = 引擎先同步跑完整轮（L4 档 4000 步），跑完才在画布逐节点回放** ⇒
断点是在"引擎阶段"停的，画布动画在其后，体感更长。
要快: 取消「🤖 L4 用 INTACT 节点执行」（走解析链，不起子进程/权重）或取消「🧩 L2 兼容」（省 YOLO 加载）。
给老倪的可选补救: 装配分阶段计时日志（画布就绪/场景 OK/权重加载完/首次推理/引擎开跑 各打时间戳）。

## 四、L4 档「L2 兼容」接线模式（档位内生效, 全局默认不动）

需求老倪原话: 「L2 功能应该和 L4 功能兼容，运行 L4 的时候 L2 也要运行」+「也要连线」+「L4 档加一个勾选框」。

```python
# tools/gui/simulink_module.py L4 装配块 (在 sim = RealStateSpaceSim(...) 之前)
_l4_cap = str(_cap or "").upper().startswith("L4")
_l2_compat = bool(_l4_cap and (not _demo_cap) and self._l2_compat_on
                  and os.environ.get("SS_L4_L2_COMPAT", "1") != "0")
if _l2_compat: os.environ["SS_USE_MLP"] = "1"      # 前馈 MLP 真身
else:          os.environ.pop("SS_USE_MLP", None)  # 非 L4/演示档: pop 回原状 = 零回退
```
- 视觉: `vision=((cap=="L3" and not _model_exec) or (cap.startswith("L4") and not _model_exec and _l2_compat))`
  —— 原来是 `vision=(cap=="L3")`，**这就是 L4 日志恒打「YOLO 未启动」的根因**（`_vis["shot"]`
  只在本帧真跑 detect_3d 时累加，日志分支 `if _v.get("shot") else "YOLO 未启动"`）。
- 勾选框三件套（老倪要求"工具按钮好使"）: 创建 `QCheckBox` + **`tl.addWidget(...)`**（FlowBar 与
  「🤖 L4 用 INTACT 节点执行」「🎯 L4 意图 → DiT 精炼」同排）+ 主线程读状态存 `self._l2_compat_on`
  （worker 线程不碰 QObject）；tooltip 里必须写**实测代价**与等效环境变量。
- 验收工具: `tools/verify_l2_compat_checkbox.py`（offscreen 11/11: 存在/文字/挂布局(FlowBar)/同排/
  默认勾选/tooltip 含实测数字/点击可切换/装配块读控件/状态参与判定/仍受环境变量约束）。
- 同口径 A/B (gui-venv311 · seed104 · 120 步 · cap=l4 · 每臂独立进程, `tools/ab_l4_l2_compat.py`):
  `臂A n_mlp=0 · YOLO 未启动 · 终点 0.42mm · 3.3s` ‖ `臂B n_mlp=120 · YOLO 240/240 100% · 终点 6.82mm (16×) · 6.9s`
  ⇒ **接线成功可验证但精度回退**（vision 后 YOLO 检测值替换 R0 真值 + MLP 在 seed104 分布边缘）
  ⇒ 按「未证明提升不进默认档」**默认关**；老倪明确要求 L2 在 L4 跑 ⇒ 最终做成**勾选框默认勾选 +
  tooltip 明写代价**（用户可见的取舍，而不是偷偷默认开）。
- ⚠️ `ultralytics` 只装在 **gui-venv311**（8.4.126），不在 `~/lerobot-venv` ⇒ 任何 lerobot-venv 跑
  `vision=True` 会 `ModuleNotFoundError: ultralytics`；跑 vision 相关 A/B 必须用 gui-venv311。

## 五、画布补线的两个教训（这次踩过）

1. **文本级插入后必须先 `json.loads` 验证再落盘**：本轮 desc 插入时多打一个引号把
   `flows/state_space_obs.json` 写坏过一次（JSONDecodeError at char 33255）。正确顺序 =
   `cp flows/x.json /tmp/flow_backup_$(date +%H%M).json` → 构造新文本 → **`json.loads(src2)` 断言通过**
   → 才 `open(p,"w")`；写完再逐字段对比旧连线（`json.dumps(sort_keys=True)` 逐条比）证明 0 变化。
2. **画布代价要同工具改前/改后量**（不能只说"加了两条线"）：`tools/verify_l4_layout.py`
   改前 `反向 2 · 重叠 0 · 穿框 44 · 交叉 145` → 改后 `反向 4 (+2, 均标 ↩) · 重叠 0 · 穿框 45 · 交叉 161 (+16)`。
   根因: L2 行在画布右侧 (前馈 x≈3826)、L4 行在左侧 (x=387) ⇒ 这两条天生反向（与既有
   SK04-08→执行器 5 条反向同源）；结构性修法 = 重排 L2 行位置（下一轮）。
   零回退仍按老规矩跑 `tools/verify_l4_zero_regression.py`（档位归属不变 · L2/L3/L4 执行集 55/60/77
   逐项不变 · 旧连线 0 丢失）。
