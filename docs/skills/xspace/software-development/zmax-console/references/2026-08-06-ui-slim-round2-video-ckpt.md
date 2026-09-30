# 2026-08-06 第二轮界面精简 + 视频 checkpoint 新鲜度 (c46ef962/5ec775ea/007f5d70)

## 视频显示旧帧 (007f5d70) — 老倪: "视频怎么还显示 14:21?"
- 根因: InferenceVideoDialog._load_frames 找到旧 rollout_final_* 帧就 _play(), 不检查训练是否更新
- 修复: _check_newer_ckpt() — 任一模型 reports/train_curve_<policy>.json 的 ts(YYYYmmdd_HHMMSS)
  比其帧目录 mtime 新 60s 以上 → QTimer.singleShot(300, self._run_rollouts) 自动重新生成
- 无 json / ts len!=15 / 解析异常 → continue 跳过, 不误触
- 触发时 lbl_note 显示 "🔄 检测到新训练 checkpoint, 正在重新生成推理视频…"
- 注意: 若某模型本轮没训练 (无曲线 json), 它保留旧帧属正确行为

## 批量 UI 精简 (c46ef962) — 老倪一口气连删 5 处
1. hero 大标题行「Z-MAX 具身智能 · Simulink 模式」(64px 渐变黑, 深色主题下看不清)
   → 删除; 标题移到主窗口菜单栏右上角品牌标签 (studio.py _build_menubar 末尾,
   QMenuBar corner widget, 白字 #e6edf3 清晰可读)
2. 窗口标题 git hash (ae62ea2) → 删 _git_short 静态方法 + 标题改纯文本
   "XSpace Studio — Z-MAX v1.7.0"
3. 📡 实时采集状态条「采集中/数据包:24」(34px 全宽) → 删 UI 块 + _poll_acquisition
   方法 + _acq_timer; closeEvent/统一清理循环里的 getattr(self,"_acq_timer",None) 引用
   无害不用改
4. ▶运行「运行已启动」QMessageBox 弹窗 → 删除; 运行反馈改靠 btn_run "⏳运行中…"
   文案 + 日志区 + 流程时钟 t, 不再弹窗
5. 右上角 t= 时钟与底部状态栏 lbl_rt 重复 → 删 lbl_clock; _flow_clock_tick 改调
   _refresh_status() 更新 lbl_rt, 不再直接引用 lbl_clock

## 底部日志区折叠 (5ec775ea) — 老倪: "下面的终端窗口也要能隐藏"
- SimulinkModule.log_box (max110px 全宽) 加标题行「📋 日志 + ◀ 收起」btn_log_toggle
- _toggle_log_box(): log_box.setVisible 切换 + 按钮文案 ◀ 收起/▶ 展开 + tooltip 同步
- 按钮样式浅底 (#e9edf2 蓝字 #1f6feb) 交 switch_theme 正确转深色

## 删 UI 通用原则 (老倪高频指令: "没用删掉/这行都删掉/还没删掉?")
- 用户说删 = 整行/整元素删除, 不商量不保留 UI; "删掉了吗?"= 催促, 立即完成提交重启
- 删前 grep 引用链: 按钮删了要删 addWidget 行 (否则 AttributeError);
  控件删了查 .value()/.text() 读取点 (sp_dt/sp_t_end 删后 start_sim 的 .value() 崩
  → getattr(self,"_sim_dt",0.02) 兜底); 方法删了查调用点
- 数据/方法被别处引用时保留逻辑只删 UI 入口 (REFERENCE_APPS 数据、open_* 方法保留)
- 大 patch 易流超时 → 方法体删除用 execute_code 按 "    def X" text.index 边界精确删,
  UI 块删用小 patch; 每个工具调用参数 <8K tokens
- 老倪会连续追删: 删掉一个后立刻问下一个 (白字按钮→Scope→ACT-Meta→时间→画布窗口),
  保持"删→验证→提交→重启"循环不停顿

## 防重入提示详细信息 (38677ef2 延续, 详见 busy-progress-video-modal ref)
- 老倪: "要显示详细信息，不要一句话带过" — _busy_hint() 输出
  正在运行「任务名」已 Ns · 训练 X/Y 步 · loss L · 剩余: A → B
- 训练进度读 train_curve json (训练中每10步落盘, curve[-1]=最新 step/loss)
- _flow_names 列表随 _flow_next 同步 pop, 显示剩余具体任务名
