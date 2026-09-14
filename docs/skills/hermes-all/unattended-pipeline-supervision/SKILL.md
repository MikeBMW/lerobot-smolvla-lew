---
name: unattended-pipeline-supervision
description: "Use when 无人值守长流水线(下载/校验/解压/训练/评测)需终态上报 — 静默哨兵+沙箱验两分支."
trigger: "Use when a multi-hour pipeline (下载→双核校验→解压→训练/评测→汇总) runs in the background while the user is away, and the terminal state (全部完成 / 失败) must push exactly one message; also when the same machine has another long job competing for GPU/带宽/磁盘写者."
---

# 无人值守长流水线监督 (静默哨兵 watchdog)

## When to Use

- 一个跑到凌晨的流水线 (下载 46GB → sha256 → 解压 → 3 seed 评测 → 汇总表) 必须**终态精确推一次**, 中间不打扰。
- 用户在别的会话/手机上等结果; 他只会问「跑完了吗」, 你要么已推过、要么正在静默等待, 不能"其实早挂了"。
- 同机还有长任务 (训练) 抢资源 —— 流水线要自己让路或自证没抢。

## 先说三条决定性事实

1. **CLI 会话里建的 cron, 输出不会回到终端**。`deliver` 必须是 gateway 平台 (`feishu:<chat_id>` / `all`), 否则用户永远收不到。**别承诺"到点我告诉你"** —— 要么显式指定飞书, 要么当面说清"这个只落盘"。
2. `no_agent=True` + 脚本 stdout 语义: **有内容才发消息, 空 stdout = 静默**。这就是免费的去噪机制, 不要用 LLM 轮次去"判断要不要报"。
3. cron 每 tick 都是**全新进程** → 状态只能落文件 (flag/state), 不能靠内存/变量。

## 设计模板 (三态 + 一次性 flag)

state 目录里三个东西:
- `.reported` — 成功已报 → 存在即 `exit 0` (永久静默, 防同一张表反复推)
- `.failed_reported` — 失败已报 (一次性, 防止"跑了但静默丢失")
- `.evidence` — 只落盘不打扰的取证 (例: 评测进程出现那一刻的 `nvidia-smi` 原始行)

脚本骨架 (顺序就是优先级):
```
① 已报 → exit 0
② 采集取证 (只落盘, 不发消息)
③ 完成判据成立 (全部产物齐) → 重新生成报告 → 打印全文 → touch .reported → exit 0
④ 死亡判据成立 (pgrep 流水线为空 且 产物缺) → 打印缺失清单 + 日志尾 → touch .failed_reported
⑤ 其余 → exit 0 (静默)
```
完成判据要**按产物数**算 (N 任务 × M seed 的产物文件全在), 不要按"日志里有 SUCCESS 字样"。

## 必做验证: 沙箱跑两个分支 (不跑等于没写)

watchdog 最坏的失败模式是"永远静默" —— 看起来一切正常, 其实从没接线。写完必须把**硬编码路径 sed 改写到 /tmp 沙箱**, 两个分支都真跑一遍:

```bash
mkdir -p /tmp/wt/results && cp <真产物> /tmp/wt/results/...       # 造"齐"
sed -e 's#^OUT=.*#OUT=/tmp/wt/results#' -e 's#^LOG=.*#LOG=/tmp/wt/x.log#' \
    -e 's#^OK_FLAG=.*#OK_FLAG=/tmp/wt/.ok#' -e 's#^FAIL_FLAG=.*#FAIL_FLAG=/tmp/wt/.fail#' \
    "$SCRIPT" > /tmp/wt/w.sh
bash /tmp/wt/w.sh                    # 必须打出完整报告
out=$(bash /tmp/wt/w.sh); echo ${#out}   # 必须 0 —— 只发一次
bash "$SCRIPT"                       # 真实目录干跑: 必须静默
```

验收清单 (逐条对):
- [ ] 完成分支输出**全文** (表/证据/产物路径), 不是只有标题
- [ ] 第二遍输出长度 **0** (一次性生效)
- [ ] 缺产物且流水线已死 → 报缺失 + 日志尾 (不是沉默)
- [ ] 真实目录干跑静默 (当前确实未完成时)
- [ ] 交付目标 = 用户真正会看的那个平台

## 生成式报告纪律 (红线: 报告里不许有会变假的句子)

- **绝不写死缺口说明**。曾写死 `**未做的**: cube 因磁盘闸门未评测` —— cube 一补测, 这句就成假话 (老倪零容忍)。缺口**从产物动态算**:
  ```python
  missing = [t for t in TASKS if not results.get(t)]
  note = f"**未做的**: {' / '.join(missing)} 未评测 (诚实记录)" if missing \
         else "**覆盖**: 全部任务 × 全部 seed 均为本机实测, 无缺口"
  ```
- **每次重新生成再发送**, 不要推缓存的旧表。
- **取证与结论同帧**: 回答"评测有没有抢显存"→ 在评测进程出现的那一刻记一次 `nvidia-smi`, 把原始行贴进最终消息; 不要用形容词替代数据。
- 失败也要报: 宁可推一条"死了 + 原因", 不要静默。

## 变体: 「早收」型哨兵 (判/停分离, 2026-09-14 v6 实测)

长训练不必等跑满: 每轮判闸 (如 INTACT 的 skill=on/zero 同权重同帧消融) 一过闸就停训出结果,
省掉后面所有无效轮 (实测 v5 越训越塌: MAE 0.0435→0.0424→0.0560)。三条设计纪律:

1. **判与停分成两个脚本/两道闸** —— `judge_watch.py`(只出数字, 落 `judged/<fam>_epoch_N.json`) +
   `earlystop_watch.py`(只读那些 json, 三连全过才动手)。别把"判"和"杀"混一个脚本里, 否则审计不了。
2. **只认属于当前 family 的判闸结果**: 续训会换轮次名 (v6 → v6r2), 旧 family 的标记必须作废 ——
   判据 = `json["ckpt"]` 里含有当前 family 目录名。
3. **动手前先防抖**: 判闸 json 是 `json.dump` 非原子写 → 残文件 `json.load` 会抛异常被跳过,
   所以防抖窗口只要 ~180s 覆盖"写完到可读"即可 (一开始写 600s 纯属白等 10 分钟)。

状态仍是三件套: `.stopped`(已停训) / `.reported`(结论已推, 一次性) / `events.jsonl`(取证台账)。
停止动作: 按 `pgrep -f <精确 cmdline>` 取 pid → SIGTERM → 等 ≤90s → SIGKILL → **复核确实退出**;
匹配模式走 env (`ZMAX_ES_PATTERN`) 才好在沙箱里换成假目标。**绝不裸 `pkill -f`** (会杀到自己)。

沙箱验"能停"分支的正确姿势 (假目标进程): 用 `subprocess.Popen(["sleep","987"])` 起一个真进程,
把 `ZMAX_ES_PATTERN="sleep 987"` + 三个路径 env 指到 `/tmp/es`, 造一份"过闸"标记 json, 跑哨兵 ——
它必须真把那个 sleep 杀掉、打出全文、写 `.stopped/.reported`, 第二遍静默。回归测试落档:
`/home/ubuntu/l4_ab/tests/v6_earlystop_sandbox_test.py`。

## 坑 (实测)

| 坑 | 症状 | 修法 |
|---|---|---|
| **系统时钟被 NTP 往回拨** (双系统 RTC 偏/开机后首次同步) | ① 报给用户的绝对时间整体错一截 (2026-09-14 实测: 会话开头读到 18:54, 真实是 10:54, NTP 在开机后 ~1 分钟把钟拨回 7.5h) ② **所有"每 N 分钟"的 cron 静默罢工**: `next_run_at` 是用旧钟算的 (18:54+N), 拨正后它落在将来 7.5h, 于是整天不触发 (v6 判闸哨兵差点被拖到当晚) | ① 报时间前先 `timedatectl` + `journalctl \| grep -i "time jump"` 核对, 再用**与钟无关的交叉验证** (训练步数 × 实测秒/步 = 真实跑了多久) ② 发现跳变立即把每个 job `cronjob(action='update', schedule=<原样>)` 重算一遍 `next_run_at` (会从"现在"重新起算), 然后 list 复核所有 next_run_at 都在合理未来 |
| **僵尸进程占着 `/proc/<pid>`** | SIGTERM/SIGKILL 都发了, 复核却报"仍存活" → 误报"停训失败", 且每 tick 重复报、永不收敛 | 存活判据不能只看 `/proc/<pid>` 是否存在: 读 `/proc/<pid>/stat`, 取最后一个 `)` 之后第一个字符, `Z` = 僵尸 = **已死** (`s[s.rindex(")")+2] != "Z"`) |
| 改一个**正在运行**的 bash 脚本 | 解释器按字节偏移增量读脚本 → 可能执行到错乱的行 (污染/中断) | 先 `pgrep -af <script>` 确认没在跑才改; 正在跑就**别改**, 另起独立 watcher/闸, 或等它结束再改 |
| 静默 = 无事, 无法区分 | "没到点" 与 "脚本早挂了" 看起来一样 | (a) 每个静默分支显式 `exit 0` 并在 `--debug` 模式落一行日志; (b) 依赖一个**独立**心跳 (sys-watchdog 类) 覆盖 cron 本身是否在跑 |
| `deliver='origin'` (CLI) | 用户什么都没收到 | 显式 `deliver='feishu:<chat_id>'` 或 `'all'` |
| 每 tick 都推 | 刷屏 → 消息被无视 | 一次性 flag; 需要中间进度就用 `monitor_script` **变化触发**, 不要定时重复推 |
| 闸门资源 (磁盘/GPU) | 流水线与同机训练互相打死 (OOM / 写坏分片) | 起跑前查 `nvidia-smi` / `df`; 不足就等 (轮询 sleep + 日志留"等待中"记录); 共享目录**单写者纪律** |
| 结果文件名逐任务不同 | 成功的评测被误判"未产出" | 从各任务 config 的 `output.filename` 取名, 不要猜 `<task>_results.txt` |
| 大文件多连接下载的"大小" | 未下完但 `ls` 已显示全尺寸 (稀疏/预分配) | 完成判据 = aria2 退出码 + size + **SHA256** 双核, 不能只看大小 |

## 相关

- 磁盘闸门/红线回收: `disk-redline-guard`
- 数据集/权重下载与 h5 真解码校验: `hf-dataset-subset` (+ `scripts/verify_h5_dataset.py`)
- 评估结果口径与不回退红线: `cross-venv-model-canvas-node` §8-9
