# GUI 精简铁律 + 工具栏归类 + 左侧栏区分 + 对话框生命周期陷阱 (2026-08-06)

老倪当天反复反馈 UI 问题（"没用就删"×6、"还是没隐藏"×3），全部教训归档。

## 1. 左侧栏对象区分（最重要，改错过 N 次）

studio.py 主程序有 **两处左侧栏**，老倪用词决定指哪个：

| 老倪说 | 指哪个 | 位置 |
|---|---|---|
| "左侧列表" / "侧边栏" / "XSpace Studio 这个列表栏" | 主窗口 **SystemSidebar**（240px，XSpace Studio 标题 + System2/Sys-12 卡片） | studio.py `_build()` root 布局 |
| "模块库" / "node 库" / "模块库列表栏" | Simulink 页 **LibraryPanel**（220px，LIBRARY 分组按钮） | simulink_module.py QSplitter |

- 2026-08-06 第 3 次反馈"左侧模块库还是没隐藏"→ 一直改 LibraryPanel 折叠（3 轮），最后用户说"XSpace Studio 这个列表栏"才明白是 SystemSidebar
- 教训：**听到"左侧列表/侧边栏"先查 studio.py 主窗口**，不是 simulink_module 的画布库
- SystemSidebar 折叠实现：标题行 ◀ 按钮 + collapse_requested 信号 + 主窗口 root 加 16px ▶ 展开条 + `_collapse_sidebar`/`_expand_sidebar`

## 2. GUI 精简铁律（老倪 2026-08-06 反复强调）

"没用/重复的按钮整行删掉"——本日删除清单（全部已验证 offscreen 后提交）：

- 参考应用条整行（白字模板按钮与上方彩色工具栏重复；REFERENCE_APPS 数据保留，load_reference_app_by_name 仍可用）
- 工作流过滤行（①访问·标注数据…⑥集成·测试 6 个按钮；set_filter 保留无 UI 入口）
- ACT-Meta 引导按钮（点击没反应）
- 画布窗口按钮（show_canvas_win——画布子窗口已不可关闭，恢复逻辑无意义）
- 时间 10.0s / dt 0.010 仿真参数控件（QDoubleSpinBox；start_sim 改 `getattr(self,"_sim_dt",0.02)` 兜底）
- 工具栏「📚 模块库」按钮（面板内已有 ◀ 收起，tl2 冗余）
- 工具栏「🖥 Scope」按钮（Scope 移入左侧 node 库）

**工具栏归类（最终形态）**：单行布局——
```
[工具类: ▶运行 ⏭单步 ⏹停止 🧭引导 ⛶浮动 💾另存为 📂加载 💾保存模型 🔴录制 ⏹停止]
┃ QFrame.VLine 分割线
[数据应用: 🎯数据闭环控制台 🔬三模型 🔬五模型 🖐VLA-Touch 🧿AWE 🎛总系统 ⬅返回总系统]
stretch → t=0.00s 时钟
```
删除原第二行 tb2/tl2，全部并入 tl。分割线：`sep=QFrame(); sep.setFrameShape(QFrame.VLine); sep.setFixedHeight(28)`。

**Scope 移 node 库**：LIBRARY 加 `("system", "📊 评估 (3)", [...])` 独立分组（📊 Scope 示波器 / 📊 对比评估 Scope / 🎥 推理效果对比），双击走既有 NODE_RUN_ACTIONS `("Scope","on_scope")` / `("视频","on_infer_video")` 链路。

## 3. 删除按钮/控件的安全步骤（避免 AttributeError）

1. grep 全部引用（含 addWidget 残留！删 mk_btn 创建但漏删 `tl.addWidget(self.btn_xxx)` 会崩）
2. 检查方法调用方（如 start_sim 读 sp_dt.value() → 改 getattr 兜底）
3. 检查模板/数据引用（删 REFERENCE_APPS 模板要查 load_reference_app_by_name 调用方）
4. offscreen 实例化验证 `not hasattr(w,"btn_xxx")` + 工具栏按钮列表确认

## 4. QDialog 二次打开失败根因（视频对比"只能打开一次"）

**症状**：InferenceVideoDialog 关闭后再打开不行/黑屏。
**根因**：`_show_nonmodal` 的 `_done` 闭包捕获 dlg 形成循环引用（dlg.finished → _done → dlg），`dlg.deleteLater()` 后 Python wrapper 不释放 → 旧 dialog 幽灵残留（QTimer 继续跑），二次打开出现两个窗口互相干扰。
**修复**：`_done` 里先 `dlg.finished.disconnect(_done)` 打破循环引用，再 deleteLater。
**验证陷阱**：offscreen 下 DeferredDelete 事件不自动处理，`count_dlgs()` 会误报残留——需 `app.sendPostedEvents(None, 52)`（QEvent.DeferredDelete）或接受 offscreen 差异，用真实 GUI 确认。

## 5. switch_theme 颜色替换陷阱

`switch_theme` 遍历所有 QWidget 的 styleSheet，把浅色值替换成深色（THEMES["light"]→dark pairs + #dbe9ff→#1a2230）。
- **坑**：按钮样式里 `color:#ffffff`（白字）会被替换成深色 → 蓝底深字看不清 → 用户"找不到按钮"
- **正确做法**：按钮用浅底样式 `background:#e9edf2; color:#1f6feb`（主题色），switch_theme 会正确转成深底蓝字

## 6. patch 工具转义陷阱

patch 的 old_string/new_string 里若含 `\"`（转义引号）会写入字面反斜杠 → SyntaxError: unexpected character after line continuation。用 write_file 重写整段或避免转义序列。
