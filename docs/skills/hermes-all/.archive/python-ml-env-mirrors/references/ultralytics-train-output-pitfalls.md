# ultralytics 训练输出坑 (2026-08-24 实测)

## 自动递增目录 (静默, 不报错, 最容易踩)

`model.train(project=..., name=...)` 当 `project/name` 目录已存在时, ultralytics **自动把输出写到 `name-2`**(不报错, 不提示), 之后 `name-3`、`name-4`… 递增。

实测案例: 昨天 CPU 训练产出 `outputs/yolo_peg_depth/peg_depth_v1/`, 今天 GPU warm-start 重训同名 → 输出静默落到 `outputs/yolo_peg_depth/peg_depth_v1-2/`。

两个后果, 都咬人:
1. **下游加载到旧权重**: `_DEPTH_WEIGHTS_CANDS = [..., "peg_depth_v1/weights/best.pt"]` 指向旧目录 → 加载昨天 CPU 训的旧 best.pt, 而非今天 GPU 训的新 best.pt。下游候选路径必须把 `name-2` 排最前。
2. **查错 results.csv**: `cat peg_depth_v1/results.csv` 看到的是昨天的旧数据(时间戳/收敛曲线对不上), 一度误判"训练没保存"。今天 GPU 的真实数据在 `peg_depth_v1-2/results.csv`。

判断新产物在哪:
```bash
find outputs/ -name best.pt -newermt "2026-08-24"    # 按今天时间过滤, 直接定位真正的新产物
ls -la --time-style=full-iso outputs/<proj>/<name>-2/weights/   # 时间戳确认
```

## 验证训练真在跑 (老倪工程真实性零容忍, 别只看 is_available)

被追问"是不是真的在训练"时, 用这几条硬证据, 不要空口:
```bash
# 1. 进程树: 主进程 + N 个 dataloader worker 子进程
ps aux | grep train_depth | grep -v grep
# 2. GPU 真实占用 (进程级) + 利用率/温度
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
nvidia-smi --query-gpu=utilization.gpu,memory.used,temperature.gpu --format=csv,noheader
# 3. 收敛曲线: results.csv 每 epoch 一行, abs_rel/rmse/delta1 单调改善 + 偶发波动(真实特征)
tail results.csv
# 4. 权重文件 mtime 和 epoch 进度对应 (best.pt 在 val 改善时更新, last.pt 每 epoch 更新)
ls -la --time-style=full-iso <name>/weights/
```

## CPU→GPU 迁移 (同 SKILL.md 已有: resume 空 GradScaler)

CPU 训的 ultralytics checkpoint 不能 `resume=True` 迁 GPU(空 GradScaler → `RuntimeError: source state dict is empty`)。要 `YOLO(last.pt)` 作 warm-start 权重 + 正常 `model.train(device=0, ...)`, 且 resume 分支要显式传 device/epochs, 否则从 last.pt 恢复成 CPU。
