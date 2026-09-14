# 2026-08-06 UI 精简反馈循环 + WSLg 陷阱（老倪连续 ~20 轮）

连续多轮"没用删掉/重复了/看不清"反馈后的完整经验。老倪对冗余 UI 零容忍，
每个冗余入口/重复显示都会被点名。以下模式直接决定验收通过与否。

## 老倪 UI 精简铁律（默认决策，不用问）

1. **"没用就删掉" = 直接删**。冗余入口（工具栏按钮与模块库/模板双入口）、
   重复显示（t 时钟两处）、无用行（参考应用条、工作流过滤按钮行、Hero 大标题条）
   一律整行删除，不要保留"备用"。
2. **删 UI 前必须 grep 全仓库引用**：删除按钮/控件后，`tl.addWidget(self.btn_x)` 等
   挂载行、`.value()` 读取、方法调用都是 AttributeError 隐患。本周期删 btn_win
   时漏删 `tl.addWidget(self.btn_win)` 差点崩；删 sp_dt/sp_t_end 时 start_sim 里
   `self.sp_dt.value()` 必须改 getattr 兜底。
3. **同款信息只显示一处**：t 时钟（工具栏右上角 vs 底部状态栏）重复被点名 →
   删工具栏的，统一走底部 lbl_rt。教训：合并/重构布局后必查重复控件
   （本周期 lbl_clock 合并单行时残留两处定义）。
4. **弹窗零容忍**：WSLg 下任何弹窗都是负担——
   - exec_ 模态框 **不可见**（WSLg 窗口管理器问题）→ 主线程阻塞 → 用户重复点击
     才解除，表现成"第二次双击才能打开"（on_infer_video 无帧时 _qmsg_info 的根因）。
   - 非模态 QMessageBox（"运行已启动" 3s 自动关）也被点名"小窗口不许弹出来"。
   - 反馈只靠：按钮状态（⏳ 运行中…）、底部日志区、画布气泡 _show_bubble。
5. **工具栏归类规范**：工具类（运行/单步/停止/保存模型/录制/停止）| `QFrame.VLine`
   分割线 | 数据应用类（数据闭环/三模型/五模型/VLA-Touch/AWE/总系统）同一行；
   第二行工具栏 tb2 删除合并进第一行。
6. **防重入提示必须详细**（"要显示详细信息，别一句话带过"）：
   - `_busy_hint()`：任务名 + 已耗时 + 训练实时进度 + 剩余队列具体任务名。
   - 训练实时进度 = 读 `reports/train_curve_<policy>.json`（训练中每 10 步
     `_flush_curve()` 落盘，curve 最后一条即最新 step/loss）。
   - 队列任务名 = `_flow_names` 列表（_start_canvas_flow 构建，_flow_next 同步 pop）。
   - `_busy_info = {name, start, policy, total_steps}` 在 _start_worker 启动时记录，
     policy 从 busy_msg 正则提取（"正在准备 vla_touch 训练" → vla_touch）。
   - 说明：五模型对比 5 训练是 `_flow_queue` **串行**队列，完成一个自动启动下一个
     ——"还在跑"是设计行为（防重入），提示要清楚显示谁在跑/跑多久/还剩几个。
7. **Scope 进模块库**：工具/观察类节点放左侧 LIBRARY 独立分组（📊 评估），
   从工具栏移除，双击走 NODE_RUN_ACTIONS 既有链路。用户要求"放到 node 库直接拖"。

## WSLg 标题栏 emoji 乱码（"标题栏出现 01F 5A5"）

- **现象**：窗口标题（尤其 MDI 子窗口标题激活时附加到主标题：
  `主标题 - [子标题]`）含 emoji → WSLg/MSRDC 标题栏渲染成**十六进制码点**
  （🖥 = U+1F5A5 → 显示 "01F 5A5"；?? 是其他 emoji 的乱码）。
- **诊断**：`powershell.exe Get-Process | Where MainWindowTitle` 读真实标题
  （msrdc 进程 = WSLg X 服务窗口）。
- **修复**：QDialog/QMdiSubWindow 标题一律**纯文本**（`setWindowTitle("画布")`），
  不带 emoji/特殊符号。

## 流程时钟（"点击运行 t 时间也不变"）

- **根因**：真实流程（_start_canvas_flow，画布有训练环节）不走仿真 tick
  （_timer→_tick→step_sim），lbl_clock 永远 0.00。
- **修**：_start_canvas_flow 启动独立 `_flow_clock` QTimer(1000ms) →
  `_flow_clock_tick`（_sim_t += 1 + 刷新底部状态栏）；_flow_next 队列空 /
  stop_sim 时停。

## 其他

- `_show_nonmodal` 的 finished 闭包捕获 dlg 形成循环引用 → deleteLater 不释放
  → 旧 dialog 幽灵存活（count=2）。修：关闭时停 QTimer + finished 回调断开。
- 视频节点首次双击：无帧时不再 exec_ 提示，直接建 InferenceVideoDialog
  （lbl_note 自带"生成中"提示）+ 气泡，第一次双击立即出窗口。
- 验证脚本注意：`findChildren` 会混入模块库按钮（带 ⬡ 前缀）与工具栏按钮
  （mk_btn 无前缀），区分后再断言。
