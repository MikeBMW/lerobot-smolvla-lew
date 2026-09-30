---
name: unattended-job-orchestration
description: "Use when 长跑多阶段任务(下载/解压/训练/评测)要无人值守出结果 — 接力脚本 + 哨兵 cron 只报一次。"
trigger: "Use when a job outlives the session: multi-stage pipelines (download → verify → extract → train/eval → report) that run for hours, where the user wants the result delivered without babysitting, when two heavy jobs must not compete for the same bandwidth/GPU/disk, or when the user pings '静静'/催进度 and you must answer with live evidence + options."
---

## 投递纪律: 哨兵正常时必须**真静默**, "无变化"也是刷屏 (2026-09-27 老倪: 「没请求的时候不要总发…不要刷屏」)

把 cron 哨兵投到群里时, 群是**给人看结论的地方, 不是日志流**。踩过的坑(都很安静, 不看输出看不出来):
1. **脚本哨兵无条件打状态行** —— `echo "✅ 链路正常: …"` / `echo "📊 used 82G / 红线 300G"` 每轮都发, 一天 48+12 条纯噪声。
   口径: **没有要人处理的事就一个字节都不打**(stdout 空 → cron 不发); 只报 FAIL/超红线/真删了东西。
2. **过程提示当成结果报** —— "🔒 保护/⏸ 跳过/🏃 在跑" 这类中间过程, 正常跑也刷一屏。口径: 这类只留给人工排查(脚本里加 `DRY=1` 开关, 平时不显示)。
3. **LLM 任务里写"无变化"** —— 提示词写"无变化就回无变化"，结果这四个字每 30 分钟一条发进群。
   口径: ☠️ 只有**字面 `[SILENT]`** 才会抑制投递(不要翻译成中文、不要加任何其它字); 提示词里要**明写**"没有新东西就只回 `[SILENT]`，不要写'无变化'/'暂无'——写任何文字都会被当成消息发出去"。
4. **同一异常重复报** —— 超红线持续时别每轮都喊: 落状态文件, 同一状态 N 小时(如 6h)只报一次, 恢复正常时清状态。
5. 查"到底谁在发": 读 `~/.hermes/cron/output/<job_id>/<时间>.md` 能看到**实际投递出去的内容**(no_agent 任务还会标 `Status: silent (empty output)`) —— 比猜快得多。
6. **没请求就不推送媒体** —— 常驻的"新图就发群" watcher(如 `aoi_feishu_push.py --watch`)默认应当**关掉**, 只在人点/真事件时用 `--once`; 它会静默地每几秒扫一轮, 一旦有新图就发, 从群里看像"没请求也在发图"。

 (接力脚本 + 哨兵 cron)

适用: 一整个流水线比会话活得久 (下载 46GB → 解压 → 3 seed 评测 → 出表), 用户只想要结果, 不想盯。
核心思想: **会话不占着等** —— 把"等"变成脚本, 把"报"变成哨兵 cron, 自己只在有实质进展时出现。

## 三段结构

```
[执行体] 接力脚本 (chain_*.sh)     串行重活: 上游结束 → 自动起下游
[心跳]   哨兵 cron (no_agent)      产物齐 → 出报告; 死了但产物缺 → 报失败; 否则静默
[状态]   flag 文件 (*.reported)    保证只推送一次, 不重复刷屏
```

## 1) 接力脚本: 串行而不是并行

抢同一份资源的两件事 (出口带宽 / 一块 GPU / 磁盘写) **不要并行**。让小的先跑完, 再自动起大的:

```bash
#!/usr/bin/env bash
set -uo pipefail
LOG=/path/results/autopilot.log
say() { echo "[$(date '+%F %T')] [接力] $*" | tee -a "$LOG"; }

say "等待上游流水线结束..."
while pgrep -f "intact_autopilot.sh --tasks .tworoom" >/dev/null 2>&1; do sleep 60; done
sleep 20                       # 让上游收尾 (删归档/写汇总) 落盘
say "上游已结束 → 起下游 (断点续传)"
bash /path/intact_autopilot.sh --tasks "cube" --seeds "0 1 42" --num 100 >> "$LOG" 2>&1
say "下游流水线结束"
```

后台起: `terminal(background=true, notify_on_complete=true)` (长跑完成时会有一次系统通知)。
`pgrep -f` 的模式要能唯一命中 (带上 --tasks 参数), 否则可能匹配到自己或别的会话。

## 2) 哨兵 cron: 有内容才发, 否则静默

用 `cronjob(action='create', no_agent=true, script='<name>.sh')`:
- stdout **非空** → 原文推送给用户; **空** → 完全静默 (用户什么都不会收到)
- 非 0 退出 / 超时 → 框架自动发错误告警

模板 (完整实例见 `references/intact-four-task-case.md`):

```bash
set -uo pipefail
OUT=/path/results; LOG=$OUT/autopilot.log
OK_FLAG=$OUT/.reported; FAIL_FLAG=$OUT/.failed_reported
[ -f "$OK_FLAG" ] && exit 0                      # 报过就永久静默

alive=0; pgrep -f 'autopilot|chain_' >/dev/null 2>&1 && alive=1
missing=""; for t in a b c d; do for s in 0 1 42; do
  [ -f "$OUT/${t}_seed${s}.json" ] || missing="$missing ${t}_seed${s}"
done; done

if [ -z "$missing" ]; then                       # ① 全齐 → 出表 (一次)
  python3 /path/summary.py "$OUT" >/dev/null 2>&1
  echo "✅ 全部完成"; echo; sed -n '/^# /,$p' "$OUT/SUMMARY.md"
  touch "$OK_FLAG"; exit 0
fi
if [ "$alive" = "0" ] && [ ! -f "$FAIL_FLAG" ]; then   # ② 死了且缺货 → 诚实上报 (一次)
  echo "⚠️ 流水线已结束, 结果缺失:$missing"; tail -12 "$LOG"; touch "$FAIL_FLAG"
fi
exit 0
```

要点:
- **失败分支必须有**。只写成功分支 = 流水线崩了用户以为还在跑, 静默丢失比报错更糟。
- 状态 flag 防重复推送 (哨兵每 20 分钟跑一次, 不能每次刷屏)。
- 挂 cron 前**先手动干跑脚本**: 未完成时应"零输出、rc=0"。有输出说明判据写错了。
- 让哨兵自己生成报告 (`summary.py` + `sed` 取段), 不要依赖上一次会话留在上下文里的数字。

## 3) 交付通道: CLI 会话收不到 cron 输出

从 CLI 会话创建的 cron 是 **local-only**: 输出只落库, 不会回到那个终端。
要让用户收到, `deliver` 必须指向已接的网关平台 (如 `feishu:oc_xxx` / `telegram:...`), 不要用默认/`origin`, 也不要向用户承诺"会在终端里弹出来"。

## 陷阱

- **不要编辑正在运行的 bash 脚本**: bash 按字节增量读取脚本文件, 运行中改动可能让执行流错乱。要加门/加钩子就**另起一个 watcher 进程** (轮询 + 状态文件), 或等它跑完。
- **报"完成"前必须有真实产物证据**: 文件真打开/真解码/统计量对得上 (见 `hf-dataset-subset` 的
  `references/hdf5-blosc-verification.md` 与 `scripts/verify_h5_dataset.py`), 不能只看 exit code 或"文件存在"。
- **同机多任务抢 GPU**: 起训练/评测前 `nvidia-smi` 看 free; 判断某进程是否占显存要看代码 (模型 device 由参数所在 device 决定; 有的评测只用 `CUDA_VISIBLE_DEVICES` 给 MuJoCo EGL 选渲染卡), 别凭印象说"不抢卡" —— 真起跑时再复核一次。
  🔴 **判断"现在能不能起"看 `memory.used`, 不要看 `utilization.gpu`**: 实测见过 `utilization 0% 而 memory.used 7267/8188 MiB`
  ⇒ 拿 0% 断定"卡空着"一起跑就 OOM。回答"所有模型能同时训练吗"要拿**显存预算加法**说话
  (各阶段申报 gpu_mb 相加 vs 整卡总量), 并给全三层: 串行一条命令=可以 / 真并发=不行(带数字) / 要真并发就换架构。
  详见 `references/multi-stage-orchestrator-rc-and-gpu-oom-2026-09-22.md`。
- **磁盘闸门**: 大任务前先算 "归档×2~3 + 解压后" 的峰值占用, 低于红线直接跳过并诚实记录 (别硬跑把盘打满)。
- **一个写者**: 同一份数据集/产物只允许一条流水线写。幂等判据用"结果文件是否已存在", 但别忘了"结果齐时仍要把数据补齐"这种混合状态 (踩过: 因为结果齐就整段 continue, 连数据都没下)。

## 用户催进度时怎么答 (本用户: 只发"静静"就是催)

先查实况, 再答 —— 不许凭记忆。一次并行取: 进程存活/etime、日志尾进度与 ETA、GPU 利用率与显存、
磁盘可用、产物文件清单。然后给:
1. **最简现状** (每行: 在跑什么 + 进度 + ETA + 有没有异常)
2. **行动选项** (A/B/C, 把你建议的默认项放第一个并说明"已在自动跑")

要点: 说清"实际在跑什么" (老倪红线: 说了没做=不可接受); 指标不夸大 (真实均值+波动区间); 缺口如实标注 (如"cube 未评测"不许含糊成"已完成")。

## 参考

- `references/multi-stage-orchestrator-rc-and-gpu-oom-2026-09-22.md` — 多阶段训练编排: **逐阶段读 rc/JSONL** ·
  OOM 真凶是资源冲突而非模型太大 · "一起训练"的定性(顺序流水线 vs 共享梯度) · **同卡并发=显存预算加法**
  (单层实测 5728 MiB / 整卡 6395 MiB; 两层各 6000 MB 相加必放不下) · 不抢卡纪律。
- `references/intact-four-task-case.md` — INTACT 官方四任务评测的完整实例: 接力脚本原文、哨兵脚本原文、四任务汇总表格式、tworoom 验证数据与 blosc 坑、以及"cube 因磁盘闸门未评测"的诚实标注写法。
