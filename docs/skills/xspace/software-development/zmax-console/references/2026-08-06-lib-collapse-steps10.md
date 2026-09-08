# 2026-08-06: 左侧栏折叠 (LibraryPanel v1/v2/v3 + 主窗口 SystemSidebar) + 训练步数 50→10 + worker 锁诊断 (commits b66c6833/aaf370a5/0af2128c/ca63eb33/a7b3cabd)

## ✨ 左侧模块库栏可折叠 (b66c6833, 老倪: "太占地方, 隐藏左边列表栏")
LibraryPanel (setFixedWidth 220) 与 MDI 画布在 `QSplitter(Qt.Horizontal)` 里。折叠方案:
1. **LibraryPanel 加信号**: `collapse_requested = pyqtSignal()` (类属性), 标题行加 `◀ 收起` 按钮
   (QPushButton fixedWidth 64, hover 样式), `clicked.connect(self.collapse_requested.emit)`。
2. **split 变 3 部件**: `library | _lib_expand_bar(16px ▶按钮) | _mdi`。
   展开条初始 `setVisible(False)`, 折叠时 `library.setVisible(False); bar.setVisible(True)`,
   展开时反向。stretchFactor: 0→0, 1→0, 2→1 (画布占满)。
3. 方法: `_collapse_library()` / `_expand_library()` (各自 setVisible 翻转 + `_log` 提示)。

⚠️ offscreen 验证坑: 窗口未 show() 时 QSplitter.sizes() 全 0, **不能断言"展开后库宽>0"**;
用 `isHidden()` 翻转断言 (折叠后库 isHidden, 展开后 not isHidden)。offscreen 下首次
setVisible(False) 后 isVisible() 会误导 — 用 isHidden 反向判断。

## ✨ 折叠 v2 迭代 (aaf370a5, 老倪两次反馈"还是没隐藏" — 按钮不可见坑)
**教训**: v1 折叠按钮是 64px 小灰按钮 (#e9edf2 底 10px 字) 在标题行右缘 — 用户完全找不到,
反馈"左侧列表, 也没隐藏啊"。**功能 offscreen 验证全过 ≠ 用户能发现按钮** — UI 入口可见性
需要醒目样式, 不是功能正确就行。
v2 修复 (用户偏好: 功能入口必须显眼, 参考"新模板须显眼工具栏按钮"铁律):
1. **按钮加大加醒目**: `setFixedWidth(72)` + 蓝色底 `background:#1f6feb` + 白字
   `color:#ffffff` + `font-weight:700` + hover `#388bfd` — 与浅灰面板强对比
2. **双击「📚 模块库」标题也折叠**: `title.mousePressEvent = self._title_clicked`,
   `_title_clicked` 里两次点击间隔 <0.4s 触发 `collapse_requested.emit()`
3. 展开条 ▶ 保持 16px 窄条 (左缘, 折叠后唯一入口)
⚠️ 给 QLabel 挂 mousePressEvent 时注意: 方法定义在 __init__ 之后作为独立 method,
别把后续 __init__ 代码 (scroll/hint 创建) 卷进 handler — 曾 patch 时把 scroll 创建
错放进 _title_clicked 导致 lay 未定义, 需恢复完整结构再验证。

## 截图诊断 GUI 状态 (WSLg 窗口像素分析)
用户反馈 UI 问题时, 别只靠 offscreen 断言 — 截真实屏幕看按钮/面板是否可见:
```powershell
# PowerShell (WSLg 窗口在 Windows 桌面):
Add-Type -AssemblyName System.Windows.Forms,System.Drawing
$b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bmp=New-Object System.Drawing.Bitmap($b.Width,$b.Height)
$g=[System.Drawing.Graphics]::FromImage($bmp); $g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size)
$bmp.Save('C:\temp\gui_shot.png')
```
然后 PIL 按颜色定位: 面板 #f6f8fa / 按钮 #1f6feb / 画布 #eef1f5 的像素分布判断
"按钮是否存在/面板是否隐藏"。本次靠这个发现: 面板色只有 1448 像素 (该显示 17 万) →
折叠按钮根本没被用户看到 (而非折叠逻辑坏)。

## ⚡ 训练步数统一 50→10 (0af2128c, 老倪: "改成训练10步吧, 先跑通流程")
所有训练入口默认 steps 从 50 改 10 (链路验证更快)。改动位置清单 (新增训练入口时照此检查):
- `simulink_module.py`: REFERENCE_APPS 全部模板训练节点 `"steps": 50`→10 (18处),
  对话框 `p.get("steps", 50)`→10 (TrainConfigDialog + tooltip 显示), `setSingleStep(50)` 不动
- `node_logic.py`: 右键源码默认 `p.get("steps", 50)`→10
- `tools/train_vla_touch.py` / `tools/train_awe_zflow.py`: `default=50`→10 (argparse)
- `config_*_peg_v3.yaml`: `steps: 50/2000`→10
- 排除: `000050` checkpoint 目录名、`act_infer.py n_action_steps=50` (推理参数非训练步数)
验证: grep 残留 `"steps": 50|steps=50|default=50` (排除 000050/n_action_steps) + offscreen
加载模板断言所有训练节点 steps==10。

## 🔍 "训练完成但锁没释放"诊断 (老倪: "⏳ 上一个任务还在跑" 半天没反应)
日志出现 `✅ 训练完成` 但后续点击仍提示"上一个任务还在跑" = **防重入锁 `self._worker.isRunning()`
卡 True** (所有入口共用: _start_canvas_flow/_run_full_flow/on_train/双击节点)。
排查顺序:
1. 先看系统: `ps aux | grep lerobot_train` + nvidia-smi — 若无训练进程 = worker 线程没退出,
   不是还在跑 (之前误判过"设计如此", 实际训练真完成了)。
2. `CICDWorker.run()` 正常 emit finished_ok → `_done` 回调里
   `cur.wait(100)` 等线程真死再 `self._worker = None` (崩溃修复#10 保留引用不冲突,
   finished 回调 no-op `lambda: None` 防止 GC 竞态)。
3. finished_ok 连接在 worker.start() 前, `worker.finished.connect(lambda: None)` 必须有
   (不置 None → worker 无引用被 GC → QThread destroyed SIGABRT)。
若 _done 没执行 (日志无 ✅ 摘要行) → 看 worker.run() 是否在 fn 内部卡住 (子进程 Popen
等待) 或异常被吞。GUI 日志里训练脚本自己的 `✅ 训练完成` 是子进程 stdout, 与 _done 的
`✅ {summary}` 是两条 — 只有后者出现才说明锁会释放。

## ✨ 折叠 v3 双入口 + switch_theme 颜色坑 (ca63eb33, 老倪第 3 次反馈\"左侧模块库, 还是没隐藏\")
**用户连续 3 次反馈同一个问题 (b66c6833→aaf370a5→ca63eb33)** — v1/v2 功能 offscreen 全过但用户就是找不到入口。真正的两个坑:

**坑 1: switch_theme 遍历替换所有 widget 的 QSS 颜色, 把按钮白字改成深色**
`switch_theme(name)` 遍历 `[self] + self.findChildren(QWidget)`, 把 stylesheet 里浅色值替换成深色:
```python
for lc, dc in pairs:   # pairs = THEMES light→dark 颜色映射 + ("#dbe9ff","#1a2230")
    ss = ss.replace(lc, dc) if name == "dark" else ss.replace(dc, lc)
```
v2 的 ◀ 按钮样式 `background:#1f6feb; color:#ffffff` → dark 下 `#ffffff` 被换成 `#1a1f2b` (深色字) → **蓝底深字, 对比度差, 用户看不见按钮文字**。修复: 用浅底样式 (会被正确转深底), 文字用主题色 (#1f6feb 不在替换对里, 保持蓝色):
```python
btn_collapse.setStyleSheet("""
    QPushButton{background:#e9edf2; color:#1f6feb; border:1px solid #d0d7de; ...}
    QPushButton:hover{border-color:#1f6feb; background:#dbe9ff;}
""")   # dark 下 → background:#14181f(深底) + color:#1f6feb(蓝字) 醒目
```
**规律**: 自定义按钮样式里**不要用 #ffffff 白字 + 彩底** — switch_theme 会把白字换深色; 用 `浅底+主题色文字` 组合, 主题转换后深底+主题色依旧可见。验证时断言 `"#ffffff" not in ss` 且 `"#1f6feb" in ss`。

**坑 2: 面板内入口不可发现 → 加工具栏双入口**
v2 只有面板内 ◀ 按钮 (72px, 在 LibraryPanel 标题行右缘) — 用户仍找不到。v3 在 tl2 工具栏加同款大按钮:
```python
self.btn_lib_toggle = mk_btn("📚 模块库", "隐藏/显示 左侧模块库面板 (点击切换)", self._toggle_lib_btn, "#1f6feb")
# _toggle_lib_btn: library.isVisible() → _collapse_library + 文字 "📚 模块库 (隐藏中)"
#                  else → _expand_library + 文字 "📚 模块库"
```
**规律 (用户偏好)**: 折叠/隐藏类入口必须有**双入口** — 面板内 + 工具栏 (同\"新模板须显眼工具栏按钮\"铁律)。工具栏按钮文字带状态 `(隐藏中)` 反馈。

**诊断方法升级**: 前两次反馈只靠 offscreen 断言 (isHidden 翻转全过) — 但**功能正确 ≠ 用户能发现**。第三次用 PowerShell 截真实屏幕 + PIL 按色定位:
- 面板色 #f6f8fa 只有 1448 像素 (LibraryPanel 应 220×800≈17 万) → 面板实际被折叠了? 或按钮没被看到
- 蓝色 #1f6feb 像素仅 556 且分散 (不在左上角按钮区) → 按钮样式被主题改色
- 用户窗口可能没最大化 (窗口从 x=160 开始, 左侧 0-160 是桌面) — 截图先定位窗口边界再分析

**结论**: 用户说\"还是没隐藏\"时, 排查顺序: ① switch_theme 是否改了按钮颜色 ② 按钮是否足够醒目/是否在用户视线内 ③ 是否加工具栏双入口。不要重复\"功能验证已过\"就完事。

## 🚨 决定性教训: 用户说的\"左侧栏\"是 XSpace Studio 主窗口侧边栏, 不是 Simulink 页模块库 (a7b3cabd, 老倪第 4 次反馈)
前三次 (b66c6833/aaf370a5/ca63eb33) 一直在改 `SimulinkModule.LibraryPanel` (Simulink 页画布左侧 220px 模块库)。
老倪第 4 次明说 \"**XSpace Studio 这个列表栏**\" — 才意识到指的是**主窗口左侧 `StudioMainWindow.SystemSidebar`** (240px,
含 XSpace Studio 标题 + System2/Sys-12/Sys-11 架构卡片 + 模块库分隔)。**代码注释写着\"侧边栏 (可隐藏)\"但从未实现** —
注释是愿望不是事实, 信注释就踩坑。

**架构事实**: `studio.py` 是 QStackedWidget 多页面主程序 (home/architecture/dataset/training/.../simulink 12 页),
`SystemSidebar` 在主窗口 `root = QHBoxLayout()` 最左, `SimulinkModule` 只是其中一个 stack 页 (其内部又有自己的 LibraryPanel)。
**两个\"左侧栏\"并存**: 主窗口级 SystemSidebar vs Simulink 页级 LibraryPanel。用户说\"左侧列表/侧边栏/列表栏\"默认指主窗口的;
说\"模块库/左侧模块库\"在 Simulink 页上下文里才指 LibraryPanel — 但这次老倪说\"模块库\"其实还是主窗口侧边栏 (其内有\"模块库\"分隔标签)。
**诊断**: 拿不准时先截图 (PowerShell 全屏) 定位窗口边界和面板位置, 或直接问\"是主窗口左侧还是 Simulink 画布左侧\" —
别埋头改一个\"功能验证已过\"的入口。

**SystemSidebar 折叠实现** (与 LibraryPanel 同构, 但挂在主窗口 root 而非 split):
```python
# SystemSidebar (studio.py):
collapse_requested = pyqtSignal()          # 类属性
# 标题行 (logo + XSpace Studio + stretch + ◀ 按钮 34px, C_CARD 底 C_BLUE 字):
btn_collapse.clicked.connect(self.collapse_requested.emit)

# StudioMainWindow._build: root = QHBoxLayout() 里:
self.sidebar = SystemSidebar()
self._sb_expand_bar = QPushButton("▶")     # 16px, 初始 setVisible(False)
self._sb_expand_bar.clicked.connect(self._expand_sidebar)
self.sidebar.collapse_requested.connect(self._collapse_sidebar)
root.addWidget(self.sidebar); root.addWidget(self._sb_expand_bar)   # 然后 addWidget(self.stack)

# 方法 (放 _on_nav 前):
def _collapse_sidebar(self):
    self.sidebar.setVisible(False); self._sb_expand_bar.setVisible(True)
    self.statusBar().showMessage("📚 左侧栏已收起 (点左缘 ▶ 展开)", 3000)
def _expand_sidebar(self):
    self.sidebar.setVisible(True); self._sb_expand_bar.setVisible(False)
    self.statusBar().showMessage("📚 左侧栏已展开", 3000)
```
验证: offscreen 实例化 **StudioMainWindow** (不是 SimulinkModule!) — 类名是 `studio.StudioMainWindow`
(不是 MainWindow), 实例化慢 (12 页全部构建, timeout 给 240s)。断言 sidebar 折叠/展开/信号/◀ 按钮存在。

## 关联
- 训练数据动作压扁/视频不动根因 → lerobot-dataset-engineering #13
- rollout 推理路径 (x0 起点/归一化) → metaworld-sim-eval
- Simulink 页 LibraryPanel 折叠 v1/v2/v3 → 上文
