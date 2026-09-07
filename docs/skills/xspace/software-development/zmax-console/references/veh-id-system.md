# VEH-ID 显示体系 (2026-08-09 老倪定稿)

老倪用 VEH-ID 指代控制台任意卡片/控件, 对话时说 "VEH.5" = Simulink 页。**格式是点号: VEH.N.xx, 不是连字符。**

## 格式规则 (老倪多次纠正后定稿)
- 主页功能卡: `VEH.1` ~ `VEH.12` (点号, 无序号后缀)
  - 1数据集 2模型引擎 3硬件 4架构 5Simulink 6配置 7数据空间 8监控 9评估 10插拔 11版本 12产品大屏
- 页内控件: `VEH.N.xx` (卡号.顺序号), 顺序 = 布局上→下、左→右 (全局 y 优先, 再 x)
- 控件级 ID 只给 VEH.2 (模型引擎) 页做了; 其他页若要, 复用 `_veh2_apply` 模式改成 `_vehN_apply`
- 老倪说 "xxx" 必须能对上: 以后对话 "VEH.2.05" = 模型引擎页第 5 个控件

## 覆盖范围 (老倪: "所有 layout 的所有对象都要有 ID" — 但要排除容器类!)
- **真实可见控件全覆盖** (按钮/开关/下拉/输入/数值spinbox/表格/分组框/QLabel/QFrame)
- **⚠️ 必须排除容器类: QScrollArea / QScrollBar / 裸 QWidget 壳 (`type(w) is QWidget`)** — 末轮实测 76→41 个控件, 容器角标会盖住/干扰子控件角标, 用户报 "一个ID都没有" 的根因就是给容器也编号了
- QLabel 过滤: 空文字标签跳过 (图标占位), 以 "VEH." 开头的角标自身跳过 (防递归)
- 数值控件: `QAbstractSpinBox` 必须模块级 import, targets 里含它; `_holo_name/_holo_type/_holo_state` 三处都要补 spinbox 分支 (数值 x / 数值 / value)
- QLabel 也要补 name/type/state 三处 (标签)

## 位置 (老倪: "全都改到左下角")
- badge 统一左下角: `x=2, y=height - lbl.height - 2`
- 试过 "长条最右/方块右下" 被否 — 必须统一左下角

## ⚠️ Qt QSS 8 位 hex = #AARRGGBB (alpha 在【最前】)
- 写 `#00d4aacc` 想表达"青色+透明度" → 实际被解析成 alpha=00 (全透明) + rgb d4aacc → **完全看不见**!
- 正确: `#cc00d4aa` (alpha CC 在前) 或 `#aa00d4aa`
- 这是第二次踩 (记忆里有但写 QSS 时没查) — 写 8 位 hex 前必查
- 7px 小字 + alpha 前位 是可读底线: 5px 太小说 "一个都看不到", 10px 说 "太明显", 7px 合适

## 主页卡 VEH 徽标 (ModuleCard)
- 左下角常显, Consolas 7px bold, 灰色 (C_GRAY #8b949e), tooltip "与静静对话时用此 ID 指代本卡片"
- 由 `_modules_grid` 传 `veh_id=f"VEH.{idx+1}"` (12 卡按网格顺序)
- 走卡内布局 QLabel (不是 _holo_badge_overlay), 所以不受页级 hover_only 影响

## simulink 页 (VEH.5) 特殊规则
- **画布节点 ID 常显** (2026-08-09 定稿: 用户报\"画布节点上有常显文字 VEH.5.25\"后, 从 hover-only 改为**常显** — 节点左下角一直画 nid, 不依赖 `_hover`): `SimNodeItem.paint` / `CICDStageItem.paint` 里去掉 `if getattr(self, "_hover", False)` 门控, 无条件 drawText nid。nid = `lib_seq_of(node.name)` (与模块库一致), 回退才用 id 取模。
- 按钮等控件角标: `_holo_page_of(w) == "P11"` → hover_only (ID 进 tooltip 不常显)
- **⚠️ `_veh5_apply` 必须排除画布/场景**: `QGraphicsView` 及其 viewport 也要跳过 (`isinstance(w, QGraphicsView) or isinstance(w, QGraphicsView.viewport().__class__)`) — 画布节点 ID 纯由 SimNodeItem.paint 常显, 归 paint 管, 不归控件编号器管。画布节点是 QGraphicsObject 非 QWidget (`findChildren(QWidget)` 抓不到), 但 QGraphicsView 本身是 QWidget 会被编号污染画布区域。
- **⚠️ 用户连续报同一 ID 错误时先确认窗口版本**: 代码 offscreen 全绿 + 用户仍报旧值 (如连续 3 次报 VEH.5.22/25) → 先 `ps -o lstart= -p <pid>` vs `git log --format='%ci' -1` 对比进程启动时间与提交时间; 用户窗口可能是旧代码渲染 (旧 `id % 100` 对共享 id `n...525` 取模 = 25)。进程是最新的就请用户彻底关掉 Simulink 窗口/整个控制台重开 — 别反复改代码 (改 3 轮后发现是旧窗口的典型教训)。

## 实现位置 (tools/gui/studio.py)
- `_veh2_apply`: P03 页所有 QWidget 布局序编号, 每控件 `_holo_badge_overlay(w, f"VEH.2.{i:02d}", ...)` + 注册 `_holo_coords`
- `_holo_badge_overlay(w, h_id, hover_only=False, veh_small=False)`: 角标渲染; hover_only=ID 进 tooltip
- `_holo_apply_all` 先调 `_veh2_apply(root)`, 主循环跳过 P03 (防双重)
- `_VEH_PAGE` dict: 页 (P01..P12) → VEH 卡号; `_holo_seq_id` 输出 `VEH.{veh_n}.{seq:02d}` (取消旧 Pxx.xx.xx 系统)
- 旧手动 `_holo_badge(w, "B-01"/"M-01")` 包装已全部移除, 模式卡按钮去掉 `[M-xx]` 文字; btn_map 执行层兼容保留 (B-01/M-01 仍可执行真实控件)
- 页识别靠 objectName: TrainingModule `setObjectName("model_engine")` → `_holo_page_of` 认 P03
- **⚠️ HomeWidget 必须 `setObjectName("home")`** — 缺了它首页按钮被判 P00, `_holo_page_of(w) in ("P01","P11")` 永不命中 → hover_only 不生效 → 首页按钮一直常显污染 ("还是能看到ID" 真根因)。**任何页类 __init__ 都要 setObjectName(页名), 页识别失效先查它**

## ⚠️ 真根因: 缺 `lbl.show()` (窗口里"一个ID都没有")
父控件已显示时新建 QLabel 子控件默认 `isVisible()==False` → 角标创建了但从不渲染。
- `_holo_badge_overlay` 创建后**必须 `lbl.show()`**; `_holo_sync_badges` 里 `if not lbl.isVisible(): lbl.show()`
- 像素级验证: offscreen render 数 badge 色像素 >0 才证明真画出来了。注意按钮自身也有相近色边框会误报 — 以 `lbl.isVisible()` 断言为主
- 排查顺序: "没编号" vs "编号了但看不见" 用 offscreen 实例化查 `_holo_badge_lbl` 是否存在 + isVisible

## 字号迭代史 (老倪反馈驱动, 别再走弯路)
5px 太淡"一个都看不到" → 7px 太小"看不清" → 14px 贴纸"字太大覆盖原字体" → 10px 无背景纯青字 → **10px 无背景纯灰字 = 定稿**。
铁律: ID 要求 = 可见但不抢眼、不覆盖控件原文字。先做最小样式, 别上大字号/贴纸底。

## 颜色定稿 (老倪: "不要用绿色, 用背景色相似的灰色")
- badge 颜色 `C_GRAY` = `#8b949e` (贴近背景 #0d1117, 能看清不显眼)
- 主页卡 ModuleCard VEH 徽标同步灰色; simulink 节点 hover ID (QColor) 同步灰色 (#8b949e)
- 绿色系 (C_CYAN/#00d4aa/#00ffd0) 在 VEH-ID 体系里全部禁用

## v5→v7 显示分流演化 (最终形态)
- **v5**: `_is_big` 阈值 20000 → 大窗常显/小窗悬停 (模式卡也算大, 被否)
- **v6 (老倪: "小按钮灰色字很脏")**: `_is_big` 收紧 — QPushButton 一律 `return False` (永不常显), 仅 QGroupBox/QTableWidget/面积≥60000 常显。实测 41 控件 = 6 常显 + 35 悬停。铁律: **按钮上不要放常显 ID 文字 (哪怕灰色), 一律 tooltip**
- **v7 (老倪: "首页上面几个按钮被污染")**: 主循环 hover_only 扩为 `self._holo_page_of(w) in ("P01", "P11")` — 首页 hero 区 8 按钮 (smolvla_lew/同步/升级/Z-MAX/版本/解决方案/PPT汇报/分享) 悬停弹出, 不常显。功能卡 VEH.1~12 徽标不受影响 (卡内 QLabel, 不走 overlay)
- **v8 (老倪: "模型引擎所有ID都改成悬停, 你大部分把原有字遮挡了")**: VEH.2 (P03) 页**彻底取消常显** — `_veh2_apply` 删掉 `_is_big` 分支, 41 控件**全部** `hover_only=True`。定稿铁律: **ID 一律 tooltip 悬停, 页面零静态 ID; 常显只留给主页功能卡徽标 (VEH.1~12)**。分组框/表格这些"大窗口"也常显被否 — 老倪最终要的是干净页面
- **v9 (老倪: "VEH.0.01 也不要显示...全局规则一致")**: 主循环 `hover_only` 从 `("P01","P11")` 扩为**无条件 True** (所有页所有控件一律悬停, 不再按页区分)。VEH.0.x (objectName 未映射页的兜底 ID, `_VEH_PAGE.get(pg,0)`) 自然也悬停。两处调用点 (VEH.2 页 + 主循环) 都是 `hover_only=True`, `veh_small` 常显路径零残留 — 全局已无常显角标
- 经验: 页面顶部 hero 行按钮最容易被 ID 角标污染 — 常显角标只留给主页功能卡徽标; 页级 hover_only 判断 (P01/P11) 最终也被全局化吞并, 别再做按页分支

## VEH.2 页布局定稿 (2026-08-09 老倪: VEH.2.17 全高 / VEH.2.01 取消拖动条)
- **VEH.2.17 = 配置表 zoo_table**: 表格自身 `setMinimumHeight(n_rows*28+30)` 已是内容全高 (18行≈534px), 但被 param_scroll 视口截断 → 用户说"太小要拖动"
- **⚠️ showEvent 覆盖坑**: `showEvent` 里有 `screen.height()//3` 动态覆盖 param_scroll 最小高度 (offscreen/小屏下≈200) — 这是"设了 600 却读回 200"的真根因。已改为 showEvent 里直接 `setMinimumHeight(600)` (表格 534 ≤ 600 默认全展开)
- **VEH.2.01 取消拖动条**: param_scroll 垂直滚动策略 `AsNeeded → AlwaysOff`; log_text 最小高度 600→200 给表格腾空间 (日志可折叠 btn_log_collapse)
- 页面整页 scroll_area 保留 (1414 vs 900 视口, 下方按钮/日志仍需可到达) — 只关内层 param_scroll 的滚动条

## 其他页 VEH.N ID (2026-08-09: VEH.3 硬件页落地)
- 老倪要求硬件工具箱页(VEH.3)也加 ID, 之前只有 VEH.2 有。**任何页要 VEH.N ID 只需两步**:
  1. 页类 `__init__` 里 `setObjectName("<页名>")` (HardwareModule 用 "hardware") → `_holo_page_of` 认 P05 → `_VEH_PAGE` 给 VEH.3
  2. `_holo_apply_all` 全局遍历自动编号 (targets 类型内控件) — 无需写 `_vehN_apply`
- **⚠️ 页内独立序号 (v10)**: 原 `_holo_seq_id` 用全局 `_holo_seq` 递增 → VEH.3 从 73 起 (被其他页占位), 用户要 VEH.3.01 起。改为 `_holo_page_seq = {}` 按页计数:
  ```python
  seq = self._holo_page_seq.get(pg, 0) + 1
  self._holo_page_seq[pg] = seq
  return f"VEH.{veh_n}.{seq:02d}"
  ```
  `_holo_apply_all` 开头重置 `self._holo_page_seq = {}`。VEH.2 用 `_veh2_apply` 自编号不受影响。
- 硬件页实测 26 控件: 下拉/按钮/表格/输入框/急停/塔灯状态按钮全悬停, VEH.3.01~26。
- 塔灯按钮(🔴🟡🟢⚫)与夹爪/机械臂按钮都在 `_make_hw_btn` 创建 — 属 QPushButton, 自动编号。

## VEH.1 数据集页 (2026-08-09 落地)
- `DatasetModule.__init__` 加 `self.setObjectName("dataset")` → `_holo_page_of` 认 P02 → `_VEH_PAGE` P02=1 → VEH.1
- **⚠️ 首页冲突**: `_VEH_PAGE` 原 P01(首页)和 P02(数据集)都=1 → 首页按钮混进 VEH.1 编号 (VEH.1.04 "🌐 Z-MAX" 是首页控件)。修复: P01 改 0 + `_holo_apply_all` 主循环 `if self._holo_page_of(w) == "P01": continue` (首页导航不编号, VEH.1 仅数据集页)
- 实测 89 控件 VEH.1.01~89

## ⚠️ VEH.4 架构页 — QLabel/QFrame 页面必须写独立 _veh4_apply (纠正"两步法")
- ArchitectureModule 全是 QLabel + QFrame 卡片, **没有 QPushButton/QComboBox → 全局 targets 分支覆盖不到** (实测 arch.findChildren(QPushButton) 为空 → VEH.4 一个都没有)。两步法只对标准控件页有效。
- 正解: 仿 `_veh2_apply` 写 `_veh4_apply` (独立方法):
  1. `ArchitectureModule.__init__` 加 `setObjectName("architecture")`
  2. `_holo_page_of` 映射加 `("architecture", "P13")`; `_VEH_PAGE` 加 `"P13": 4`
  3. `_holo_apply_all` 开头调 `self._veh4_apply(root)` (和 _veh2_apply 并列)
  4. `_veh4_apply` 遍历 P13 控件, 按 y→x 排序编号 — 过滤规则 (踩过 3 轮):
     - `w.objectName() == "architecture"` 跳过 (页面自身)
     - `type(w) is QWidget` 跳过 (裸壳)
     - **QFrame 且 `w.layout() is not None or w.children()` 跳过** (容器卡片, 给叶子编号; 第一版空 QFrame 过滤后 21 个全是容器)
     - QLabel 空文字/以 VEH. 开头跳过
- 实测 39 控件 VEH.4.01~39 (标题/层级标签/卡片文字/流程条)

## VEH.5 Simulink 页 — 独立窗口自身编号 (2026-08-09 落地)
- SimulinkModule 在 **另一个文件** `tools/gui/simulink_module.py`, 是独立窗口 (studio.py `self.simulink = SimulinkModule()`), **不走 studio 全局 _holo_apply_all** — 两步法无效
- 正解: SimulinkModule 自身 `_veh5_apply`:
  ```python
  self.setObjectName("simulink")  # __init__ 里
  def _veh5_apply(self):
      # 遍历 self.findChildren(QWidget), 布局 y→x 排序
      # 跳过: 自身/裸QWidget/滚动区/容器QFrame(有layout或children)/空QLabel/VEH.开头
      # 编号 f"VEH.5.{i:02d}", 每控件 w.setToolTip(f"{h_id} — {class名}")
      # 存 self._veh5_ids[id(w)] = h_id
  def showEvent(self, ev):  # 窗口显示时触发一次 (self._veh5_done 防重复)
  ```
- 注意 `VEH.5.{i:02d}` 三位数自动扩展 (VEH.5.100+ 正常, 187 控件 VEH.5.01~187 连续)

## ⚠️ VEH.5 模块库 ID 与画布节点 ID 必须一致 (2026-08-09 老倪: "数据一致")
- 用户明确要求: **左侧模块库的 ID 与画板上的模块 ID 要数据一致** (同一模块两边同号)。曾出现: 库 SYS2=VEH.5.105 但画布 SYS2=VEH.5.22, 且多个节点撞号 VEH.5.22 (随机数取模)
- 根因: 画布节点 id = `gen_id()` (n+时间戳+3随机), 显示 `VEH.5.{id % 100:02d}` 对长字符串取模 → 随机散乱 + 撞号
- 正解: `LIBRARY_SEQ` 映射 (LIBRARY 定义后遍历生成 name→稳定序号) + `lib_seq_of(name)`:
  ```python
  LIBRARY_SEQ = {}
  _lib_seq = 0
  for _gtype, _gname, _items in LIBRARY:
      for _it in _items:
          _lib_seq += 1
          LIBRARY_SEQ[_it["name"]] = _lib_seq
  def lib_seq_of(name): return LIBRARY_SEQ.get(name)
  ```
- 画布节点 nid 显示: `f"VEH.5.{lib_seq_of(node.name):03d}"` (未找到回退原取模逻辑)
- 模块库按钮: `btn.setText(f"⬡ {name} · VEH.5.{seq:03d}")` + tooltip 同号 — **按钮文本和画布节点显示同一序号**
- 实测: SYS2 云端训练 = 65 → 两边都 VEH.5.065

### ⚠️⚠️ VEH.5.22 有两个独立真身来源 (用户反复追问 "VEH.5.22 到底是什么" 的完整答案)
**来源 A — 画布节点回退随机撞号**:
- `gen_id()` 生成 `n<时间戳><3随机>`; **模板加载 (load_reference_app) 时所有节点可能共用同一个 id** (offscreen 实测 7 个节点 node.id 全相同 n1786262826525!) → `f"VEH.5.{id % 100:02d}"` 对同一字符串取模 → **全部节点同号 VEH.5.22**
- 修复必须**消除回退路径**: 不只 LIBRARY 项要注册, **REFERENCE_APPS 模板节点名也要注册进 LIBRARY_SEQ** (三层总系统的 "🧠 SYS1 动作系统"/"📦 数据集合"/"🖥 GPU 服务器"/"🔬 Model Zoo"/"🔧 硬件配置" 原不在 LIBRARY → lib_seq_of None → 回退):
  ```python
  for _app in REFERENCE_APPS:
      for _n in _app[1]:
          _nm = _n[1]
          if _nm and _nm not in LIBRARY_SEQ:
              _lib_seq += 1
              LIBRARY_SEQ[_nm] = _lib_seq
  ```
  验证: 遍历全部 12 个 REFERENCE_APPS 节点名 `lib_seq_of` 全非 None (MISSING_COUNT 0) + 总系统 7 节点 nid 无重复
**来源 B — _veh5_apply 通用编号器覆盖模块库按钮 tooltip**:
- `_veh5_apply` (控件通用编号, VEH.5.{i:02d} 从 01 起) 遍历 `self.findChildren(QWidget)` 给**所有**控件设 tooltip → **把模块库按钮的 lib_seq tooltip (VEH.5.065) 覆盖成通用序号 (如 VEH.5.22/32)** → 用户 hover 模块库按钮看到 22 ≠ 画布 065
- 修复: `_veh5_apply` 开头收集模块库按钮 id 集合, 循环里跳过:
  ```python
  _lib_btn_ids = set(id(b) for b in getattr(getattr(self, "library", None), "_lib_btns", {}).values())
  ...
  if id(w) in _lib_btn_ids:
      continue  # 模块库按钮用 lib_seq 编号, 与画布一致
  ```
- 排查顺序: 用户报 "ID 不一致" → 先 grep 谁在设 tooltip (`_veh5_apply` 的 `w.setToolTip(f"VEH.5.{i:02d}...")` 是唯一会覆盖的), 再查画布 paint 的 nid 回退路径。**两套编号系统并存时必须用 id 集合隔离, 否则后执行的覆盖先执行的**
- **⚠️ 先问清"ID 出现在哪"再动手**: 同一报错 ("VEH.5.22/25 不对") 有多个独立来源 (tooltip / 画布 hover 小字 / 画布常显文字)。offscreen 全绿 ≠ 用户窗口正确 — 用户报"还有"时先问或让其明确: 是悬停 tooltip 还是节点上常显文字? 画布节点 ID 从 hover-only 改常显后, 用户能看到的就是 paint 里的 nid, 别只查 tooltip 路径。

### ⚠️ CICD 流水线环节 sid 是字符串 (2026-08-09 顺手修)
- `CICDStageItem.sid` = "collect"/"train"/"validate"/"integrate"/"deploy"/"infer" (**字符串不是数字**), 原显示 `f"VEH.5.{self.sid % 100:02d}"` → `%` 对字符串 TypeError → 被 try/except 吞 → ID 不显示 (静默)
- 修复: CICD 环节标题 ("① 采集"...) 也注册进 LIBRARY_SEQ 续号, 回退 `f"VEH.5.CICD.{self.sid}"`

## ⚠️ 总系统模板: 画布模块必须与模块库一一对应 (2026-08-09 老倪铁律)
- 用户要求: **总系统里的所有模块, 必须要从模块库里得到** — 即 REFERENCE_APPS 模板每个节点名在 LIBRARY 里必须有同名条目 (画布拖入的块都能在左侧模块库找到)。
- 落地: 三层总系统缺失的 "🧠 SYS1 动作系统" / "🖥 GPU 服务器" / "🔬 Model Zoo" / "🔬 总系统" / "📦 数据集合" / "🔧 硬件配置" / "📦 metaworld_peg" 补进 LIBRARY (新分组 "🏗 三层总系统组件" system 类 + "🧩 结构条件变体" coord_overlay 类); Model Zoo 每模型行的 "🧩 结构条件 · ACT/SmolVLA/LEW/VLA-Touch/AWE" 变体也补。
- 验证: 遍历全部 REFERENCE_APPS 节点名 `lib_seq_of` 全非 None (MISSING_COUNT 0) 才算齐。
- **⚠️ LIBRARY 与 REFERENCE_APPS 条目格式不同**: LIBRARY 是 `{"name": ..., "params": {...}}` dict; REFERENCE_APPS 是 `(ntype, name, params)` 元组。用 find 定位插入点时别把 REFERENCE_APPS 里的同名项 (如 "🧩 结构条件") 当 LIBRARY 位置 — 曾把变体插进 REFERENCE_APPS 导致 LIBRARY 计数不变 (134)。定位 LIBRARY 内位置用 `src.find("LIBRARY = [")` 之后找, 插入后验证 `len(LIBRARY_SEQ)` 增长。

## 🏗 总系统模板重写 (2026-08-09 老倪拍板: 只表达 SYS2 云端训练 → 部署 → SYS1)
- 用户指令: "删掉总系统 VEH.5.15 的内部所有功能块, 重写; 系统2是用于云端训练, 训练好的模型部署到系统1; 你表现出这个就可以了, 不画别的"
- 定稿: "🏗 三层总系统" 模板 = **2 节点 + 1 部署链路**: `🖥 SYS2 云端训练` (顶, layer sys2) → `🧠 SYS1 动作系统` (底, layer sys1), link `(0, 1, "部署")`, 两行横排 layout。**删掉**: 数据集合 / GPU 服务器 / Model Zoo / SYS0 硬件驱动 / 硬件配置 (全部功能块)。
- 验证: offscreen `load_reference_app_by_name("🏗 三层总系统")` → len(nodes)==2, len(links)==1, names 精确等于 [SYS2, SYS1]。

## ⚠️ Simulink 深色主题悬停黑字看不清 (2026-08-09)
- 症状: 左侧模块库按钮深色主题下 hover 变黑底黑字 (用户: "字体黑色背景也黑色看不清")
- 根因: `switch_theme` 的替换对 `pairs` 只含 `("#dbe9ff", "#1a2230")` (hover 底色), **漏了 hover 文字色 `#1f2328`** → 深色下底色变深但文字仍是深色
- 正解: pairs 追加 `("#1f2328", "#c9d1d9")` (hover 文字色深色下变浅)。THEMES 里 `#24292f→#c9d1d9` 已有 (非 hover 文字), 但 hover 伪类的 `#1f2328` 不在 THEMES key 里必须手动补
- 排查: 深色 UI 看不清 → grep 按钮样式里所有深色 hex (`#1f2328/#24292f`), 逐个确认在替换对里

## VEH.0 首页落地 (2026-08-09 老倪: "首页也都加上 ID 用 VEH.0.序列号, 鼠标悬停弹出")
- 之前 VEH.0 只是 objectName 未映射页的兜底 ID (`_VEH_PAGE.get(pg,0)`) 且被跳过; 用户明确要求首页正式编号 VEH.0.xx。首页 = ModuleCard(QFrame) + QLabel + 按钮混合, 通用 targets 分支覆盖不到 ModuleCard → 必须写独立 `_veh0_apply` (仿 _veh4_apply)。
- 落地: ①`_veh0_apply` 定义 ②`_holo_apply_all` 开头调 `self._veh0_apply(root)` (与 _veh2/_veh4 并列) ③P01 在 `_VEH_PAGE` 已=0 → 自动 VEH.0
- **⚠️ 坑1 — 侧栏控件误编 VEH.0**: SystemSidebar 等 parent 链无 objectName 的控件, `_holo_page_of` 返回 P00 → `_VEH_PAGE.get("P00", 0)` = 0 → **通用分支把它编成 VEH.0** (offscreen 首测 179 个里混入 "◀ 收起"/"← 返回首页" 等侧栏按钮)。修复: 通用分支 `if _pg == "P00" or _pg is None: continue` (未识别页不编号, VEH.0 只由 _veh0_apply 产生)
- **⚠️ 坑2 — _veh0_apply 必须严格限定 parent 链**: 不能只靠 `_holo_page_of(w) == "P01"` (侧栏按钮 parent 链断, 判不出 P01, 会漏)。必须: 先找 `home_w` (objectName=="home" 的 HomeWidget), 再沿每个控件 parent 链 `while _p is not None: if _p is home_w: in_home=True` — 不在 HomeWidget 内直接 continue
- 过滤规则同 _veh4_apply: 页面自身 (`w.objectName()=="home"`) / 裸 QWidget / 滚动区 / 容器 QFrame(有 layout 或 children 且非 ModuleCard——**ModuleCard 是要编号的功能卡**) / 空 QLabel / "VEH." 开头
- 实测: 179 控件 VEH.0.01~99+ (三位数自动扩展), NOT_IN_HOME=0 (全首页, 无侧栏混入)
- 验证: offscreen 遍历所有 VEH.0 控件沿 parent 链确认 `p is home_w`, 断言 NOT_IN_HOME==0 — 比数个数更能抓"混入"

## 💾 模块库加载用户保存的工作流 JSON (2026-08-09: flows/system.json)
- 用户在画布上搭好总系统后保存为 `flows/system.json` (格式 `{format, nodes[], links[]}`, 5 节点含位置), 要求模块库"🔬 总系统"点击加载它, 而非代码内置模板
- 落地: ①LIBRARY 项加 `"flow": "flows/system.json"` 字段 ②模块库点击逻辑先判 `it.get("flow")` → `self.module.load_flow_file(fl)` (优先于 template) ③新方法 `load_flow_file(path)`:
  - 解析 JSON → 逐节点 `self.add_node(type, name, x, y, params)` 恢复位置 → 记 `id_map[spec["id"]] = n["id"]`
  - 恢复连线: **`add_link(src_item, dst_item)` 要 item 对象不是 id** — `fi = self._items.get(f); ti = self._items.get(t); self.add_link(fi, ti, spec.get("label"))` (第一版传 id 导致 links=0 的坑)
  - 加载期间 `self._sync = lambda: None` + `_suspend_undo = True`, finally 恢复 (同 load_reference_app 性能铁律)
- 验证: offscreen `load_flow_file("flows/system.json")` → len(nodes)==5, len(links)==5, 链路 metaworld_peg→SYS2→SYS11+SYS12→Scope

## 🔀 节点改名必须三处同步 (2026-08-09: Z-Flow→引导系统 / VLA-T→动作系统)
- 老倪: "VEH.5.066 Z-Flow 改成 引导系统, VEH.5.067 VLA-T 改成 动作系统" — 改名 = 模板节点名 + LIBRARY name + layout 数组**三处同步** (各 2 处 = 6 处改动)
- LIBRARY_SEQ 由 LIBRARY 构建自动跟随新名 (无需手动改映射); 旧名 `lib_seq_of` 返回 None 即验证改名成功
- 注意: `lib_seq_of("🖐 SYS11 动作系统")` 用 🖐 手 emoji — 测试脚本里 emoji 转义写错会误报 None, 先 `for k in LIBRARY_SEQ if 'SYS11' in k` 确认实际 key

## ⚠️ flow JSON 加载: row_bg 背景节点必须垫底 z=1 (2026-08-09: model_zoo.json 颜色模糊)
- 症状: 加载 model_zoo.json 后节点颜色模糊 — 用户问"是因为背景在前面么?" (是的, 正是)
- 根因: `SimNodeItem.__init__` 里 `self.setZValue(10)` 对所有类型生效; model_zoo.json 的 8 个 row_bg 背景节点 (🎨 YOLO 3D/ACT/SmolVLA/... 每模型一行, 半透明色带 params.bg=#3a5a7a) 在 JSON **索引末尾** → `load_flow_file` 按序 add_node → **row_bg 后加, 同 z=10 渲染在正常节点上面** → 半透明色带盖住节点 → 颜色变模糊
- 修复 (一处): `self.setZValue(1 if node.get("type") == "row_bg" else 10)` — row_bg 垫底 z=1, 正常节点 z=10, 连线 z=5 居中
- 验证: offscreen `load_flow_file("flows/model_zoo.json")` → 遍历 `m._items` 断言 `row_bg z=={1.0}` 且 `正常节点 z=={10.0}` (71 节点: 8 row_bg + 63 正常)
- 教训: 场景里"背景层/装饰层"节点 (row_bg/bg) 必须显式低 zValue, 不能和内容节点同层 — 加载顺序决定同层渲染先后, JSON 里背景常排在末尾 → 盖内容

## 验证方法 (offscreen 冒烟)
```python
QT_QPA_PLATFORM=offscreen
m = TrainingModule(); m.resize(1400,900); m.show(); app.processEvents()
m._holo_coords = {}; m._holo_seq = 0; m._holo_applied = set()
m._veh2_apply(m)  # 或 _holo_apply_all(m) 测全页
# 断言: 目标控件 hasattr(w, "_holo_badge_lbl") 且 isVisible(); _holo_coords 有 VEH.2.xx 映射
# 区分"没编号" vs "编号了看不见": badge label 存在但 isVisible=False = 缺 show()
```

## ⚠️ 嵌套验证脚本 tempfile 陷阱 (犯 5 次的 NameError)
execute_code 里写嵌套子脚本 (hermes-verify- 前缀) 做 offscreen 验证时: **子脚本内部用 `tempfile.mkstemp` 必须自己在子脚本里 `import tempfile`** — execute_code 外层已 import 不代表子进程继承。症状: 子脚本跑一半 `NameError: name 'tempfile' is not defined` → 验证脚本 exit 1 但静态断言全过 (误导)。
两个稳法:
1. 外层 `fd, path = tempfile.mkstemp(prefix="hermes-verify-", suffix=".py", dir="/tmp")` 写文件 → 子进程 `/usr/bin/python3 path` → 跑完 `os.remove(path)`
2. 子脚本里自 `import tempfile` — 但子脚本 body 常是拼接字符串, 第一行忘加就踩坑
排查: 验证脚本 exit 1 + STDERR NameError → 不是被测代码问题, 是脚本自身 import 缺失 — 别去改被测代码。

## 📌 相关: 原子技能→条件编码 (ControlNet)
设计定稿在 `references/atomic-conditions-controlnet.md`: flows/ 双生成器 (gen_atomic_conditions.py → 242 条 11 通道条件编码; gen_atomic_flow.py → 251 节点 Simulink DAG), 双击 🧩结构条件节点注入。两个 JSON 用途不同: 条件库 (list) 不能直接 load_flow_file, 要生成 DAG 版。
