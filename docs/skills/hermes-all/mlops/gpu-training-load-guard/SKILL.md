---
name: gpu-training-load-guard
description: Use when 训练 GPU 负载偏低/掉载/要求负载≥50%。
version: 1.0.0
author: Hermes
license: MIT
metadata:
  hermes:
    tags: [gpu, training, utilization, dataloader, profiling]
---

# GPU 训练负载守护（"负载不能小于一半"怎么做到）

## 何时用
- 用户要求「GPU 训练负载不能小于 50%」「GPU 不许空转」
- 训练在跑但利用率忽高忽低 / 掉到 0%
- 要给出"负载达标"的**可信证据**（不是瞬时采样）

## 铁律：用**窗口平均 + 低于阈值的次数**说话，不用瞬时采样
```bash
# 每秒采样 30~45 次, 再统计（瞬时采样会误报 0%）
S=""; for i in $(seq 1 30); do
  U=$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits); S="$S $U"; sleep 1; done
python3 -c "
v=[int(x) for x in '''$S'''.split()]; vs=sorted(v); n=len(v)
b=sum(1 for x in v if x<50)
print('平均 %.1f%% | 中位 %d%% | 最低 %d%% | 低于50%%: %d/%d (%.0f%%)'
      % (sum(v)/n, vs[n//2], vs[0], b, n, 100.0*b/n))
print('低于阈值样本:', [x for x in v if x<50])"
```
**只看平均值会被骗**：实测过"平均 70.7% 但 27% 采样低于 50%、6 次直接 0%"→ 不达标。

## 诊断顺序（按"最可能→最不可能"）
```bash
nvidia-smi --query-gpu=utilization.gpu,memory.used,power.draw --format=csv,noheader   # 同步看显存/功耗
```
| 现象 | 根因 | 处置 |
|---|---|---|
| **停顿周期性 = 每个 step 一次**，功耗仍 20-50W | 每步 CPU 开销 > GPU 计算 | 见下"降 CPU 开销" |
| 显存贴近上限(>90%) | 分配器抖动 | 降 batch / `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` |
| 检查点写入时掉载 | 落盘阻塞 | 拉长 save_freq / 异步写 |
| 数据 worker CPU 很低 | 数据在**主进程**预处理 | 把 transform 放 workers |
| 系统内存 0 free / swap 高 | 内存压力 | 释放其它进程；**别从带内存 scope 的工具调用里长期训练** |

## 降每步 CPU 开销（最有效，且不增显存）
1. **静音逐步日志**（本项目实测：每步打印 `[SmolVLALew] Forward pass: ...` 属 CPU/IO 开销）
   ```python
   if os.environ.get("ZMAX_VERBOSE_STEP"):   # 包住 logger.info(...)
       logger.info(...)
   ```
   ⚠️ **改前先 `grep -n` 定位到唯一文件**：同名日志出现在多个文件时，`grep -rl | head -1` 会改错文件（我踩过，误改了 `rewards/classifier/modeling_classifier.py`）→ 必须 `grep -n '关键词' <目标文件>` 确认行号再改，改完 `git diff` 核验。
2. **数据加载并行度**：`num_workers` 4 → min(16, CPU核数/2)、`prefetch_factor` 4 → 8
3. `OMP_NUM_THREADS` 设 CPU 物理核数的一半，避免线程抢占

## 配置字段的合法边界（LeRobot / draccus）
- `pin_memory` **不是** `TrainPipelineConfig` 的合法顶层字段 → 加了会 `DecodingError: The fields 'pin_memory' are not valid`
- 改配置后**必须先跑一次**确认能被解析（否则训练静默不启动，看起来像"GPU 掉载"，实际是没跑）
- **判定"没跑"的方法**：日志无 `Training: N/M` 进度 + `nvidia-smi` 无该 PID + 显存回落到基线

## 守护进程（持续取证）
`tools/gpu_load_guard.py`：每 N 秒采样 → 写 JSONL；训练中连续 K 次 <阈值 → 打告警；`--report` 出统计。
```bash
python3 tools/gpu_load_guard.py --interval 5      # 常驻
python3 tools/gpu_load_guard.py --report          # 出"训练期间低于阈值次数"结论
```

## 坑
- **GPU 空转是常态**：训练一结束就 0%。要求"不许空转/≥50%"时，必须**保持作业队列连续**，不是跑完就等
- `nvidia-smi` 的 `utilization.gpu` 是**瞬时**值，别用它单点下结论
- 训练期间**同刻只跑一个模型进程**（8GB 卡），否则显存互挤 → 双掉载
- 从**工具调用**里 `setsid` 起的训练会继承调用方 cgroup；查 `cat /proc/<pid>/cgroup` + `memory.max` 确认没被限
