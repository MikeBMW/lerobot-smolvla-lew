# 2026-08-06: UI 清理 + 浮动还原 + pal 崩溃 + 分组/终端折叠 (commits be1ba44a/11cf1249/2ef33199)

## 🐛 浮动窗口关闭后画布还原露灰色空白 (be1ba44a)
老倪: "浮动按钮打开浮动窗口后, 关闭后, 就回不到原来的状态了, 背景露出一个灰色空白"
**根因**: `_restore_canvas` (浮动窗口 closeEvent → 还原画布回 MDI) 重建 `_canvas_win` 时:
1. **`show()` 而不是 `showMaximized()`** → 子窗口只有 920x620, 不铺满 MDI → 灰色背景露出
2. 保留标题栏按钮 (最小化/最大化/关闭) — 与主窗口创建处不一致

**修复** (与 __init__ 里主画布创建完全一致):
```python
self._canvas_win = QMdiSubWindow()
self._canvas_win.setWidget(self.canvas)
self._canvas_win.setWindowFlags(
    self._canvas_win.windowFlags()
    & ~Qt.WindowMinimizeButtonHint & ~Qt.WindowMaximizeButtonHint
    & ~Qt.WindowCloseButtonHint)          # 去标题栏按钮
self._canvas_win.setWindowTitle("🖥 画布 · Simulink 模型")
self._mdi.addSubWindow(self._canvas_win)
self._canvas_win.showMaximized()          # ← 铺满 MDI, 不露背景
self._mdi.setActiveSubWindow(self._canvas_win)
```
**规律**: 所有重建画布子窗口的路径 (init + _restore_canvas) 必须同一套 flags+showMaximized;
只改一处另一处必露馅 (用户实际操作到浮动功能才发现)。

## 🖥 画布窗口标题栏按钮"点击没用" (老倪反馈)
QMdiSubWindow 的 最小化/最大化/关闭 按钮在 WSLg 下点击无效, 且关闭后画布消失难以恢复
(WA_DeleteOnClose=False 只是隐藏) → 用户困惑"这按钮干啥的? 点击也没什么用"。
**处理**: 直接去掉这三个按钮 (windowFlags & ~...), 画布始终铺满不可误关 — 比"可恢复"
更符合用户直觉。教训: WSLg 下 MDI 子窗口标题栏按钮不可靠, 别给核心画布留关闭口。

## 🐛 SimLinkItem.paint NameError: 'pal' 未定义 — 主题字典残留引用 (11cf1249)
**发现途径**: kill GUI 进程时 stderr 刷出 `NameError: name 'pal' is not defined` (反复崩溃)。
**根因**: paint() 里 `color = QColor(pal["inactive"])` — `pal` 是旧主题色字典, 主题系统
改版 (THEMES[_CUR_THEME]) 时删了局部 pal, 但 SimLinkItem.paint 的引用没清。
SimNodeItem.paint / row_bg paint 开头有 `pal = THEMES[_CUR_THEME]` 所以不崩 — 只有
SimLinkItem 漏了定义却还在用。
**修复**: 未选中链路直接 `QColor("#8b949e")`, 不再引用已删字典。
**教训**:
- 渲染类代码改主题/删变量后 **全局 grep 残留引用** (`grep -n 'pal\['`), 别只改定义处
- **kill GUI 进程的 stderr 是免费运行时诊断** — 用户日常操作不崩 (分支未走到) 不代表
  代码没 bug; 重启/杀进程时刷出的 Traceback 要当正式 bug 修, 不是噪音
- 验证时断言"非注释行无引用" (`not any('pal["inactive"]' in l for l in code_lines if not l.strip().startswith("#"))`),
  注释里保留的 bug 说明文字不算残留

## 🗑 删 UI 行/模板时检查依赖方法 (11cf1249 + 参考应用删模板)
**删工作流过滤按钮行** (「① 访问·标注数据…⑥ 集成·测试」6 个白色按钮, 老倪: 没用删掉):
- 删 UI 按钮行后, `_filter_library` 方法仍遍历 `self._wf_btns` → 被调用会 AttributeError
  (无 UI 入口不调用, 但保险起见连同方法一起删, 保留 `LibraryPanel.set_filter` 内部用)
- 模块库 hint 文案 "顶部工作流过滤" 同步去掉

**删参考应用模板** (「⚙️ CI/CD 默认流水线」+「📦 取料·100G 闭环」, 老倪: 没用删掉):
- ⚠️ `open_cicd_panel` 硬编码 `load_reference_app("⚙️ CI/CD 默认流水线", ...)` — 删模板
  后该调用找不到名字 → 改成 `load_reference_app(REFERENCE_APPS[0][0], REFERENCE_APPS[0][1], ...)`
  (CICD 主控台在索引 0)
- 删模板前 grep 全仓引用: `grep -n "模板名" tools/gui/*.py` — 模板名可能被 open_*/LIBRARY
  引用; LIBRARY 里的原子模块按钮 (如 "A01 取料·100G") 与模板同名但独立, 可保留
- 参考应用条按钮数 = REFERENCE_APPS 数, 删后 offscreen 断言 `len(w._ref_btns) == 11`

## 🚨 老倪说"没用就删掉"= 删整个 UI 行, 不是删个别条目 (fbc629d9, 第 2 次反馈"还没删掉?")
**复盘**: 老倪先反馈"参考应用这行白色按钮为什么搞这么多? 跟上边带颜色的按钮重复了" —
我理解成"删重复模板", 只删了 2 个 (CI/CD 默认流水线 + 取料·100G), 保留其余 11 个。
老倪追问"参考应用 这行, 还没删掉?" — 才意识到他要的是**整行参考应用条消失**。
**规律**: 老倪对"一行 UI"(横向按钮条/工具栏行) 说"没用/重复/删掉"时,
= **整行删除**, 不是按重复度修剪。彩色工具栏 (tl2) 已有入口的模板功能全覆盖,
白字参考应用条就是冗余 — 直接删 UI 渲染代码, 数据保留。
**正确做法** (fbc629d9):
- 删 `outer.addWidget(ra)` 整个 ra=QFrame 块 (~40 行: ra/ral/ra_lab/ra_scroll/ra_inner/_ref_btns 循环)
- **REFERENCE_APPS 数据保留** — 模块库 LIBRARY 的完整模型条目
  (`it.get("template")` → `load_reference_app_by_name`) 和
  `load_reference_app`/`load_reference_app_by_name` 都还用它, 只删 UI 行
- `_ref_btns` 删除后 grep 确认无残留引用 (它是 UI 渲染专用, 无其他消费者)
- 验证: ① 界面无「参考应用」QLabel 文字 ② 8 个彩色入口 (open_compare3/5, vlatouch,
  awe, topsys, act_meta, pipeline, cicd) 方法仍在 ③ `load_reference_app_by_name("🔬 五模型对比")`
  仍返回 True ④ open_compare5() 加载 ≥30 节点
- 顺带: 用户连续 2 轮对同一 UI 行提意见时, 直接整行删, 别修修补补再等反馈

## 📚 模块库分组折叠 (点击分组标题, be1ba44a 内)
老倪: "模块库左侧的 System2/Sys-12 这些列表栏也要能隐藏" — 不是整个库, 是**每个分组**。
`_rebuild()` 渲染 LIBRARY 分组: 每组一个 QLabel 标题 (gname) + 组内 QToolButton 按钮。
实现:
```python
# 状态: self._group_collapsed = {}   (dict gname→bool, 实例属性, rebuild 前初始化)
collapsed = self._group_collapsed.get(gname, False)
marker = "▸ " if collapsed else "▾ "
lab = QLabel(f"{marker}{gname}")
lab.setCursor(Qt.PointingHandCursor)
lab.mousePressEvent = lambda ev, gn=gname, lbl=lab: self._toggle_group(gn, lbl)
# 组内按钮: btn.setVisible(not collapsed)
```
`_toggle_group(gname, lab)`: 翻转状态 → `lab.setText(f"{'▸ ' if collapsed else '▾ '}{gname}")`
→ 遍历 LIBRARY 找同 gname 的 items → `self._lib_btns[it["name"]].setVisible(not collapsed)`。
**状态保持**: `_group_collapsed` 存实例属性, set_filter/rebuild 后按它恢复 marker+可见性。
注意: 组名可能重复跨 ntype (同一 gname 多个 type) — toggle 用 gname 匹配即可。

## 📋 终端日志区折叠 (studio.py TrainingConsole, 2ef33199)
老倪: "下面的终端窗口, 也要能隐藏" — TrainingConsole 底部 "Training Log" 区
(QGroupBox + QTextEdit, layout.addWidget(log_group, 1) stretch 占大部分)。
**QGroupBox 标题不能内嵌按钮** → 改 QWidget + 自绘标题行:
```python
log_group = QWidget()          # 替换 QGroupBox(" Training Log ")
log_outer = QVBoxLayout(log_group)
log_head = QHBoxLayout()
log_head.addWidget(QLabel("📋 Training Log"))
log_head.addStretch()
self.btn_log_collapse = QPushButton("◀ 收起")   # 蓝色醒目 (同左侧栏折叠 v2 偏好)
self.btn_log_collapse.clicked.connect(self._toggle_log_area)
log_head.addWidget(self.btn_log_collapse)
log_outer.addLayout(log_head)
log_outer.addWidget(self.log_text)
```
`_toggle_log_area`: log_text.isVisible() → setVisible(False) + 按钮 "▶ 展开", 反向恢复。
折叠后 QTextEdit 隐藏 → 容器塌缩到标题行, 上方内容 (进度条/参数) 占满。

## 关联
- 左侧栏折叠 v1/v2 + 训练步数 50→10 → 2026-08-06-lib-collapse-steps10.md
- 视频窗口 5 同屏/元信息/循环 → 2026-08-06-video-window-fix.md

## 🗑 删工具栏按钮: 连带删方法 + grep 运行时引用 (c2c17658/4401d6ae, 第三波清理)

老倪连续逐个点工具栏按钮问"这干啥的? 没用删掉" — 规律是**逐个清理冗余按钮**:

| 按钮 | 删除原因 | 连带删除 |
|---|---|---|
| 「🪟 画布窗口」 | 画布子窗口已不可最小化/关闭 (be1ba44a 去按钮) → show_canvas_win 恢复逻辑无存在必要 | 按钮 + `show_canvas_win` 方法 |
| 「时间 10.0s / dt 0.010」 | 仿真参数 QDoubleSpinBox, 纯 UI 无逻辑价值 | 控件组 (含"时间"QLabel) |
| 「📚 模块库」(tl2) | 面板内已有 ◀ 收起, tl2 按钮冗余 | 按钮 + `_toggle_lib_btn` 方法 |
| 「🖥 Scope」(tl) | Scope 已移入 node 库 (见下节), 工具栏入口冗余 | 按钮 (show_scope/on_scope 保留) |

**🚨 最大坑: 删控件必须 grep 运行时读取点, 不只 UI 引用**。
删掉 sp_dt/sp_t_end 控件后, `start_sim` 里 `self._sim_dt = self.sp_dt.value()` 仍引用
→ 点 ▶运行 就 AttributeError。修复:
```python
self._sim_dt = getattr(self, "_sim_dt", 0.02)      # 控件已删, 用内部默认值兜底
self._sim_t_end = getattr(self, "_sim_t_end", 10.0)
```
**删 UI 三步清单**: ① 删按钮/控件创建+addWidget ② 删回调方法 ③ `grep -n "名字"` 全文件
(含 start_sim/step_sim 等运行时方法, 不只 UI 构造区)。删按钮时 btn 创建处与
addWidget 处可能不相邻 — 两处都要清, 否则残留 `tl.addWidget(self.btn_xxx)` 报错。
验证: 断言 `not hasattr(w, "btn_xxx")` + 实例化不崩 + 触发原按钮回调路径 (如 start_sim) 不崩。

## 📊 Scope 移入左侧 node 库 (db19e223 + 5dc3ed4d)

老倪: "Scope应该放到左侧的node库里，可以直接拖到主窗口" → LIBRARY 新增独立分组:
```python
("system", "📊 评估 (3)", [
    {"name": "📊 Scope 示波器", "params": {"scope": True}, "desc": "双击 → 示波器..."},
    {"name": "📊 对比评估 Scope", "params": {"shared": True}, "desc": "♻ 共用对比图表"},
    {"name": "🎥 推理效果对比", "params": {"video": "all", "auto": True}, ...},
]),
```
然后老倪 "scope还在工具栏呢?" → 工具栏 btn_scope 删除, 只留库入口。

**新节点进 LIBRARY 的完整链路** (无需新代码, 走既有机制):
1. LIBRARY 加条目 (type 用现有 NODE_TYPES 如 "system"; params 带触发标记如 scope/video)
2. LibraryPanel 点击 → `add_node_at_center(ntype, name, params)` 建节点
3. 双击节点 → `on_node_activated` → NODE_RUN_ACTIONS 名称关键字匹配
   (`("Scope", "on_scope")` / 视频分支 `params.get("video")` → on_infer_video)
4. node_logic.py 已有 node_scope 注册 (关键字 ["Scope"]), 无需改
验证: LIBRARY 分组在 → add_node_at_center 添加 → NODE_RUN_ACTIONS 含关键字 → 库按钮
点击后节点+1 → 分组折叠仍工作。

**🔑 验证时区分工具栏 vs 库按钮**: `findChildren` 会同时找到两者 —
- 工具栏按钮 = QPushButton (mk_btn 创建, **无 ⬡ 前缀**)
- 模块库按钮 = QToolButton (**⬡ 前缀**: "⬡  📊 Scope 示波器")
断言"工具栏无 X"必须过滤 ⬡ 前缀, 否则库按钮误报 FAIL (本会话真实踩过一次)。

