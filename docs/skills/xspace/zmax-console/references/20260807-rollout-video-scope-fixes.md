# 2026-08-07 视频/Scope/续训运维修复实录

## 1. GUI 重启三连坑 (老倪反复"没重启/没看到重启")

- **pkill -f 'studio.py' 自匹配自杀**: `pkill -f 'studio.py'` 的命令行自身含 "studio.py"
  → pkill 匹配自己 → exit -15 (每次都这样)。但 GUI 进程也被匹配到 → 实际被杀成功。
  **确认杀没杀到**: `ps aux | grep '[s]tudio.py'` (方括号防自匹配), 看 PID 是否变化 +
  `ps -o pid,lstart -p <pid>` 看启动时间。
- **WSLg 窗口无缝重开**: 重启后 auto_run 自动切回 simulink 页 + open_compare5 →
  窗口位置大小一样, 老倪觉得"没关过/没重启"。**解释要点**: 进程是新的 (lstart 证明),
  内容也是新的 (代码已加载); 让他用功能验证 (拖 Frame 滑块) 而非窗口视觉。
- **simulink 是 studio.py 的一页** (QStackedWidget 第 11 页, `self.stack.addWidget(self.simulink)`,
  auto_run 时 `setCurrentWidget(self.simulink)` + `open_compare5()`) — 不是独立进程,
  杀 studio.py 即杀 simulink 画布。老倪说"控制台是 simulink 功能没关" = 窗口无缝恢复的观感。

## 2. 曲线文件被训练链清空 (两次教训, 数据丢失!)

- **症状**: 训练曲线 json (reports/train_curve_*.json) 神秘消失/变成 0-50 点残留。
- **根因**: GUI 重启后 auto_run 触发训练链, **训练启动瞬间清空/覆盖旧曲线文件**
  (on_train 里 `os.remove(train_curve_<policy>.json)` + 新训练实时落盘覆盖);
  训练被 kill 后只剩残留 (act 50 点 + 其余 0 点) → Scope 无曲线 + _check_newer_ckpt 误判。
- **修复 (2026-08-07)**: `_auto_run_compare5` 改为 **默认不自动训练** — 只有
  `ZMAX_AUTO_TRAIN=1` 环境变量才 start_sim 训练; 重启只加载画布。busy 检测 (有训练进程跳过)
  保留。
- **恢复路径**: 曲线数据丢了只能重训 (act 1000 步 ~1min / smolvla ~9min / lew ~9min)
  或从 /tmp 训练日志解析恢复 (vla4.log/retrain_awe.log 有 action_loss 行)。
- **教训**: 重启 GUI 前先确认无训练进程 + auto_run 不会触发训练; 曲线 json 是易失资产,
  重要曲线先备份。

## 3. rollout_video.py 推理修复 (三个根因, 视频"没动/动作≈0")

1. **obs dict 解包**: V3 环境 `obs` 是 dict (observation.state/image) — `np.asarray(dict)`
   → 0 维对象数组 → state 全零 → 所有模型推理异常。修:
   ```python
   if isinstance(obs, dict):
       _st_raw = np.asarray(obs.get("observation.state", np.zeros(st_dim, dtype=np.float32)), dtype=np.float32)
   ```
2. **stats 归一化维度广播**: `(st - sm) / ss` 中 stats 是旧 3D 而 state 39D (完整观测)
   → `operands could not be broadcast (39,) (3,)`。修: stats 维度不足补零
   (`np.pad(sm, (0, st_dim-sm.size))`, ss pad 后 **+1e-6 防除 0 NaN** — 否则动作 NaN)。
3. **ACTPolicy 的 env_state**: 若模型有 `encoder_env_state_input_proj`, 39D = robot(3) + env(36)
   → 从权重维度推断拆分 batch["observation.environment_state"]。诊断用
   `_tb.print_exc(limit=3)` (except 里) 定位真实错误行, 别只信异常消息。

## 4. 视频方向/视角 (老倪多次纠正, 最终规则)

- **视角**: rollout 对比视频用 **`--camera corner2`** (能看到插槽!) — 默认 `corner` 看不到。
  MLP/专家视频 (rollout_mlp/rollout_expert_full) 是正确参考 (corner2 + --rotate-ccw)。
- **方向**: `--rotate-ccw` (rollout_video.py 内 `np.rot90(rgb, k=2)` = 180°)。
  13:35 批次用 corner2+rotate 生成 (正确); 重生成时漏参数 → 方向/视角全错。
- **统一验证**: 亮度分布对比 (上半/下半 mean 一致 = 同视角): MLP 136/128 为基准。
- **改视角/方向后要重跑全部 5 个模型** (act/smolvla/smolvla_lew/vla_touch/awe_zflow),
  MLP/专家不动。

## 5. lerobot 训练日志解析 (step:1K 陷阱)

- lerobot_train 日志 `INFO ... step:990 ... loss:1.818` — step 冒号分隔。
- **1000 步显示 `step:1K`** → 正则 `step[:=]?\s*(\d+)` 误解析成 step=1 → 曲线尾点 [1, x]。
  修: `log = re.sub(r"step:(\d+)K\b", r"step:\1" + "000", log)` 先展开 K 后缀;
  正则加 `\b` 边界。解析后去重 (`seen` set) + sorted。

## 6. 微调续训 (替代 resume, 更可靠)

- lerobot draccus 的 `resume: true` 需要 config 里 `config_path:` 字段指向
  checkpoint 保存的 train.yaml (目录结构复杂, 报 "A config_path is expected when resuming")。
- **可靠方案**: 不用 resume — `--policy.path=<ckpt>/pretrained_model` 加载 1000 步权重
  + **新 output_dir** (时间戳) + steps 4000 → 微调续训 (loss 从旧值继续降, 等价续训)。
- **曲线合并**: 新训练从 step 0 开始 → 旧曲线 + 新曲线 **step 偏移 +1000** 后合并,
  用 `setdefault` (旧步不被新覆盖, 因新步已偏移) + sorted + 去重。
- **失败检查**: 训练后 `grep -qE "FileExistsError|Traceback|Error:"` log, 失败不合并曲线。

## 7. 视频对比对话框 (InferenceVideoDialog) 修复

- **_check_newer_ckpt 误判"新 checkpoint"→ 每次打开都重新生成 (闪一下/视频没了)**:
  curve json 残缺 (0-50 点残留) 但 ts 新 → 误判。修: `len(d.get("curve") or []) < 100` 跳过
  (非正常 1000 步训练不算新)。
- **on_infer_video 的帧检查目录映射**: expert_mlp/expert_policy 帧在 rollout_mlp/
  rollout_expert_full (不是 rollout_final_<p>) — 触发前检查漏映射 → 误判无帧 → 重新生成失败
  → "视频没了"。修: `_dm = {"expert_mlp": ("rollout_mlp", ...), "expert_policy": ("rollout_expert_full", ...)}`。
- **模型名标题位置**: 老倪嫌"文字飘到上面窗口"→ 标题从视频框上方改为**叠加在视频框左下角**
  (QGridLayout 同 cell + `Qt.AlignLeft|Qt.AlignBottom` + 半透明底 rgba(13,17,23,140) 水印样式)。
- **白屏**: `_tick` 里 `lab.size()`=0 (对话框未显示) → `scaled(0,0)` 空白。
  修: 尺寸有效才 scaled, 否则 `lab.setPixmap(pm)` 原图。

## 8. Scope loss 曲线带训练时间 (老倪要求)

- FlowScopeDialog 指标行格式: `ACT·08-07 15:37: 80.5→1.99 (↓97.5%)`。
- ts 字段 `%Y%m%d_%H%M%S` (15 位) 切片: **`_ts[4:6]-[6:8] [9:11]:[11:13]`** (别漏中间的下划线,
  8 位日期 + "_" + 6 位时间; 用 [8:10] 会取到 "_1")。
- _DISPLAY 映射含全部 7 模型 (vla_touch/awe_zflow/expert_mlp/expert_policy)。

## 9. 布局演进 (老倪逐步要求, 最终形态)

- 12 列: 列9=训练/基准 → 列10=🎮仿真推理·<模型> → 列11=🎮仿真视频·<模型> (每模型一行对应)。
- 评估行 (行8): 列7=🎮仿真推理对比 (全模型) → 列10=📊对比评估 Scope (仿真) →
  列11=📄PDF 技术选型报告 (最右, 与 Scope 同行)。
- 节点名/desc 带"🎮 仿真"标注 (desc 显示"metaworld 环境, 非 Orin 真机" — 老倪确认视频是
  本地仿真输出, 必须让用户看得到)。
- **id 分配 = specs 顺序, layout 只按名字摆放** → 改布局/加节点不动旧 links 的 id,
  只需在 specs 尾部追加新节点 (id 顺延) + 追加新 links。
- 背景行 n_cols 10→12 (open_compare5 调 _draw_model_rows 时传)。
