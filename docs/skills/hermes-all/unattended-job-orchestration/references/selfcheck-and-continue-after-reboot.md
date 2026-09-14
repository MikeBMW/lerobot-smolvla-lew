# 「自检，继续上一个任务」: 关机/重启后接续长跑任务 (2026-09-14 实例)

> 配套 `references/reboot-resume-and-eta.md` (§1–5 讲关机取证 / 恢复入口 / ETA 实测 / 哨兵 marker)。
> 本文是 09-14 那次真实重启的**第二份实例**: 用户只说 6 个字, 全部上下文靠取证重建。

场景: 上一会话以「保存数据 + 小版本迭代 + 准备关机」收口, 留下手递文档 `l4_ab/V6_RESUME.md`;
本机 18:53 重启 (`uptime` 0 min), 新会话零上下文。用户消息 = 「自检，继续上一个任务」。

## 0) 铁律: 上下文来源是文件和会话库, 不是记忆

```bash
session_search()                          # browse → 最近那条 CLI 会话
# 读它的**收口消息**: 里面写了「开机后跑哪条命令」+ 已验证产物清单 + 未做完的事
read_file /home/ubuntu/l4_ab/V6_RESUME.md # 目标任务 / 断点状态 / 一条命令 / 判闸口径 / 遗留
git log --oneline -12                     # 本地提交到哪一版 (本次 v5.5.51, 未推送)
```
**关机前必留手递文档** (目标 / 断点 / 一条命令 / 判闸口径 / 没做完的事) —— 它是跨重启唯一的任务上下文。
没有它, 新会话只能靠猜。用户问"继续上一个任务"而你先反问"哪个任务"= 不合格。

## 1) 自检清单 (顺序固定, 每条都要实得值, 不许推断)

| # | 检查 | 命令 / 判据 | 本次实得 |
|---|---|---|---|
| 1 | 重启还是崩溃 | `uptime -p; who -b; ps -eo pid,etime,cmd` | 0 min / 18:53 → 重启, 不用查 traceback |
| 2 | 断点丢了多少 | `ls <ckpt_dir>/weights_epoch_*.pt \| wc -l` | **0 个** (只有 run_metadata.json + train_config.yaml) ⇒ 丢 Epoch 0 ≈ 47 min 算力; 旧 ckpt 无损 |
| 3 | 环境在位 | `./.venv/bin/python -c "import torch;print(torch.__version__, torch.cuda.is_available())"` | 2.6.0+cu124 True |
| 4 | 数据在位且**同源** | 字节数 + sha256 对数据卡 | 7,369,514,300 B = 数据卡 sha256 ✓; `config/train/data/zmax_v5.yaml` 指向的就是它 |
| 5 | 暖启动源在位 | `init_weights_path` 那个文件真存在 | v5 `weights_epoch_2.pt` 83.9MB ✓ (脚本本身 `[ -f ] \|\| exit 2`) |
| 6 | 新特性代码在位 | `git log -1` | 记忆通道提交 799a9bc ✓ |
| 7 | 哨兵认新目录 | `grep glob ~/.hermes/scripts/<ver>_judge_watch.py` | 通配 `intact_goal_optical_insert_v6*_s3072` ⇒ 换轮次名不用改 cron |
| 8 | GPU / 磁盘 | `nvidia-smi`; `df -h /` | GPU 3 MiB 空载可起; 磁盘 307G/396G **越 300G 红线 7G** → 如实报, 不擅删 |

红线处理纪律: 磁盘越线时先看大占用是谁 —— 本次是 cube 95G + reacher 93G (官方数据集, 用户要求留的),
没有"明显垃圾"可补 ⇒ 报数字 + 给 A/B/C 选项, **不擅自删** (删大文件前必须验证依赖, 曾误删唯一源)。

## 2) 续训脚本的「轮次名 bump」要预期到 (不是 bug)

`l4_ab/v6_resume.sh` 逻辑: 有 v6 权重 → 最新 epoch 续 (`init_zero_skill_branch=false`, 保住已学通道);
无权重 → 从 v5 ep2 暖启动 (`=true`, 数学上等价老模型); 且 `while [ -d "$NAME" ] && [ -z "$NEWEST_W" ]`
会**跳过已存在的目录名** ⇒ 本次输出落到 `intact_goal_optical_insert_v6r2_s3072`
(v6_s3072 只存 metadata 也占名)。原因: Lightning 的 epoch 计数从 1 重来, 同名续训会覆盖旧 ckpt。
判闸哨兵用通配目录, 所以改名的续训轮次**照样被自动判**, 不用动 cron。

## 3) 零回退 / 新通道自证 (给模型加条件分支后暖启动必看)

「不回退」必须由**日志原文**自证, 不能靠读代码推断:

```bash
grep -nE "skill|zero|init" reports/v6_chain.log | tail
[init] 🧠 skill 分支已零化 (skill_dim=24) → 暖启动 = 老模型逐位等价      ← 关键行, 贴进回报
[init] 未从 ckpt 取得 (将从零训) 共 7: [intent_actor.skill_enc.0.weight, 0.bias, 2.weight, ...]
Cached 'skill_ctx' from optical_insert_v5_disturb.h5                  ← 数据侧通道真被消费
cat <ckpt_dir>/run_metadata.json   →  "skill_dim": 24, "dataset": ..., "objective": ...
```
原理: 新分支末层零初始化 ⇒ 暖启动那一刻 E(s)≡0 ⇒ 与老权重逐位等价;
通道到底有没有用上, 交给判闸数字, 不靠声称 (老倪红线)。

## 4) 起训练后 3 条活证据 (缺一条 = 「说了没做」)

```
nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader   # 56 %, 5973 MiB
pgrep -af "train.py --config-name=intact_goal_optical_insert_v6"           # 真进程 + 新轮次名 v6r2
tail reports/v6_chain.log                                                  # [Epoch 0/12] step 100/5870 (2.1 it/s)
```
落法: `terminal(background=true, notify_on_complete=true)` 适合**本会话内**盯 + 完成时一次通知;
要真脱离会话 (跑 >10h) 仍按 `reboot-resume-and-eta.md` §2 的 `setsid nohup ... < /dev/null &` 包装。

## 5) 回报格式 (用户要「自检 + 继续任务」时)

三段, 每条都带实得值:
1. **自检 N 项** (表格/列表; 含那条红线告警, 如实写)
2. **已继续什么 + 落地证据** (轮次名 · 日志关键行原文 · GPU% · 当前 step/epoch)
3. **后面会自动发生什么** (首个 ckpt 时刻 · ETA · 谁推给谁, 如"判闸哨兵每 20min 发飞书静界群, 这里看不到")
   + 选项 A/B/C (把你建议的默认项放第一个)

ETA 现算 (别抄 tqdm 瞬时值): 5870 步/epoch ÷ 2.1 it/s ≈ 47 min/epoch × 12 = **9.4h**;
18:54 CST 起训 ⇒ 首个 `weights_epoch_1.pt` ~19:41, 12 epoch 跑完次日 ~04:20。
⚠️ **训练日志时间戳可能是 UTC** (本次日志 10:54 vs `date` 18:54 CST) —— 报时间前先对齐时区, 别把 UTC 当本地时间报。

## 6) 顺带报的旁支状态 (用户"继续任务"时也要看)

- 闭环守护 `tools/auto_loop.py` v2 随开机自起并已连 `wss://datadrive.world/ws` → 「队列空, 等小芳采集数据」是**正常待料**, 不是故障。
- cron 哨兵清单 (`cronjob action=list`): 13 个全 ok; 其中判闸类哨兵用 `monitor_script` / marker-per-artifact 天然"变化触发", 静默=无新 ckpt。
- 内存/磁盘/GPU 这些"环境类"结论一律现查 (`uptime`/`nvidia-smi`/`df`), 不用记忆里的旧值。
