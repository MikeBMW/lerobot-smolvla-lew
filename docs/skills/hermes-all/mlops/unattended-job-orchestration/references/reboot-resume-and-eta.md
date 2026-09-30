# 关机/重启后恢复长跑任务 + 实测 ETA (2026-09-13 实例)

场景: 12 epoch INTACT 微调 (接力守护 `train_intact_optical_chain.sh`) 跑到 Epoch 0 时,
用户"可以关机了么" → 干净关机 21:26 → 21:49 开机。新会话进来时只看到"进程没了"。

## 1) 取证: 先判"关机"还是"崩溃"

```bash
date; who -b; last -x reboot | head -5; uptime
journalctl -b -1 -n 5 --no-pager
ps -eo pid,etime,cmd --sort=-pcpu | head -20
nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader
df -h /
```

实测输出 (决定性证据):
```
         system boot  2026-09-13 21:49
reboot   system boot  6.17.0-14-generi Sun Sep 13 21:49   still running
reboot   system boot  6.17.0-14-generi Sun Sep 13 07:42 - 21:26  (13:43)
Sep 13 21:26:04 ubuntu systemd[1]: Reached target poweroff.target - System Power Off.
```
→ 21:26 干净关机, 21:49 开机, 中间 23 分钟机器根本没上电。不是崩溃, 不用查 traceback。

⚠️ **`ps -o etime` 单位坑**: `01:13` = 1 分 13 秒 (`[[dd-]hh:]mm:ss`)。
我第一轮把它读成 73 分钟并推出"机器跑了 1 小时多"的结论 —— 与 `uptime: up 1 min` 直接矛盾。
**任何 etime 推理都要用 `uptime`/`who -b` 交叉验证**。

旁证 (确认"训练是被关机打断, 不是自己跑完"): 训练日志停在 Epoch 0 中途;
`checkpoints/intact_goal_optical_insert_v5_s3072/` 只有 metadata, `weights_epoch_*.pt` = 0 个。

## 2) 恢复: 复用项目自带入口, 并自证"它没跑过"

项目已备好两层恢复:
- `l4_ab/resume_after_reboot.sh` — 一条命令拉回 ① 微调接力 ② 控制台 GUI
- `l4_ab/train_intact_optical_chain.sh` — 接力守护 (`TARGET/PER_RUN/CFG/FAMILY_V/DEADLINE`),
  被 `timeout` 硬杀后自动从**最新** `weights_epoch_*.pt` 续训 (`init_strict=true`),
  无 ckpt 则按配置初始化; 每轮换 `output_model_name` 避免覆盖历史 ckpt。

**自证没跑过**: 包装/恢复脚本都用 `>> log` 追加, 一启动就 bump mtime。
`logs/chain_v5_outer.log` mtime 还停在 21:19 (关机前) ⇒ 恢复脚本没执行过 ⇒ 可以放心起。

**只起训练那半**: 那时 GUI 已经有一个在跑 (用户自己点开的, `ps -o lstart` 显示 21:50:22),
而 `resume_after_reboot.sh` 是无条件 `nohup studio.py &` —— 整套跑会起出第二个控制台。
于是新建 `l4_ab/start_v5_chain_only.sh` (见下), 前台调用, 秒退:

```bash
#!/usr/bin/env bash            # 只起 v5 微调接力守护 (不碰已在跑的 GUI)
set -uo pipefail
cd /home/ubuntu/l4_ab
mkdir -p logs
CFG=intact_goal_optical_insert_v5 FAMILY_V=intact_goal_optical_insert_v5 TARGET=12 \
  setsid nohup bash /home/ubuntu/l4_ab/train_intact_optical_chain.sh >> logs/chain_v5_outer.log 2>&1 < /dev/null &
disown || true
exit 0
```

为什么要包装: harness **拒绝**前台命令里带 `&`
(`Foreground command uses '&' backgrounding. Re-send WITHOUT the '&' ...`),
而 `terminal(background=true)` 起的东西会话结束就没了 —— 多小时训练要真脱离, 只能让脚本自己去 setsid。

恢复后复核 (三个都要看):
```
6127  bash train_intact_optical_chain.sh                      # 守护在
6156  timeout 14400 ./.venv/bin/python train.py --config-name=intact_goal_optical_insert_v5
GPU: 100 %, 5773 MiB                                          # 真吃上卡
[Epoch 0/12] step 50/5815 (2.1 it/s)                          # 有新进度行
```

## 3) 实测 ETA (别抄 tqdm 的 it/s)

tqdm 那行 `2.1 it/s` 是滑窗瞬时值, 要自己测 Δ步/Δ秒:

```bash
s0=$(tr '\r' '\n' < $LOG | grep -E "^\[Epoch" | tail -1); t0=$(date +%s)
sleep 240
s1=$(tr '\r' '\n' < $LOG | grep -E "^\[Epoch" | tail -1); echo "$s0 @$t0 → $s1 @$(date +%s)"
```
实测: step 100 → 600, 窗口 240s ⇒ **2.08 步/s** ⇒ 5815 步/epoch ≈ **46.6 分钟/epoch**
⇒ 12 epoch ≈ 9.3 小时 ⇒ 21:51 起训 → 次日 **~07:10** 完成。

里程碑式回报 (用户问"还得多少时间"就这么给):
| 里程碑 | 时间 |
|---|---|
| epoch1 ckpt 落盘 (第一个可判闸点) | ~22:38 |
| 判闸出数字 (cpu 跑 120 真帧, 15~25 分钟) | ~23:00 |
| 12 epoch 全跑完 | 次日 ~07:10 |
| 判闸过 → 闭环 + 成功插拔视频 | +1 小时 |

并显式给出不确定性: "判闸不过就要改数据/损失再来一轮 = +1 天"。只给乐观数字 = 夸大。

## 4) 判闸哨兵: 一个 epoch 只判一次 (marker-per-artifact)

新 ckpt → 判闸 → 报数, 天然是"变化触发", 不要定时重复判:

```python
ws = glob.glob(os.path.join(CKPT, "weights_epoch_*.pt"))
if not ws: return 0                                  # 还没落 ckpt → 静默
newest = max(ws, key=os.path.getmtime); ep = int(re.search(r"_epoch_(\d+)\.pt$", newest).group(1))
mark = f"{MARK_DIR}/v5_epoch_{ep}.json"
if os.path.exists(mark): return 0                    # 该 epoch 判过 → 静默
if time.time() - os.path.getmtime(newest) < 180: return 0   # 刚落盘, 防读到半个文件
...  # 跑判闸 → 写 mark → 打印简报 (no_agent cron: 有 stdout 才发)
```

两条纪律:
- 判闸**用 `--device cpu`** —— 训练正占着 GPU, 判闸绝不能抢卡 (它本来就慢, 抢了也没有收益)。
- 判闸超时/未产 json **不写 mark** (下轮重试) 并把 stderr 尾部打出来; 写 mark 会让它永久沉默 ——
  "静默" 与 "早失败" 必须能区分。

## 5) 判闸口径与已知塌缩 (v3/v4/v5 同一把尺)

`tools/intact_replay_check_v3.py` (数据集真帧 → 微调权重 → 预测动作 vs 数据集 action 列):

- **过关判据 (必须赢常数基线)**: `model_xyz_mae < const_xyz_mae`
- **塌缩判据**: `预测std / 教师std` (xyz 均值); 实测 v3/v4 = **0.07~0.16** = 塌到均值

| 版本 | epoch | model xyz MAE | 常数基线 | 预测/教师 std | 结论 |
|---|---|---|---|---|---|
| v4 | 1 | 0.0416 | 0.0368 | ~0.10 | ❌ 输给常数 |
| v4 | 2 | 0.0451 | 0.0368 | ~0.09 | ❌ 输给常数 |
| v5 | 1 | 待判 | 0.0368 | 待判 | loss intent 0.1/0.05→1.0/1.0, min_log_std −5→−2 |

结论纪律: 判闸不过 ⇒ 根因是**模型能力** (不是接线), 环`闭环直驱 0%` 与之一致时不要再去改接线;
判闸过了才值得上闭环真物理。
