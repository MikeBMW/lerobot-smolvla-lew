# 训练队列 / 日志实时 / 远程自主训练 (2026-08-08 老倪会话)

## 1. Model Zoo 训练队列 (studio.py TrainingModule)

- 训练按钮 → `_start_training` → `_simulink.on_train(policy=...)` (双向注入: 主窗口 `simulink.set_model_engine(engine)` + `model_engine.set_simulink(simulink)`)
- 7 模型串行: `ZOO_POLICIES = ["act","smolvla","smolvla_lew","vla_touch","awe_zflow","expert_mlp","expert_policy"]`
- `_zoo_next()` 推进 + 15s QTimer 轮询

### 🐛 45s 防误判 (血的教训)
on_train 启动训练有**数据准备延迟** (tmp_cfg 生成/数据检查) — 训练进程还没起时 pgrep 查不到 → **误判"完成" → 秒推进下一个模型** (14 秒"训完"一个 4000 步模型 = 假象, 老倪当场识破"怎么这么快?真的么?")。
修复: `_zoo_start_ts` 记录启动时间 — 启动后 **45s 内不判完成**; 训练进程存在时重置窗口。

## 2. 训练输出实时性 (simulink_module.py)

三层问题, 逐层修:
1. **python 非 tty 块缓冲** — Popen pipe 下 stdout 攒 4K 才输出 → 训练命令加 `-u` (无缓冲)
2. **tqdm `\r` 不换行** — `for line in p.stdout` 等 `\n` 永远等不到 → 卡死无输出 → `_run_cmd` 重写: **块读 (read 4096) + 按 `\r`/`\n` 分行**
3. **截断 200 太简化** — 老倪"终端信息要详细, 不要简化" → 截断放宽 600

### 用户偏好 (老倪)
- "终端信息要详细, 不要简化" — 数据加载/模型加载/每步 loss/进度条全部实时完整输出
- "你要操作窗口按钮, 不能只在后台执行" — xdotool 模拟点击 (WSLg: `DISPLAY=:0 xdotool search/getwindowname/mousemove click`)
- "自主完成训练, 不用请示" — 训练按钮 → 队列全自动, 失败重试

## 3. 远程自主训练 (GPU 服务器计时场景)

- **venv 3.12 快路径 > docker 3.10 镜像**: docker 镜像 PEP695 修到吐, venv (deadsnakes 3.12 + torch 2.3.0+cu118) 一次到位
- 远程串行脚本模式: `for POL in act smolvla smolvla_lew awe_zflow expert_mlp; do ... lerobot_train --config_path CFG; done` + 每模型 `sed -i "s|^  root: .*|  root: data/metaworld_peg_grab6|"` (数据 root 统一)
- **vla_touch 无 config** (on_train 分支 cfg_path=None, 跳过); **awe_zflow 用独立脚本** tools/train_awe_zflow.py; expert_policy 是基准不训
- cron 监控: `zoo_monitor.sh` 每 20 分钟 → 飞书 dataworld (deliver='feishu:oc_c0b4048546145c5c581ddd1a9e8f565d')
  - 🐛 **进程优先判断**: 先 pgrep 训练进程 → 有=训练中; 无 → 查 ALL_DONE (log 追加模式下旧 ALL_DONE 会误匹配, 必须进程优先或 tail 查)

## 4. lerobot_train 参数

- 参数是 **`--config_path` (下划线)** — 不是 `--config-path` (短横线 unrecognized)
- 本地 GUI 一直用 `--config_path` (training_backend), 远程提交手写 `--config-path` 才崩
- 完整命令: `python -u -m lerobot.scripts.lerobot_train --config_path config_xxx.yaml`

## 5. GUI 多实例

- gateway 守护会自动拉起 studio (kill 后 8s 复活) — 手动 run_studio.sh + 守护 = 双实例 (2 进程 1 窗口或 2 窗口)
- 老倪看到"好几个控制台" = 双实例 + 多个 rollout 对比弹窗 (评估窗口多开)
- 清理: 杀 1 个进程 (保留 1); rollout 弹窗 `xdotool windowkill <wid>` 循环关
