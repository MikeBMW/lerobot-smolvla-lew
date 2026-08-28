# 2026-08-08 远程训练执行模式 (V100 服务器计时 — 快)

## 训练命令参数
- `--config_path`(**下划线**) — `--config-path`(短横线) → `unrecognized arguments`。本地 GUI 与远程 venv/容器统一用下划线。
- 数据 root 统一: 每个 config 先 `sed -i "s|^  root: .*|  root: data/metaworld_peg_grab6|"` (远程只有 metaworld_peg / metaworld_peg_grab6)。

## 输出实时性 (老倪: "要详细的终端打印, 我在监控")
1. python 非 tty → 块缓冲(4K 攒批) → 训练命令加 `-u` (stdout/stderr 无缓冲)
2. tqdm 用 `\r` 刷新不换行 → `for line in p.stdout` 卡住 → Popen 改 bytes 块读 `read(4096)` 按 `\r`/`\n` 分行, 每行 emit; 截断放宽到 600 不简化
3. 队列轮询防误判: on_train 数据准备有延迟, 轮询 pgrep 会误判"完成"秒推进下一个 → 记录启动时间戳, 45s 窗口内不判完成; 进程存在则重置窗口

## ssh 后台长任务
- `setsid bash x.sh > /dev/null 2>&1 < /dev/null & disown` — nohup/普通 & 在 ssh 断开后被清
- 验证: `pgrep -f 'script名'`; log 用 `>>` 追加带时间戳标记
- 训练串行脚本模式: for 循环 run_one(name, config) — sed root → timeout 7200 python -u -m lerobot.scripts.lerobot_train --config_path → 结束 rc 标记; 每个 config 缺则跳过

## venv 补包 (--no-deps 装 lerobot 的后果)
远程 venv 反复缺: accelerate/tensorboard/transformers/datasets/av — 报错就 `pip install X` (去掉 -q, 静默会假失败); transformers 版本大战见 zmax-console references/20260808-container-framework-threadsafe.md — 最终锁定 **4.44.2** (5.5.4 缺 torch import、4.49/4.51 缺 Qwen2_5_VLTextConfig)

## 监控 cron (no_agent)
`zoo_monitor.sh`: 进程优先判断 — 容器/venv 训练中 → 输出进度%; 无进程查 ALL_DONE; 否则报无训练。cron 每 20min deliver 飞书 dataworld。教训: 先 grep 进程再 grep ALL_DONE, 否则旧 log 的 ALL_DONE 误报完成。
