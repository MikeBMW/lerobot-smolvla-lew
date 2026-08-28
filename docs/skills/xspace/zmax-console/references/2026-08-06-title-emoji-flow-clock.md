# 2026-08-06 收尾波 — 标题 emoji 乱码 / 流程时钟 / hero 行删除 / 工具栏归类

提交链（本段）：e82e8ae0 工具栏归类单行 → e66ecd00 删重复时钟 → f2d2234d 画布标题 emoji+流程时钟 → 38677ef2 防重入详细提示（见 busy-progress 文件）→ 5ec775ea 底部日志折叠（见 busy-progress 文件）→ hero 行/运行弹窗删除（进行中）

## 🐛 窗口标题 emoji 在 WSLg 标题栏渲染成十六进制乱码（f2d2234d）

现象：老倪问"标题栏出现 01F 5A5 这是啥？"
真相：**01F 5A5 = 🖥 emoji 的 Unicode 码点 U+1F5A5**。画布子窗口标题「🖥 画布 · Simulink 模型」的 emoji 在 WSLg/MSRDC 标题栏渲染成 hex 乱码。MDI 子窗口激活时 Qt 自动把子标题附加到主标题（`主标题 - [子标题]`），乱码进了 Windows 任务栏/标题栏。

调试路径（WSL 侧读不到 WSLg 窗口标题，必须走 Windows 侧）：
```
powershell.exe -NoProfile -Command "Get-Process | Where-Object {\$_.MainWindowTitle} | Select-Object ProcessName, MainWindowTitle"
# 看到 msrdc: XSpace Studio — Z-MAX v1.7.0 · e66ecd0 - [?? 画布 · Simulink 模型] (Ubuntu)
```
修复：**常驻窗口标题一律纯文本，不带 emoji/特殊符号**——`setWindowTitle("画布")`（主创建 + 浮动还原两处）。验证断言 `"\U0001F5A5" not in windowTitle()`。
通用规则：GUI 里 QLabel/按钮/日志可以带 emoji，**setWindowTitle 不给 emoji**（Windows 侧标题栏渲染不了）。

## ⏱ 真实流程运行 t 不动 → 独立流程时钟（f2d2234d）

现象：加载三/五模型对比点「▶ 运行」→ lbl_clock 停在 "t = 0.00s"。
根因：`start_sim` 走 `_start_canvas_flow`（有训练节点）→ worker 串行训练，**不走仿真 `_timer`/`_tick`**（那是观察模式无环节节点才走）→ lbl_clock 无更新。
修复：真实流程启动处加独立 `_flow_clock = QTimer(self)`（1s，timeout → `_flow_clock_tick`：`_sim_t += 1.0` + `lbl_clock.setText(f"t = {self._sim_t:.0f}s")` + `_refresh_status()`）；`_flow_next` 空队列（流程结束）和 `stop_sim`（手动停止）里 `fc.stop()`。
验证：手动调 `_flow_clock_tick()` 断言 `_sim_t == 1.0` 且 lbl 文本更新。

## 🗑 hero 大标题行删除 + 「运行已启动」弹窗删除（老倪最后要求）

1. **hero 行**：SimulinkModule 顶部「Z-MAX 具身智能 · Simulink 模式」64px 渐变行（qlineargradient stop:0.6 #0f1a24）在深色主题下"太黑看不清且占地方"→ 整行删，标题信息提升到主窗口菜单栏（studio.py `_build_menubar` 末尾 `mb.addWidget(QLabel(...))` 或 `mb.setCornerWidget(w, Qt.TopRightCorner)`，深色 QSS 已保证可读）。删除后顶部直接是工具栏，更紧凑。
2. **「运行已启动」小黑窗**：`_start_canvas_flow` 里 `QMessageBox`（"🚀 正在执行 N 个环节…" show + singleShot(3000, close)）——老倪明确"没必要，删掉"。理由：日志区已有「▶ 真实全流程启动 (N 环节): 名称」行，弹窗是噪音。删整段 try/except（L3473-3491 附近）。
用户偏好模式：**运行反馈靠日志区/按钮状态/流程时钟，不弹额外窗口**；顶部只留功能行不留装饰标题。

### ✅ 已完成（c46ef962）——hero 行 / git hash / 实时采集条 / 运行弹窗 四删齐

- hero 行删除：已提交（simulink_module.py 只剩注释，标题已在菜单栏品牌标签）
- **窗口标题 git hash 删除**：老倪问"上边的 ae62ea2 是啥？没用就删掉" → 删 `_git_short()` 静态方法（studio.py）+ setWindowTitle 改纯文本 `"XSpace Studio — Z-MAX v1.7.0"`。**窗口标题只保留产品名，不显示 commit hash**（老倪认为无用信息）。
- **📡 实时采集状态条整行删除**：「实时采集/采集中/数据包:24」UI 块（acq QFrame 34px + lbl_acq_state/pkgs/latest + _acq_timer 轮询）——纯展示无操作入口 → 全删。坑：`self._theme = _CUR_THEME` 行与采集无关但相邻，删 UI 块时保留。
- 「运行已启动」弹窗删除：已提交（L3471 只剩注释）
- 遗留引用 `_acq_worker`/`_acq_timer`（closeEvent 清理循环里 getattr 兜底）无害，不必清。

### 🐛 大 patch 流超时 → 拆小 patch 或 Python index 切片删除（可靠方案）

在 simulink_module.py（5.2K 行 / 292KB）上，**单次 patch 的 old_string/new_string 过大（约 >8K tokens）会流超时，patch 不落地且被系统警告**：连 read_file 大窗口也会超时。
- 小段删除（5-15 行）：先小 read_file（limit≤15）确认行号，再 2-3 个小 patch 分步删，old_string 控制在 5-8 行
- **大段删除（方法体 30-100 行）最可靠：execute_code 里 Python 字符串 index 切片**——一次成功删 65 行方法体，比多次小 patch 更快更不易超时：
  ```python
  src = open(f, encoding="utf-8").read()
  start = src.index("    def _poll_acquisition(self):")
  end = src.index("    def _repo_root(self):")
  src = src[:start] + "\n" + src[end:]
  open(f, "w", encoding="utf-8").write(src)
  ```
  删除后 grep 确认零残留（`def X` / 属性名 / label 名），实例化断言 `not hasattr(w, 'attr')`。

## 🎨 工具栏归类单行 + 分割线（e82e8ae0）

老倪："运行单步停止；保存模型录制停止，这些按钮是工具类放一行；其它数据典型应用按钮放工具按钮右侧；中间用分割线分开"。
实现：删除 tb2/tl2 第二行，全部并入第一行 tl：
`[▶运行 ⏭单步 ⏹停止 🧭引导 ⛶浮动 💾另存为 📂加载 💾保存模型 🔴录制 ⏹停止]` + `QFrame.VLine` 分割线 + `[🎯数据闭环 🔬三模型 🔬五模型 🖐VLA-Touch 🧿AWE 🎛总系统 ⬅返回]` + stretch + `t=0.00s` 时钟。
分割线：`sep = QFrame(); sep.setFrameShape(QFrame.VLine); sep.setFixedHeight(28)`。
**坑**：合并时 lbl_clock（t=0.00s）定义残留两处 → 界面出现两个时钟（e66ecd00 删一处）。合并布局后必须 `grep -c 'lbl_clock = QLabel'` 确认唯一。

## 其他
- 验证脚本断言含 `{bi['name']}` 等 f-string 花括号时，外层 f-string 要转义 `{{`，否则报错——用 write_file 写脚本避免 heredoc 转义地狱。
- 每次删除按钮/行后：`grep -n` 确认无残留引用（btn_xxx 在别处 addWidget/方法调用），实例化断言 `not hasattr(w, 'btn_xxx')`。
