# lerobot_train resume 续训坑 (2026-09-09, smolvla_lew 3000→10000 实测)

老倪"模型继续训练 N 步": 只改 yaml steps 不够, lerobot resume 机制三个坑:

1. **config_path 必须指向 checkpoint 的 train_config.json**
   `--config_path outputs/train/<run>/checkpoints/<step>/pretrained_model/train_config.json`
   (不是训练 yaml!)。resume 分支在 cfg.validate() 里读 config_path → Path(config_path).parent
   当 policy_dir → 找同目录权重。传 yaml 会报
   `ValueError: A config_path is expected when resuming a run. Please specify path to train_config.json`
   (或 FileExistsError output_dir 已存在 + resume is False)。

2. **train_config.json 里 resume 改 true + steps 改目标值**
   训练时存档的 train_config.json `resume:false` → 必须 `json.load` → `d['resume']=True;
   d['steps']=10000` → 写回, 否则 validate() 走 output_dir 已存在分支报 FileExistsError。

3. **命令行必须 `--config_path=<路径>` (=号分隔)**
   `parser.parse_arg("config_path")` 只认 `--config_path=` 前缀 (空格分隔不识别) →
   返回 None → 同 #1 的 ValueError。这是最容易漏的: 空格写法训练能跑 (draccus 吃) 但
   resume 的 validate() 二次解析找不到。

**resume 成功标志**: tqdm 从剩余步数起 (7000 = 10000-3000) + 日志出现 `step:3K` 续点行
+ loss 从续点继续降 + GPU 显存占用回升。若进度从 0/10000 起 = 当新训练跑了 (resume 没生效,
output_dir 会被 FileExistsError 挡或覆盖风险)。

**⚠️ 与磁盘红线守护的交互**: 红线脚本 (disk_redline.sh) 每 2h 删中间 checkpoint 只留 last —
训练进行中删已完成 ckpt 不影响当前 run (resume 用 last/), 但会丢回退点。大训练启动前确认
红线脚本没刚跑过; resume 指向的 ckpt 若被删 → 需退到 last/ 或上一个现存 ckpt。
