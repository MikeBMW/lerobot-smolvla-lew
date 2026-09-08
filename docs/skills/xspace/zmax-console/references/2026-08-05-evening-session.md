# 2026-08-05 晚间会话: QThread 真根因 / WSLg 冻结 / LEW 3bug / Scope 归一化

承接同日早间迭代。本文件记录晚间新增的硬核教训。改动全部已 commit + push (main)。

## 1. exit 134 QThread 崩溃 — 真根因 (崩溃修复#10)

- 症状: 反复 exit 134 `QThread: Destroyed while thread is still running` SIGABRT。修了 9 处 closeEvent（_acq_timer/_rec_timer/CICDPanel._worker/_remote_worker/StudioMainWindow/InferenceVideoDialog...）仍崩。
- 定位: 测试脚本加 `faulthandler.enable()` + 分步 print → 崩溃点精确在
  `worker.finished.connect(lambda: setattr(self, "_worker", None))` 的回调。
- 机制: finished 信号回调里置 None → worker 对象失去最后一个引用被 Python GC，
  而 QThread 底层线程尚未完全终止（PyQt 竞态）→ 析构时 abort。
- 修复演进:
  1) 5 处 finished 回调改保留引用 `lambda _w=worker: setattr(self, "_worker", _w)`（防 GC）；
  2) 这又引入流程卡死（见 §2），最终方案: **`_done`（finished_ok 回调）里 `wait(100)` 等线程真结束再置 None + 调 `_flow_next()`；finished 回调改 no-op `lambda: None`**。
- 铁律: **QThread 对象析构时线程必须已结束**。任何 "finished 回调里置 None" 都有 GC 竞态风险。closeEvent 里对 running worker 先 pkill -9 子进程再 wait(15000)，wait 失败用 `self._keep_worker = w` 保留引用防 GC。

## 2. 流程卡死: ACT 完成后 SmolVLA 被"上一个任务还在跑"拦截

- 症状: 三模型对比中 ACT 训完 → 日志出现 `⏳ 上一个任务还在跑` ×2 → SmolVLA/SmolVLA+LEW 不启动。
- 根因: 崩溃修复#10 的保留引用版 finished 回调，在 `_done` 置 None 之后又把旧 worker 设回 `_worker` → 下一环节 `cur.isRunning()` 竞态拦截。
- 修复: `_run_node_stage._done` 里 `cur.wait(100)` + `self._worker = None` + `self._flow_next()`；5 处 finished 回调全改 no-op。
- 轮询型 worker（_acq_worker/_remote_worker）不依赖 finished 清理，靠下一轮创建时覆盖引用回收（旧线程早已结束，GC 安全）。

## 3. WSLg 界面"卡死" — 显示层冻结（不是 Qt 逻辑问题）

- 症状: 窗口完全不动 / 点击无效，但进程活着、主线程 `poll_schedule_timeout`（事件循环正常）、负载低、无训练进程。
- 诊断顺序: `cat /proc/<pid>/status` 看 State=S (sleeping) + 线程 wchan → 主线程在 poll = Qt 正常；
  `ls /tmp/.X11-unix/` 有 X0 + `ps aux | grep weston` 查不到合成器 = **WSLg weston 合成器崩溃**。
- 修复: ① QApplication 创建前设 `AA_DisableWindowManagerEffects` + `AA_UseSoftwareOpenGL`（软件渲染兜底，studio.py main 开头）；
  ② 终极: Windows PowerShell `wsl --shutdown` 重建 WSLg，或 `sudo pkill -9 weston` 让 WSLg 自动拉起。
- 模态对话框不可见假死: WSLg 下 `exec_()` 模态框可能弹到不可见位置 → 主窗口被模态禁用 = "按啥都不好使"。
- 根治: **全部对话框改非模态** `_show_nonmodal(dlg, on_accept=None)`（居中 + `WindowStaysOnTopHint` + raise_ + activateWindow + finished 回调 + show）。
  8 处已改: TrainConfigDialog/BlockParamsDialog/NodeLogicDialog/FlowScopeDialog/InferenceVideoDialog/ModelCompareDialog/ScopeCompareDialog/对比面板。
  仅 QFileDialog（需返回值）保留模态。offscreen 验证: 弹任意对话框后 `w.isEnabled()` 必须仍 True。

## 4. SmolVLA+LEW 训练必失败 — 3 个 bug（手动跑 lerobot_train 抓真实报错）

- ① `t.permute(0, 3, 1, 2)` 错误: lerobot 图像 tensor 已是 `[T,C,H,W]`(CHW)，permute 打乱成 `[T,W,C,H]` → SigLIP 报
  `expected input[2,96,96,3] to have 3 channels, but got 96`。修复: 直接 `t.detach().cpu().float().numpy()`。
- ② `batch_videos.transpose(0,1,2,5,3,4)` 错误: videos 构造后已是 `[B,V,T,C,H,W]`，再 transpose 打乱 → 删除。
- ③ dtype 不匹配: LEW 内部 vision_encoder bf16 + predictor float32 混合权重 → `mat1/mat2 must have the same dtype`。
  修复: lew_loss 计算包 `torch.autocast(device_type=..., dtype=torch.bfloat16)`。
- 验证: 修复后 150/150 步 1分18秒成功（修复前 30s 内必炸），显存仅 1.8GB。
- 调试法: 后台 `nice -n 10 .venv/bin/python -m lerobot.scripts.lerobot_train --config_path <cfg>` 抓 stdout 报错。

## 5. Scope loss 三模型统一量纲（归一化）

- 为什么 SmolVLA loss 小: ACT = 动作空间 MSE（`(rad/s)²` 量级大，80→5）；SmolVLA 系 = DiT 扩散**噪声空间** MSE
  （modeling_smolvla.py:809 `F.mse_loss(u_t, v_t)`，N(0,1) 量级 ~0.5）。绝对值跨模型不可比。
- 归一化实现: 每条曲线除以前 3 点平均（**单点基准不稳** — SmolVLA 首点 0.4357 异常小，次点 1.049/0.4357=2.4 暴涨）。
  `<3 点用首点`。y 轴标签改 "loss (归一化 · 起点=1)"。
- 训练初期 loss 波动（0.44→1.05）是 DiT 噪声预测真实现象，不是变差。

## 6. Scope 显示约定（用户铁律，反复修正后定型）

- **训练中 1 点不显示**（歧义）; ≥2 点才画。ScopeWidget 内 `n<2: continue` 兜底 + FlowScopeDialog 过滤。
- **未训练默认空**（不显示旧曲线）; 单模型训练启动只删自己 policy 的曲线文件（保留其他模型已完成曲线）。
- **三模型对比（≥2 训练节点）启动时清空全部 train_curve_*.json**（本轮从零开始，避免上轮残留混淆）。
- 图例色块必须显式 `setBrush(颜色)` + 画完 `setBrush(Qt.NoBrush)`：1 点圆点残留的 brush 会让所有图例色块同色。
- 图例移出波形循环统一绘制（1 点曲线 continue 曾跳过图例 → 曲线没名字）。
- x 轴用真实 step（curve 数据 `[step, loss]` 第一元素），不用数组索引。
- 全局适配按钮点击需反馈（按钮变「✓ 已全局适配」1.5s）——功能正常但无视觉变化，用户以为"第二次没用"。

## 7. 训练流程用户偏好

- **训练步数先小后大**: 150→100→50。用户明确: "都改成50步吧，先跑完流程，再增加步数"。三模型对比 50 步 ≈ 1.5 分钟跑通。
- 训练节点**双击 → 训练配置对话框**（steps 10-5000 / batch / lr），右键菜单也有「🎛 训练配置」；参数存 node params，node_logic 透传下次训练生效。
- 训练中每 5-10 步日志区输出 `📈 pname 训练中: X/Y 步 · loss Z`（防"感觉卡住"）；log_freq 已 50→5。
- 训练子进程 `nice -n 10` 降优先级（防 CPU 满载卡 UI）；`stop_sim` 用 processEvents 轮询（200×50ms）代替阻塞 `wait(10000)`。
- 运行反馈三层: 按钮变「⏳ 运行中…」+ 非模态弹窗「🚀 正在执行 N 环节」3s 自动关 + 日志流程行。
- 总系统模板点运行自动展开子系统再跑（start_sim 检测 subsystem → _open_subsystem → 重收环节节点）。

## 8. 验证纪律（本会话反复确认）

- GUI 改动: `QT_QPA_PLATFORM=offscreen` + **tempfile.mkstemp** 建 `/tmp/hermes-verify-*.py` + terminal 直接执行（execute_code 内 subprocess 不被系统追踪且 60s 上限——模型加载 41s+ 会触发 stale 记录）。
- 跑完即删；write_file 固定路径会被系统 stale 追踪，统一用 tempfile。
- 测试脚本里节点名**避开 "训练" 关键词**（node_logic.execute_node_logic 会触发真实训练而不是你的 mock fn）。
- 崩溃复现用 `faulthandler.enable()` + 分步 print 定位精确行。
