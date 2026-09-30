# 2026-08-06 晚间 — 防重入详细进度升级 / 视频 exec_ 模态根因 / 底部日志折叠

提交链（本段）：c7f913b5 防重入详细进度+视频非模态 → 5ec775ea SimulinkModule 底部日志折叠

## 1. 视频"非得第二次双击才能打开"——exec_ 模态在 WSLg 下阻塞主线程（c7f913b5）

现象：首次双击视频对比节点"没反应"，第二次双击才打开。
根因：`on_infer_video` 无帧分支调用 `self._qmsg_info(...)`——`_qmsg` 用 **`mb.exec_()` 模态**。
WSLg 下模态弹窗不可见 → 主线程阻塞在 exec_ → 用户以为没反应，重复点击/按键后模态框
才被解除 → 后续 `dlg.show()` 才执行 → 看起来"第二次双击才打开"。
修复：无帧时改 `self._show_bubble(self.rect().center(), "...", 5000)` 气泡非模态提示；
对话框自身 lbl_note 已显示"无帧/生成中"，不再阻塞主线程，首次双击立即弹窗。
**通用教训**：任何 `_qmsg_*`/QMessageBox.exec_() 在 WSLg 下都会"卡住没反应"，排查
"点了没反应/要点两次"类问题先搜 exec_ 调用。

## 2. 防重入提示升级：训练实时进度 + 剩余队列具体任务名（c7f913b5）

老倪反馈"⏳ 正在运行「正在准备 vla_touch 训练」已 6s · 队列还有 1 个任务"仍不够——
要显示详细进度。升级为 `_busy_hint()` 统一生成（4 处防重入点 `self._log(self._busy_hint())`）：

```
⏳ 正在运行「正在准备 vla_touch 训练」已 6s · 训练 30/50 步 · loss 0.2000 · 剩余: 🧠 AWE 训练 → 📊 对比评估 Scope · (日志区可看到 📈 进度)
```

- **训练实时进度来源**：`reports/train_curve_<policy>.json`——训练中 `_flush_curve()` 每 10 步
  写盘，`curve` 列表最后一条 = 最新 (step, loss)。读 json 比解析日志流可靠（log 只发一行）。
- busy_info 记录 policy：`_start_worker` 里从 busy_msg 正则提取
  `re.search(r"(act|smolvla_?lew?|vla_touch|awe_zflow)", str(busy_msg))`。
- **剩余队列具体任务名**：`_start_canvas_flow` 构建队列时同步
  `self._flow_names = [n["name"] for n, m, k in stages]`，`_flow_next` pop 队列时同步
  `self._flow_names.pop(0)`；提示取 `list(flow_names)[1:]`（第 0 个是正在跑的）。
- 兜底：无 busy_info 时返回 "worker 运行中"。
- 注意：`"name": busy_msg.split("(")[0]` 会带出"正在准备 X 训练"这种前缀——这是 on_train
  传的 busy_msg 本身，可接受；若嫌长可只取 policy 段。

## 3. SimulinkModule 底部日志区可折叠（5ec775ea）——"下面的终端窗口也要能隐藏"

SimulinkModule 底部有 `log_box`（QTextEdit, setMaximumHeight(110), 全宽日志框，_log 输出处）。
老倪要求可隐藏。实现：
- log_box 上方加标题行 `log_head = QHBoxLayout()`：`QLabel("📋 日志")` + stretch + `btn_log_toggle`（◀ 收起, 64px）
- `_toggle_log_box()`：`log_box.setVisible(False)` ↔ 按钮文字 ◀ 收起/▶ 展开 切换
- 按钮样式用浅底蓝字（#e9edf2/#1f6feb），switch_theme 会正确转深色——**不要用白字**
  （switch_theme 把 #ffffff 替换成深色 → 深底深字看不清，之前 ◀ 收起 按钮踩过）
- _log 写入不受影响（append 到隐藏 widget 无副作用）

## 4. 用户反馈节奏模式（晚间连发）
老倪晚间密集反馈都是 UI 体验问题，逐个修：删除无用按钮（ACT-Meta/Scope/画布窗口/
时间dt/📚模块库/参考应用条）→ 工具栏归类单行+分割线 → 画布标题 emoji → 防重入详细
提示 → 视频首次双击 → 底部日志折叠。每改一处立即 commit + push + 重启控制台
（kill 旧进程 → `DISPLAY=:0 python3 studio.py` 后台起，watch Traceback 确认无崩溃）。
