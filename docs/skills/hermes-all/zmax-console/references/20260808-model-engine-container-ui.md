# 模型引擎容器管理框架 UI 定稿 (2026-08-08)

老倪本会话对模型引擎（TrainingModule）容器管理区的连续迭代定稿。完整版（含代码位置、SSH 命令、QSS）在
`docker-gpu-training` 技能的「标准容器框架」段——本文件只记 GUI 侧要点，给 studio.py 维护用。

## 三模式卡片（最终形态，老倪三次纠正后定稿）

- 迭代史：①状态机单选（复杂）→ ②裸 QRadioButton（太简单不好看）→ ③ **三模式卡片**（QPushButton checkable + QButtonGroup exclusive）
- 卡片：`QPushButton(f"{title}\n{sub}")`，`setMinimumSize(150, 64)`，QSS `QPushButton:checked{border:3px solid 青色; background:#0d3b33;}`（选中外边框包裹高亮）
- 三模式：`train`🚀 远程训练 / `infer`🎮 本地运行 / `deploy`📱 端侧部署（Mac/Orin 合并为端侧）
- 默认 `_ct_mode_btns["train"].setChecked(True)`

## 模式 = GPU 引擎（两次纠正）

- `_ct_pick(key)`：train → `gpu_mode="remote"`；infer → `gpu_mode="local"`（deploy 不动）
- `_start_training` 只对 deploy 分流（`_container_action("mac")` 推送），其余统一走 Model Zoo 训练队列
- simulink `on_train`（5012 行）按 `gpu_mode` 分流：remote → 远程容器 / local → 本地 4060 真训练
- **坑①**：曾把"本地运行"接 `on_infer_video` → 点训练弹 scope → 老倪"scope 是 simulink 的功能，应该开始训练"——本地运行必须真训练，推理走画布节点
- **坑②**：训练按钮固定走队列不读模式 → "本地推理没反应"

## 按钮定稿

- "▶ Start Training" → "▶ Start"（通用开始——模式决定动作）
- "⏹ Stop Training" → "⏹ Stop"；**取消 Pause**（按钮 + `_pause_training` + 遗留 `pause_btn` 引用全删）
- `_stop_training` 重写：清 `_zoo_queue` + `_zoo_timer.stop()` → `pkill -9 -f lerobot_train` → simulink `on_stop()` → Start 恢复

## 布局定稿

- 配置表格：`layout.addWidget(self.param_scroll, 1)`（伸长占满，右侧滚动条 `ScrollBarAsNeeded`）
- 容器管理：`cg` 移出 param_group → 主布局 `layout.addWidget(cg)`（外层底部）
- 紧凑上移：`layout.setSpacing(6)` + `setContentsMargins(16, 6, 16, 12)`（紧挨 GPU 服务器不空段）
- "本地推理" → "本地运行"（7 处改名，infer key 不变）

## 日志与线程

- **日志桥接**：`self.simulink.log_signal.connect(self.model_engine._log)`（主窗口）——否则训练细节在 simulink 页，模型引擎日志区只看到队列推进（老倪"日志呢"）
- **容器状态详细树**：`_poll_remote_container` 一次 SSH 拉全 `docker ps -a` + images + logs(Training%/loss/config) + nvidia-smi，状态变化输出 `🐳 远程容器: …├镜像 ├训练 └GPU`（变化才输出防刷屏）
- **Qt 跨线程铁律**：后台线程 `log_text.append`/`setEnabled` 直接崩（老倪"容器管理崩溃"）→ `_log` 非主线程用 `QTimer.singleShot(0, ...)` 回主线程

## 反复弹 scope 诊断

多个「7 模型仿真 rollout 对比」窗口 = simulink video 节点双击触发（5742 行 `on_node_activated`）或旧 GUI 残留，
**不是训练触发**。处理：xdotool 按标题过滤 `*rollout 对比*` windowkill 全关 + 确认无本地 lerobot_train + 重启 GUI。
