# 2026-08-08 视频白屏根治 + expert_mlp 加载链 + 指令最小化 (老倪连续纠正 4 次)

## 视频白屏根治 (simulink_scope.py InferenceVideoDialog) — 老倪"这个问题出了好几次"
- **根因**: 打开对话框 → `_check_newer_ckpt()` 检测到任一模型 train_curve ts/ckpt 比视频帧新
  (如 act 曲线 ckpt 刚指向新训练目录) → **自动 `QTimer.singleShot(300, self._run_rollouts)` 重生成** → 白屏等 1-2 分钟
- **修复原则 (根治, 不再反复)**:
  - `if self.frame_dirs:` 分支 **永远先 `self._play()` 播放历史视频** (不管 ckpt 新不新)
  - 检测到新 ckpt → 只 `lbl_note` 提示「🔄 检测到新训练 checkpoint · 已显示历史视频 · 点重新生成更新」
  - 重生成改**手动按钮** (「🔄 重新生成推理」)
  - 仅**完全无帧** (`else:` 分支) 才自动生成
- 配套: `_tick` 只播放循环 (cur_idx 越界归 0), 无自动重生成; 对话框未显示时 lab.size()=0 → scaled(0,0) 白屏 → 尺寸有效才缩放
- **用户偏好**: 历史视频是资产, 打开必须先显示, 绝不能因新训练而白屏等待

## expert_mlp (MLP 蒸馏) 加载/推理链 — 3 个坑
`outputs/rl_peg/expert_mlp.pt` 是 torch.save({"model": state_dict, "obs_dim": 39, "act_dim": 4}) 单文件:
1. **load_policy (rollout_video.py)**: 曲线 ckpt 指向 `.pt` **文件非目录** → isdir False → 兜底 glob 失败 → FileNotFoundError。
   修: `if policy == "expert_mlp" and os.path.isfile(base_dir):` 特判 — importlib 加载 distill_expert.py → ExpertMLP(obs_dim, act_dim) → load_state_dict(data["model"])。
   **必须设 `pol.state_dim = pol.obs_dim`** — 否则 run_rollout 的 st_dim 推断 `getattr(policy, "state_dim", 2)` = 2 → 输入 2D vs 权重 39x512 → `mat1 and mat2 shapes cannot be multiplied` → 动作 0.0
2. **推理分支**: ExpertMLP 无 `select_action`/`_cond` → 落 else (awe 4 参数 forward) 报错 → 动作 0。
   修: `elif hasattr(policy, "obs_dim") and not hasattr(policy, "model"): pred = policy(batch["observation.state"])` (39D 直出动作) — **rollout_video.py 和 rollout_peg_check.py 两处都要加**
3. **--policy choices**: argparse choices 须含 expert_mlp/expert_policy (原只 5 模型)

## MLP 蒸馏 > ACT 长训 (插销插入)
- ACT 插销数据 4000 步: loss 64→0.585 收敛, 但 rollout 0/5 (销钉没抬起 — 动作链没学会)
- **MLP 蒸馏 (distill_expert.py, 专家 300 eps 采样 + 15 epochs, loss 0.507): 插入 2/5 (40%), 最小孔距 0.011m** — 5/5 全抬起
- 教训: 长程精确操作 (插销) 数据不足时, **从专家策略蒸馏小模型 (纯 state→action) 立竿见影**, 远胜长训大模型
- 曲线更新: act 曲线 ts/ckpt 指向新训练目录后, Scope 显示新 loss; 解析日志正则先展开 `step:1K`

## 数据闭环控制台模型选择器 (PipelinePanel)
- 需求 (老倪): 看到**所有已训练模型** + 属性 (名字/训练时间) → 选一个 (如 AWE) → Sim-to-Real → Stage 3
- 实现: `_reload_models()` 读 `reports/train_curve_*.json` (7+ 模型, ts→MM-DD HH:MM) 填 QComboBox;
  `_show_model_attr()` 显示 ckpt/训练时间/步数/尾 loss; `_on_sim2real`/`_on_stage3` 写 `docs/PIPELINE_STATE.json` stages[2]/[3] + 日志
- 默认选中 AWE (index 2); 属性行格式: `属性: ckpt=... · 训练 MM-DD HH:MM · N 步 · 尾loss X.XXX`

## 训练状态监视 — 老倪"训练中，终端得看到训练状态" (simulink_module.py)
- **根因**: `_start_ext_log_watch` 只监视固定文件 (`/home/xspace/zmax_train4.log` / `zmax_deliver_latest.log`) —
  **外部/飞书端/其他会话启动的训练** (如 smolvla_peg_long2, config_smolvla_peg_long2.yaml) 输出不在这些文件 → GUI 日志框看不到
- **修**: `_poll_ext_log` 末尾挂 `_poll_train_state()` (每 2s):
  `pgrep -f lerobot_train` → 最新 `outputs/train/*/checkpoints` (mtime) → 数字目录最大步数 →
  `_safe_log(f"⚙ 训练中: {name} · {mx} 步")` — **去重** (`_last_train_state` 变化才刷, 开始/结束各提示一次, 结束打 `✅ 训练完成`)
- 教训: 环境共享时 (飞书端/另一会话/自动流程都在起训练), GUI 状态监视必须**动态检测进程**,
  不能只 tail 固定日志文件; 训练目录名/配置来自 `/proc/<pid>/cmdline` 的 `config_*.yaml` 可溯源

## 指令最小化 — 老倪连续纠正 4 次 (最重要的工作方式教训)
- "YOLO 3D, 删掉检测" → 我理解成删 YOLO 功能/画布节点 → 又删背景行大字 → 老倪: "背景字删掉" → "**就是删掉 检测两个字**" → "**别删多了**" → "你干啥呢"
- **教训**: 老倪的删除指令是**字面最小化的** — 删"检测"两字 = 只改字符串, 不是删功能/节点/背景;
  先 grep 确认目标范围再动, 改完小验证; 拿不准时用最小改动 (rename 而非 delete)
- 关联记忆: "指令最小化(删X=先改名非删功能; 删检测=YOLO 3D改名)"

## 其他
- 数据集清理: 飞书端/其他会话发起的训练产物 (act_peg_long/act_peg_far 各 25 ckpt) 也按磁盘铁律
  **每目录只留最后 ckpt** (004000 + last) → 58G→33G; 别假设只清理本会话产物
- 训练对账: 飞书端消息说"训练 smolvla" 可能过时 — 本地查 `ps aux | grep lerobot_train` + GPU + 曲线 ts 对账,
  不一致时发飞书消息澄清 (dataworld 群 chat_id 见记忆)
- 验证脚本跑 torch 依赖代码必须用 `.venv/bin/python` (系统 python3 无 torch/pandas); 断言别用宽松切片 (含 else 分支误报)
