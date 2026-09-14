# 2026-08-05 Scope/流程/训练修复会话记录

本会话后半段（崩溃修复#10 之后）的 Scope 铁律、流程链终局模式、SmolVLA+LEW 训练 3 bug、归一化量纲。

## Scope 铁律（老倪反复强调，全部已落地 simulink_scope.py）

1. **训练中不显示曲线**：`len(cv) < 2` 的点不进 series（1 点=训练中=歧义）；ScopeWidget.paintEvent 兜底 `n < 2: continue` 不画圆点。训练完成（≥2 落盘点）才显示。指标行用 `⏳ 训练中: 模型名` 提示。
2. **默认无显示**：series 空 → `set_series({})` + 提示「暂无完整训练曲线」，**禁止兜底画单条 loss 曲线**（曾用旧 _train_curve 数据画默认线 = 歧义来源）。
3. **x 轴用真实 step**：series 值格式 `(xs, y, color, dashed)`，xs=None 时退索引（兼容旧格式）；刻度范围取所有曲线 xs 的 min/max，不是点数。
4. **图例色块必须显式 setBrush**：drawRect 空心框会残留前一次圆点的 brush → 所有图例变同色（"怎么都用黄色"）。每个色块 setPen(color)+setBrush(color)，画完 setBrush(NoBrush)。
5. **归一化统一量纲**（用户要求三模型可比）：ACT loss=动作空间 MSE（(rad/s)² 量级大），SmolVLA 系=扩散噪声空间 MSE（量级小），绝对值差量级**不可比**。Scope 显示时 `ys /= mean(ys[:3])`（前 3 点平均，**不是单点**——SmolVLA 首点 0.4357 异常小，单点基准会让次点显示 2.4 倍暴涨）。y 轴标签「loss (归一化 · 起点=1)」。
6. **全局适配按钮**：`fit_all()` 清 `_y_lo_manual/_y_hi_manual/_drag_last`；点击后按钮变「✓ 已全局适配」1.5s 恢复（功能正常但无反馈 = 用户以为"第二次没用"）。
7. **滚轮缩放/中键平移**：wheelEvent 设手动范围；中键按下时 manual 为 None 先初始化；双击=fit_all。

## 曲线文件管理（simulink_module.py）

- 三模型对比（`_start_canvas_flow` 检测 ≥2 个训练节点）启动时**清空全部 train_curve_*.json**，日志「🧹 三模型对比: 已清空旧曲线」——Scope 只显示本轮三个模型。
- 单模型训练（on_train）：只删当前 policy 自己的文件（`train_curve_{policy}.json`），保留其他模型已完成曲线。
- Scope 不按 mtime 过滤（保留所有已训练曲线）。

## 训练进度与步数

- `_line_hook` 每 log_freq 步 emit `📈 {pname} 训练中: {step}/{total} 步 · loss {loss:.4f}`（训练中日志区实时滚动，防"卡住"错觉）。log_freq=5（150→100→50 步时同步改）。
- **步数哲学**（用户：先跑通流程再加步数）：steps 从 150→100→50；50 步时三模型总时长 ~1.5min（ACT 13s + SmolVLA 30s + SmolVLA+LEW 30s）。跑通全流程后再逐步加。改步数 = 模板 10 处 `"steps": N` + node_logic.py 默认值 + 3 个 config_*_metaworld.yaml + simulink_module._parse_loss_curve 的推断步进（`max(dedup, default=0) + log_freq`）。

## QThread 终局模式（崩溃修复#10 之后的最终形态）

- **worker.finished 回调禁置 None**：`finished.connect(lambda: setattr(self, "_worker", None))` 是 exit 134 真根因——finished 信号回调里置 None → worker 失去引用被 GC，而 QThread 底层线程未完全终止（PyQt 竞态）→ "QThread: Destroyed while thread is still running" SIGABRT。
- 正确模式：finished 回调 = `lambda: None`（no-op）；`finished_ok` 的 `_done` 回调里 `worker.wait(100)` 等线程真正结束 → `self._worker = None` → `_flow_next()`。wait 后线程已死，GC 安全。
- 曾误改"保留引用"（`lambda _w=worker: setattr(self, "_worker", _w)`）→ 引入新 bug：_done 置 None 后被 finished 回调设回旧 worker → 下一环节被 `cur.isRunning()` 竞态拦截（"ACT 完成后 SmolVLA 启动被拦截"）。
- **主线程禁阻塞 wait**：stop_sim 的 `w.wait(10000)` 会冻结 UI（worker 卡数据拉取时点停止 = 界面死 10s）。改 200×50ms `QApplication.processEvents()` 轮询。
- closeEvent：pkill -9 lerobot_train + wait 15s，失败 `self._keep_worker = w` 保留引用防 GC。
- _acq_worker/_remote_worker 靠下一轮覆盖回收（旧线程已死，GC 安全），finished no-op 即可。

## SmolVLA+LEW 训练 3 bug（modeling_smolvla_lew.py，全部实测修复）

1. `t.permute(0, 3, 1, 2)`（358 行附近）：lerobot 图像 tensor 已是 CHW `[T,C,H,W]`，permute 打乱成 `[T,W,C,H]` → SigLIP patch_embedding 报 "Given groups=1, weight of size [768,3,16,16], expected input[2,96,3,96] to have 3 channels, but got 96 channels"。**删除 permute，直接 numpy**。
2. `batch_videos.transpose(0, 1, 2, 5, 3, 4)`（207 行）：videos 构造后已是 `[B,V,T,C,H,W]`（CHW），再 transpose 打乱。**删除**。
3. dtype 混战：videos_tensor float32 vs 模型权重 bfloat16 → "Input type (torch.cuda.FloatTensor) and weight type (CUDABFloat16Type)"；LEW 内部 vision_encoder bf16 + predictor float32 混合 → "mat1 and mat2 must have the same dtype"。**整个 LEW loss 计算包 `torch.autocast(device_type=..., dtype=torch.bfloat16)`**。

修复后实测：150/150 步 1分18s，loss 0.357，action_loss 0.256，显存 1.81GB。修复前 30s 内必炸（3 个不同错误逐步暴露）。

## 训练配置对话框（TrainConfigDialog，2026-08-05 末）

老倪要求"增加训练步数调整功能，在训练模块双击打开配置或右键打开"。已落地 commit 47f37e4d，simulink_module.py：

- **双击训练节点** → 打开 TrainConfigDialog，**不直接运行**（on_node_activated 里 `kw == "训练"` 分支改走 `on_train_config`；原行为双击即运行训练）。运行改走右键「▶ 运行节点」或整体 ▶ 运行。
- **右键训练节点** → 菜单加「🎛 训练配置 (步数/batch/lr)」（仅名称含"训练"的节点显示），NodeItem.contextMenuEvent 里 `a_train` 条件添加。
- TrainConfigDialog：QSpinBox steps(10-5000, singleStep=50) + QSpinBox batch(1-64) + QDoubleSpinBox lr(1e-6~1e-2, 6 位小数)；`_apply()` 写 `node["params"]["steps"/"batch_size"/"lr"]` 后 accept。
- 参数生效链路：节点 params → `node_logic.execute_node_logic` 读（`steps = p.get("steps", 50)`）→ on_train 透传替换 config。保存即下次训练生效。
- 验证方法：构造对话框 → `ed_steps.setValue(200)` → `_apply()` → assert `params["steps"]==200`；monkeypatch `on_train_config` 验证双击分派到配置而非运行；node_logic 返回 None 但仍读 params。

## loss 口径速查（回答用户"为什么 loss 这么小/大"）

- ACT：`MSE(预测动作, 真值动作)` 原始动作空间，单位 (rad/s)²，量级 5~80（metaworld 动作 ±10 rad/s）。
- SmolVLA 系：`F.mse_loss(u_t, v_t)`（modeling_smolvla.py:809）DiT 去噪损失，标准正态噪声空间，量级 ~0.1-1。
- **绝对值不可比**（量纲不同）；比归一化下降趋势；SmolVLA 系收敛慢是因为 SmolVLM2 冻结（可训练 4.4%）+ 扩散损失特性，不是更差。
