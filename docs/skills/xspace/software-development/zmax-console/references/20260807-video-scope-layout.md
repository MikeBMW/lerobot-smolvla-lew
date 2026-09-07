# 2026-08-07 视频对比对话框 / 12列布局 / Scope / 评分体系 系列坑

## 1. 模板加载 id 分配机制（改布局不动 links 的关键）
- **id 按 specs 顺序分配**（add_node 遍历 specs），**layout 只按名字摆放**（同名可多实例）。
- 改 layout（节点增删/移动列）**不需要重映射 links**——旧 86 条 links 数字 id 全部保留，
  只在 specs 尾部追加新节点（id 自动续号）+ 追加新 links。
- 验证方式：`ids = {n["id"] for n in mod.nodes}; all(lk["f"] in ids and lk["t"] in ids ...)`。
- 注意：**节点 desc 存在 params.desc**（不是 node["desc"]）——验证脚本查错字段会假失败。

## 2. 画布可见性分层（用户"看不到改动"的根因）
- 节点 **name 画布直接可见**（标题）；**desc 只双击/悬停才见**。
- 老倪要求"用户能看到"的信息（如"仿真输出/非 Orin 真机"）必须改 **name** 或加可见 badge，
  只改 desc 他会说"没看你改啥啊"。
- 改名后 layout 引用、`"对比评估" in name` 这类匹配（包含匹配）兼容；精确 name 匹配的
  NODE_RUN_ACTIONS 要检查。

## 3. 视频对比对话框（InferenceVideoDialog）四大坑
- **白屏**：`_tick` 在对话框未 show 时 `lab.size()=0` → `pm.scaled(0,0)` 空白。
  修：尺寸>0 才 scaled，否则 `lab.setPixmap(pm)`（QLabel 自适应原图）。
- **闪一下再打开**：`_check_newer_ckpt()` 把"训练中断残留的残缺曲线"（如 act 50 点、
  ts 却新）误判为新 checkpoint → 每次打开触发重新生成 rollout。
  修：`len(d.get("curve") or []) < 100` 跳过（非正常 1000 步训练不算新）。
- **视频"没了"**：`on_infer_video`（simulink_module.py）的帧存在检查与对话框 `_load_frames`
  是**两处独立候选目录逻辑**——expert_mlp/expert_policy 的 `_dir_map`
  （rollout_mlp/rollout_expert_full）只加了一处 → 触发前检查误判无帧 → 触发重新生成
  （rollout_video.py 不支持 expert policy）→ 失败。改一处必须同步另一处。
- **标题飘到上面窗口**：模型名 cap 原本在视频框**上方**（QVBoxLayout 顶部）→ 视觉归属上排。
  修：cap 与 lab 同一 cell 叠加（QGridLayout addWidget 同 cell + AlignLeft|AlignBottom），
  半透明深底水印（`background:rgba(13,17,23,140)`）+ `WA_TransparentForMouseEvents`。

## 4. rollout_video.py 推理异常（动作≈0 的根因）
- **V3 环境 obs 是 dict**（observation.state / observation.image）——
  `np.asarray(dict)` → 0 维对象数组 → state 全零 → 所有模型动作≈0（"视频没动"）。
  修：`if isinstance(obs, dict): st_raw = obs.get("observation.state")`。
- **ACT 39D 完整观测 = robot(3) + env(36)**：ACTPolicy 需要 `observation.environment_state`，
  只传 state 39D → `operands could not be broadcast (39,) (3,)`。
  按**权重维度**推断拆分（`model.encoder_env_state_input_proj.weight.shape[1]`），不依赖 config
  （config 可能无 input_features 键）。此修复 2026-08-07 尚未完全验证（见第 7 节遗留）。
- 推理异常时回退零动作（视频仍展示环境）——排查"视频没动"先查 st 是否全零。

## 5. score_model _TAB 硬编码优先（改评分先改 _TAB）
- generate_report.py `score_model` 用 `_TAB`（表格权威分数）**优先于公式**：
  `if policy in _TAB: s[_k] = float(_TAB[policy][_i])`。
- 改 MODELS 字段（world_model="✅ 世界模型…"）**不影响评分**——必须同步改 `_TAB` 对应位
  （LEW/AWE 世界模型位 4.5→8.5 教训）。`_TABKEYS` 顺序: conv, world_model, tactile, edge,
  throughput, gpu, data, video。
- **真值锚点口径**：官方专家 6.1 分低不是 bug——8 维评分是"学习模型技术选型"维度
  （45% 权重=训练性），专家不训练→收敛/吞吐中性分；成功率 85% 在评分体系外。
  报告需加"🏆 真值锚点说明"（不参与选型排序），否则老倪质疑"为什么真值不是最高"。
- tactile 判断要含 arch"视触觉"（不只 category+"Marker"）；AWE 有 SigLIP 视触觉 → 9.0。

## 6. 训练恢复 / 曲线 / 清理
- **重启 GUI 会覆盖曲线文件**（auto_run 触发训练链 → on_train 启动时删 train_curve_*.json）。
  教训：GUI 重启必须防自动训练（busy 检测 + `ZMAX_AUTO_TRAIN=1` 才训练，默认只加载画布）。
  曲线 json 被覆盖后唯一真实恢复路径 = 重训（无备份）；v10 报告 PDF 里的曲线图是 raster 无法提取。
- **从训练日志秒级恢复曲线**：/tmp/retrain_vla.log、retrain_awe.log 等有 action_loss 行 →
  正则解析落盘（比重训快 3 个数量级）。先查 /tmp/*.log 再决定重训。
- **step:1K 解析 bug**：lerobot 日志 1000 步显示 `step:1K` → 正则误解析成 step=1。
  先 `re.sub(r"step:(\d+)K\b", ...)` 展开 K 后缀 + `\b` 边界 + 去重保序。
- **checkpoint 垃圾目录**：50 步被中断的训练目录比 1000 步有效训练"新" → rollout glob 最新
  加载垃圾 → 视频不动。清理规则：删 `_150628` 这类 50 步中断目录，保留完整训练目录
  （141535 的 000050 是保存目录名≠50 步，看 pretrained_model 的 mtime 判断训练结束时间）。
- **磁盘清理**：每目录只留最后 checkpoint（`ls checkpoints | sort -n | tail -1`，last 软链重指），
  删旧实验目录（peg_v6/v3/final/metaworld 命名），保留 KEEP_DIRS 清单（GUI/曲线引用的命名目录）。
  outputs/train 67G→4.7G 实测。

## 7. 遗留（未完成）
- ACT rollout 的 env_state 拆分修复后仍有广播错误——需专门调试 ACTPolicy 输入层
  （state 语义：39D 合并 vs robot/env 分离）。视频有运动但动作偏小（0.0~0.3）。
- smolvla/smolvla_lew 曲线补训完成后需修正 step:1K 解析（运行中的脚本用旧正则，
  完成后再手动修 json，同 act 修法）。
