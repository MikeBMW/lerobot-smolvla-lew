# PyQt5 exit 134 QThread 崩溃根治手册 (2026-08-05, 10 次修复终局)

错误特征: 后台进程 exit 134 + `QThread: Destroyed while thread is still running` + `tcsetattr: Inappropriate ioctl for device`。
反复出现 10 次, 前 9 次都是外围清理, **第 10 次才是真根因**。

## 真根因 (#10, faulthandler 定位 3404 行 lambda)

```python
# ❌ 致命写法 — finished 回调里置 None
worker.finished.connect(lambda: setattr(self, "_worker", None))
```

机制: finished 信号回调里置 None → worker 对象失去最后一个 Python 引用被 GC 回收,
但 QThread 底层线程未完全终止 (PyQt 竞态窗口) → 析构时 SIGABRT。
**这个竞态在任何训练/任务正常完成时都可能触发, 与关不关窗口无关** — 这就是"修了还崩"的真相。

排查手段: `faulthandler.enable()` + 逐行 print + 分步脚本, 崩溃栈会精确指到 lambda 所在行。

## ⚠️ #10 修复的副作用 → 最终写法 (#11, 流程卡死, 699b41d7)

#10 用 `lambda _w=worker: setattr(self, "_worker", _w)`（保留引用）修好崩溃后,
**又引入新 bug**: `_done`(finished_ok 回调) 里 `self._worker = None` 释放后,
finished 回调**又把旧 worker 对象设回 `_worker`** → 下一个环节检查
`cur.isRunning()` 时线程未完全结束 (竞态) → **ACT 训练完成后 SmolVLA 启动被拦截**
(用户日志: 「✅ ACT 训练完成」后跟两行「⏳ 上一个任务还在跑, 请稍候…」)。

**最终正确写法（崩溃与流程卡死都治）**:
```python
def _done(ok, summary):
    ...  # 节点状态/日志
    cur = getattr(self, "_worker", None)
    if cur is not None:
        cur.wait(100)          # 等线程真正结束 (finished_ok emit 时线程还没 return)
        self._worker = None    # 线程已死 → GC 安全
    self._flow_next()          # 全流程流转 (在释放之后!)

worker.finished.connect(lambda: None)   # no-op! 释放完全交给 _done
```
- 5 处 finished 回调全部改 no-op (`lambda: None`); 防 GC 竞态由 `_done` 的 `wait(100)+置 None` 承担。
- 轮询型 worker (_acq_worker/_remote_worker) 没有 _done 释放 → 靠下一轮创建时覆盖引用回收 (旧线程已死, GC 安全); closeEvent 里 isRunning() 检查旧对象返回 False 不会误拦。
- **验证套路 (FLOW-CHAIN)**: 两个伪环节 fn1(0.3s)→fn2, `_run_node_stage` 串行 → 断言 fn1 后 `_worker is None`、fn2 启动 1 次、日志无「上一个任务」。
- **测试节点名坑**: 伪节点 name 不能含「采集/训练/验证/集成/部署/推理」— `node_logic.execute_node_logic` 会拦截并跑**真实训练** (日志出现「🧠 训练配置」), 测试会假死。用「环节A/环节B」这类无关名。

## 崩溃修复全清单 (共 10 处)

| # | 位置 | 漏掉的清理 |
|---|------|-----------|
| 1 | CICDPanel.closeEvent | _acq_timer/_acq_worker (aedf09fb) |
| 2 | SimulinkModule.closeEvent | _rec_timer 录屏 QTimer (用户在录制中关窗) |
| 3 | SimulinkModule 主类原本无 closeEvent | CICDWorker(_worker) QThread |
| 4 | StudioMainWindow (studio.py) 无 closeEvent | _orin_timer/_live_timer/_replay_timer/_stats_timer + Rerun QThread |
| 5 | SimulinkModule.closeEvent | 训练中关窗 wait(3000) 不够 → pkill 训练子进程 + wait(10000) |
| 6 | CICDPanel.closeEvent | 漏清 _worker (947行) |
| 7 | InferenceVideoDialog 无 closeEvent | _timer(播放)/_poll_timer(rollout轮询) |
| 8 | CICDPanel.closeEvent | 漏清 _remote_worker (1103行) |
| 9 | closeEvent | wait 超时后置 None 仍崩 → pkill -9 + wait(15000) + 失败保留 _keep_worker |
| 10 | **真根因** | finished 回调置 None → GC 竞态 → 5 处 lambda 改保留引用 (58ab40cf) |
| 11 | #10 副作用 | 保留引用 lambda 覆盖 _done 释放 → ACT 完成后下环节被 isRunning() 误拦 (「上一个任务还在跑」×2) → _done 里 wait(100)+置 None+_flow_next, finished 回调改 no-op (699b41d7) |

## 铁律

1. **任何 QThread/QTimer 必须 closeEvent 清理**; 新增线程/定时器先登记再创建。
2. **finished 回调只做 no-op** (`lambda: None`); worker 释放完全交给 `_done`(finished_ok) — 先 `wait(100)` 等线程真正结束再置 None (线程已死 GC 安全)。**不要**在 finished 回调置 None (GC 竞态崩), **也不要**保留引用设回 (覆盖 _done 释放 → 流程卡死)。
3. closeEvent 清理 worker: 先 pkill 子进程 (`pkill -9 -f lerobot.scripts.lerobot_train` + `tools.cicd_pipeline`) 再 `wait(15000)`; 超时保留引用防 GC。
4. 训练子进程杀法: SIGTERM 可能被 Python 清理逻辑拖住, 直接 `pkill -9`。
5. **训练时主窗口卡顿** (用户: "运行时候主窗口就卡住了不能拖动"): 训练子进程 CPU/GPU 满载抢占资源 → WSL2 下 GUI 线程调度延迟 → 窗口拖不动。修复 (1951bad5): 训练命令前缀 `nice -n 10` — 低优先级, CPU 优先让给 GUI/系统, 训练略慢但界面流畅。注意: 卡顿≠线程阻塞, 先查子进程 CPU 占用再怀疑主线程死锁。
6. 全部 CICDWorker 创建点: 944/1109/3271/3392/4253 (simulink_module.py) — 全要保存到 self 属性。

## offscreen 测试坑 (反复踩)

- `QMessageBox.exec_()` 模态在 offscreen 无用户点击 → 卡死 (exit 124 超时)。**产品里也避免 exec_**: 非模态 `mb.show()` + `QTimer.singleShot(3000, mb.close)` — 不阻塞主线程, 训练中日志照常刷新。
- offscreen 下 `time.sleep` 不驱动 QTimer, 需 `app.processEvents()` 循环驱动。
- QWheelEvent 构造需完整 9 参 (pos, globalPos, pixelDelta, angleDelta, buttons, modifiers, phase, inverted, source)。
- 验证脚本路径: tempfile.mkstemp 前缀 hermes-verify-, terminal 直接执行 (execute_code 内 subprocess 60s 上限 + 不被系统追踪), 跑完即删。
- 嵌套引号坑: `python3 -c` 内嵌含引号/`\n` 的验证脚本, 多层转义必坏 → SyntaxError (unterminated string literal)。对策: tempfile.mkstemp 建路径后直接 `write_file` 覆写该路径 (write_file 无转义问题), 再 terminal 执行。
- 测试脚本自身也可能崩 (创建多实例 SimulinkModule + worker 未清理) — 区分产品 bug 与测试脚本 bug。

## 🚨 WSLg 模态对话框不可见 = "界面卡死" 假象 (41048624 → **89cc9a26 最终根治**, 用户 3 次报"界面卡住了/还是卡死/按啥都不好使")

诊断先决条件: **进程活着 (State S/sleeping) + 无训练进程 + 负载低 (load < 0.2) + 主线程 poll_schedule_timeout** = 不是真死锁, 是**模态框弹到不可见位置**。

机制: `dlg.exec_()` 模态会禁用父窗口全部输入 → 对话框若弹到屏幕外/未渲染 (WSLg 下常见) → 用户点击主窗口全部无效, 观感=完全卡死。

**演进教训 (用户 3 次反馈才根治)**:
1. 第一次 (41048624): 只给 on_train_config 弹窗前 `dlg.move(父窗口居中) + raise_ + activateWindow`, **exec_ 模态保留** → 用户仍报"还是卡住"。
2. 第二次 (f0bf1dca): 只把 TrainConfigDialog 改非模态 (`show()` + WindowStaysOnTopHint + finished 回调) → 用户仍报"还是卡死"。
3. **最终 (89cc9a26)**: 排查发现**还有 7 处 exec_ 模态** (BlockParamsDialog/NodeLogicDialog/FlowScopeDialog/InferenceVideoDialog/ModelCompareDialog/ScopeCompareDialog/对比面板 2919) — 用户卡的是**别的对话框** (双击普通节点→BlockParamsDialog, 右键→节点参数/节点逻辑)。教训: **"改了还卡"= 还有漏网的 exec_**, 全文件 `grep exec_()` 逐个清。

**最终写法 — 通用非模态函数, 全部对话框统一走它**:
```python
def _show_nonmodal(self, dlg, on_accept=None):
    """通用非模态对话框: 居中+置顶+finished回调+show, 主窗口永不被禁用"""
    try:
        dlg.move(self.mapToGlobal(self.rect().center()) - dlg.rect().center())
    except Exception:
        pass
    dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowStaysOnTopHint)
    dlg.raise_()
    dlg.activateWindow()

    def _done(result):
        if result == QDialog.Accepted and on_accept is not None:
            try:
                on_accept()
            except Exception:
                pass
        dlg.deleteLater()

    dlg.finished.connect(_done)
    dlg.show()
```
- **8 处对话框全部改非模态**: on_train_config / on_show_node_logic(NodeLogicDialog) / on_node_params(BlockParamsDialog) / on_node_activated 第3分支(BlockParamsDialog) / on_scope(FlowScopeDialog) / on_infer_video(InferenceVideoDialog) / ModelCompareDialog(3507) / ScopeCompareDialog+对比面板(2919/2929)。
- **唯一保留 exec_**: QFileDialog (文件选择, 需要返回值) + QMessageBox(_qmsg, 有按钮不会不可见)。
- 非模态对话框的保存逻辑放 `finished` 回调 (result==Accepted 时执行), 别指望 exec_ 返回值。
- 验证套路 (ALL-NONMODAL): 依次调 on_node_activated(普通节点)/on_node_params/on_show_node_logic/on_scope → 每次 `assert w.isEnabled()` (主窗口不被禁用)。
- 应急: 告诉用户 **Esc 也能关模态框** (老版本应急解锁); 新版本无模态框不存在此问题。
- 与 offscreen exec_ 卡死 (exit 124) 是两码事: offscreen 是"没用户点按钮", WSLg 是"弹了但看不见" — 症状都是界面无响应, 但一个是测试环境一个是真实环境。

## Scope 波形新规则 (2026-08-05 用户反复强调)

1. **训练中不显示任何曲线** (1 点会引起歧义) — `len(cv) < 2` 不进 series, 指标行只显示 `⏳ 训练中: X`; ScopeWidget.paintEvent 的 n<2 分支也 continue (兜底不画圆点)。
2. **Scope 默认空 + 保留已完成模型曲线 (51097377 最终语义)**: on_train 启动**只删当前 policy 自己的曲线文件** (`train_curve_{policy}.json`), **保留其他模型已完成曲线** — 用户纠正: "现在smolvla训练, 为什么之前的act波形没有了" (原实现清空全部文件, 三模型对比时 SmolVLA 训练把 ACT 曲线删了)。Scope 不再按 mtime 过滤 (原 `now - mtime > 600` 跳过已删除), 保留所有已训练曲线。教训: "scope先清空"(默认空) 是打开时无默认线, 不是训练启动清掉别人的曲线 — 三模型对比需要同时看已完成模型波形。
   - **⚠️ 再修正 (5b58c868, 用户"打开就有个smolvla+lew")**: 单模型训练保留历史**又**导致上轮残留曲线显示混淆 → 最终语义 = **按训练节点数分派**: `_start_canvas_flow` 里 `_train_stages = [s for s in stages if "训练" in s[2]]`, **≥2 个训练节点 (三模型对比) 启动时清空全部曲线文件** (本轮从零开始, 日志「🧹 三模型对比: 已清空旧曲线」), **单训练节点不清** (保留历史)。教训: 用户对"清空/保留"的期望按场景走 — 多模型对比 = 本轮三模型完整重来; 单模型 = 别动别人的历史。
3. **图例色块全变同色 bug**: 画 1 点圆点时 `setBrush(橙色)` 残留 → 图例空心 drawRect 被残留 brush 填充 → 所有色块同色。修复: 图例色块显式 `setPen(color)+setBrush(color)` + 画完 `setBrush(Qt.NoBrush)`。
4. **图例必须在波形循环外统一绘制**: 原在循环内, 1 点曲线 continue 跳过图例 → 训练中曲线没名字。
5. **x 轴用真实 step** (curve 数据 `[[step, loss], ...]` 的 step), 不是数组索引 (用户: "为什么只显示 1 2 4 step")。
6. **坐标轴带单位含义**: 纵轴 `loss (归一化 · 起点=1)`, 横轴 `step (训练步数)` (cbe426c1 后; 早前是 `loss (MSE · 动作预测误差)`)。
7. log_freq 50→10→5 (3 个 config + _parse_loss_curve 步进推断同步); **steps 150→100→50** (8e6586ab → 0fb489bc, 老倪"训练时间太长"→"都改成50步先跑通流程再增加步数"; 模板10处+node_logic+3 config) — **当前默认 50 步** = 10 点 (log_freq 5); 2 点门槛 (≥2 才显示) 出现在 10 步 = 20%。步数可经训练节点双击 TrainConfigDialog 调 (见 scope-loss-session.md)。背景: 用户"训练到12%为什么scope还没显示" — 12%≈18步恰好卡在 1→2 点边界。实测 ACT 100 步 26s (6.9 step/s)。
8. 曲线文件 key 用 policy (唯一), 显示名映射 `_DISPLAY = {act:ACT, smolvla:SmolVLA, smolvla_lew:SmolVLA+LEW}`。
9. **🌐 全局适配按钮** (用户: 鼠标缩放一下曲线就找不到了): ScopeWidget.fit_all() 清手动缩放/平移回自动范围, 双击复位复用; FlowScopeDialog 按钮行加「🌐 全局适配」+ 操作提示 (滚轮缩放/中键平移/双击复位)。验证: 缩放后点全局适配精确回初始范围。
   - **点击反馈 (3e6b2161, 用户"第二次点为什么就没用了")**: 功能实测一直正常 (连续 zoom→fit→zoom→fit 每次 manual 都清、范围精确回初始), 用户觉得"没用"是**无视觉变化** → 加 `_fit_clicked`: 适配后按钮变「✓ 已全局适配」`QTimer.singleShot(1500, 恢复)`。教训: **"第二次点没用/没反应"先验证功能是否真失效 (offscreen 连续缩放+适配断言 manual 清除), 功能正常 = 加点击反馈而不是改逻辑**; 任何一键复位/适配按钮都要有点击后的状态确认。
   - **空 series 陷阱**: 无曲线数据时 `_y_range()` 返回 (-1,1) 兜底, 缩放/适配都"无效果" (manual 不设置) — 测试要 `set_series` 造数据再验, 别拿空 Scope 下结论。
10. **⚖️ 三模型 loss 统一量纲 — 归一化 (cbe426c1 + ac8e3033, 老倪"三个模型改成统一量纲")**: 三条曲线各自除基准 → 都从 1.0 附近开始, 直观对比下降速度/幅度; 指标行显示相对下降百分比 (↓93.8% 等)。**归一化基准坑 (ac8e3033, 老倪"smolvla刚开始loss怎么提高了")**: 基准**不能取首点** — SmolVLA 首点 0.4357 异常小 (训练初期波动), 次点 1.049/0.4357=**2.4 倍暴涨**, 观感像 loss 提高。最终写法: `base = mean(ys[:3]) if len(ys)>=3 else ys[0]` (前 3 点平均抗波动, SmolVLA 最大 2.4→1.30)。**训练初期 loss 波动本身是真实的** (SmolVLA DiT 噪声预测 0.44→1.05 再回落, 不是变差)。**为什么必须归一化 (MSE 量纲知识, 老倪问过两次"为什么SmolVLA loss这么小")**:
    - ACT 的 loss = 动作空间 MSE (`MSE(pred_action, true_action)`, 关节速度 rad/s 量级 ±10 → 误差² 几十, 80→5), 单位 (rad/s)²。
    - SmolVLA 系 loss = **扩散噪声空间 MSE** (`modeling_smolvla.py:809 F.mse_loss(u_t, v_t)` DiT 去噪损失, 预测加噪动作的噪声, 噪声 N(0,1) 量级 → 天然 ~0.1-1)。
    - **跨模型绝对值不可比** (量纲不同, 5 不小 0.75 不大); 要比看各自下降趋势或动作空间 RMSE / rollout 轨迹对比 (🎥 推理对比节点)。
    - **归一化后 SmolVLA 仍比 ACT 高 = 100 步内收敛显著慢, 不是能力差** (老倪"smolvla比act loss大说明什么", 实测 SmolVLA 原始 loss 0.53→0.52 几乎没降): 原因 = ① SmolVLM2 主干冻结 (可训练仅 4.4%, 只有 DiT 动作头在学) ② DiT 扩散损失收敛慢 ③ 1-2 step/s 每步学得慢 → **同样步数预算不公平** (ACT 100 步 26s 大幅收敛, SmolVLA 100 步才刚起步)。公平对比方案: 按模型区分步数 (ACT 100 / SmolVLA 系 300) 或固定训练时长。SmolVLA 系的优势在视觉泛化 (预训练特征换场景鲁棒), 训够步数才体现。
11. **0 点曲线文件诊断**: `train_curve_<policy>.json` 存在但 curve=[] = 训练**秒失败** (子进程启动即退, 无 loss 行, 走了最终落盘写空)。先别改代码 — 手动跑一次该 policy 训练 (`nice -n 10 .venv/bin/python -m lerobot.scripts.lerobot_train --config_path config_<policy>_metaworld.yaml`) 验证模型本身正常 (实测 ACT 100 步 26s 成功), 失败多为数据源/并发抖动, 重跑即可。

## 录屏 (🔴/⏹) 新规则

1. **MP4 0 字节 bug**: libx264 要求宽高偶数, 窗口高 929 (奇数) → 编码失败。修复: ffmpeg 加 `-vf "pad=ceil(iw/2)*2:ceil(ih/2)*2"`。
2. **停止按钮无响应**: 500ms grab 整窗过重 → QTimer 事件堆积 → 事件循环占满 → 按钮点击排不上队。修复: 采集 500ms→1000ms (1fps) + 防堆积标志 (上一次没完成就跳过)。
3. **2x 加速正确做法**: `-framerate 1` 输入 + `-r 2` 输出**不加速** (时长按输入帧数) — 直接 `-framerate 2` 播放 1fps 帧。
4. JPEG q85 快照 (PNG 大图压缩卡 UI) + ffmpeg 合成放后台线程 (停止按钮 0.001s 立即返回)。
5. 视觉反馈: 录制中按钮变「⏺ 录制中…」红色呼吸闪烁 (QTimer 切换样式) — 用户点录制要有明确反馈。
6. 输出: `reports/screenrec_<时间戳>/screen_rec.mp4`。

## ▶ 运行反馈链 (用户 3 次反馈"没反应")

1. 点击瞬间按钮变「⏳ 运行中…」禁用 + 日志「指令已接收」。
2. 有环节节点 → 弹非模态窗「🚀 正在执行 N 个环节: X→Y→Z」(show + 3s 自动关)。
3. 总系统模板 (无环节节点) → 自动 `_open_subsystem` 展开 → 重新收集环节节点 → 启动真实流程。
4. 无环节 → 明确日志 + bubble 提示 (不静默进仿真)。
5. **训练中每 log_freq(5) 步输出进度日志** `📈 pname 训练中: X/Y 步 · loss Z` (100 步训练共 20 行) — 用户以为"卡住"的真相是训练在跑 (CPU 460%) 但日志区无输出。
6. 拦截提示统一: `⏳ 上一个任务还在跑, 请稍候… (训练中, 日志区可看到 📈 进度)` (4 处)。
7. **停止按钮真实流程中必须可用** (用户: "运行点击之后停止按钮怎么变灰了"): btn_stop 初始灰, `_start_canvas_flow` 启动时必须 `setEnabled(True)` (真实流程分支原来漏了, 只有仿真分支启用); `stop_sim` 要**真终止训练** — 检测 `_worker.isRunning()` → `pkill -9` 训练 + 清 `_flow_queue`, 不能只停仿真 timer; 全流程结束 (`_flow_next` 队列空) 恢复 btn_run「▶ 运行」+ btn_stop 灰。
8. **🚨 stop_sim 的 `w.wait(10000)` 阻塞主线程 = 点停止时界面死 10 秒** (用户: "怎么又卡死了", fb3affd6): worker 卡在数据拉取 (requests) 时 pkill 杀不掉请求, `wait(10000)` 期间主线程完全阻塞 → 窗口拖不动像死机。**交互路径 (按钮回调) 禁止阻塞 wait** — 改 `processEvents` 轮询: `for _i in range(200): if not w.isRunning(): break; app.processEvents(); time.sleep(0.05)` (最大 10s, 期间界面可拖动/日志刷新)。**区分: closeEvent 里可以阻塞 wait (窗口反正要关), 用户可交互的按钮回调绝不能阻塞**。

## 复现验证命令

```bash
# 崩溃复现 (修复前必 EXIT=134): 加载三模型对比 → start_sim → worker running → w.close()
cd ~/lerobot-smolvla-lew && python3 -c "
import os; os.environ['QT_QPA_PLATFORM']='offscreen'
# ... 见会话: SimulinkModule 构造 + load_reference_app_by_name('🔬 三模型对比') + start_sim + close()
"
```
