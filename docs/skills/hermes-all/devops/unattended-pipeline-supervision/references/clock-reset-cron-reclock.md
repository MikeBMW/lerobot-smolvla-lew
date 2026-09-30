# 开机时钟复位 → 全部 cron 静默罢工: 诊断与 reclock 实操 (2026-09-15 实测)

原始副本见本技能 SKILL.md「坑」表的 *系统时钟被 NTP 往回拨* 一行; 这里是完整的现场处置流程。

## 症状 (本机 2026-09-15 实况)
- `date` 显示 17:17, 但 `~/.hermes/cron/jobs.json` 里 13 个 job 的 `last_run_at` 是 `2026-09-16T00:46`,
  `next_run_at` 是 `2026-09-16T01:06` —— 即**用"快 7.5~8h 的旧钟"算出来的时刻**, 比真实 now 晚 ~7.5h。
- 结果: 所有 watchdog/哨兵 (sys-watchdog / 数据链路巡检 / 磁盘红线 / 各判闸哨兵) **整晚一次都不会触发**。
- 而它们的失败模式恰好是"静默 = 无事", 没人会察觉 —— 只有独立心跳 (sys-watchdog) 或人工核对会暴露。

## 诊断三连 (先证时钟本身, 再动 cron)
```bash
date; timedatectl | head -6          # System clock synchronized: yes / NTP service: active
sudo hwclock --show                  # RTC 与 UTC 是否一致 (本次一致 → 是开机早期用 RTC 置钟后被拨正)
curl -sI https://www.baidu.com | grep -i '^date:'   # 与钟无关的外部时间源比对 ← 决定性证据
journalctl -b -1 -o short-iso | tail -5             # 上一 boot 结束时的时间戳
grep -n 'next_run_at' ~/.hermes/cron/jobs.json      # 与 now 的差 > 2×interval 即"被推后"
```
判据: **`next_run_at - now` > 2×interval** → 该 job 已被旧钟污染, 需要 reclock。

## 现场 reclock (两种等价做法)
```bash
# A) 逐个 CLI 重算 (display 从 jobs.json 的 schedule.display 读, 不要手抄)
hermes cron edit <job_id> --schedule "every 20m"
# B) 会话内工具
cronjob(action='update', job_id=<id>, schedule=<原样>)
```
批量骨架 (只处理 enabled 且非 paused 的):
```bash
python3 - <<'PY' > /tmp/_reclock_cmds.txt
import json
jobs = json.load(open("/home/ubuntu/.hermes/cron/jobs.json"))
jobs = jobs if isinstance(jobs, list) else jobs.get("jobs", [])
for j in jobs:
    if not j.get("enabled") or j.get("state") == "paused":
        continue
    disp = (j.get("schedule") or {}).get("display")
    if disp:
        print(f'{j["id"]}\t{disp}')
PY
while IFS=$'\t' read -r id disp; do hermes cron edit "$id" --schedule "$disp"; done < /tmp/_reclock_cmds.txt
```

## 复核 (必须做, 不能只看命令输出)
1. 立刻读 `jobs.json`, 算每个 `next_run_at - now` —— 本次结果从 13 个全在 +7.5~8h 变成 +8~30min ✅
2. **等 60~90s 再读一次**: 确认网关 (systemd `hermes-gateway`) 没有用它内存里的旧值回写覆盖。
   2026-09-15 实测: 网关运行中离线编辑 jobs.json **是持久的** (75s 后值不变), 不需要重启网关。
3. `cronjob(action='list')` 比对一次 (工具视图与磁盘一致)。
4. 可疑判据脚本化: `mins > 120` 就打 `<== 可疑(未重算?)`。

## 开机自动化脚本 (已存在, 有两个真坑)
`/home/ubuntu/.hermes/scripts/hermes_cron_reclock.sh`, crontab `@reboot sleep 30 && <脚本>`, 日志
`~/.hermes/logs/cron_reclock.log`。逻辑 = 等 NTPSynchronized=yes (最多 6min) → 逐个 edit → 落日志。

- **坑① (致命, 2026-09-15 发现): cron 裸环境 PATH 里没有 `hermes`**
  (`env -i /bin/bash -c 'command -v hermes'` → 空; cron 默认 PATH=/usr/bin:/bin)。
  旧版脚本直接 `hermes cron edit ...` → 每行 `command not found`, 且被 `2>&1 | grep -c` 吞掉 →
  **每次开机都白跑, 日志还显示"处理 13 个任务"**。修法: `HRM=/home/ubuntu/.local/bin/hermes` 用绝对路径,
  并在开头 `if ! "$HRM" cron list >/dev/null 2>&1; then 落 FATAL 日志; exit 1; fi`。
- **坑②: 别用 CLI 文本判成功**。`hermes cron edit` 输出只有 `Updated job: <id>` + Name/Schedule/... ,
  **没有 "Next run" 行** —— 旧脚本 `grep -c "Next run"` 恒为 0, 把成功也记成 0, 掩盖了坑①。
  判据改用 `grep -q "Updated job"` + **读 jobs.json 复核** `next_run_at`。

## 相关纪律
- 报绝对时间前先核对时钟 (`date` + `timedatectl` + 外部 HTTP Date); 用户看到的"整晚没消息"可能就是这类静默罢工。
- 时钟复位属于"静默哨兵死亡"的典型触发源: 需要一个**与 cron 无关**的独立心跳去暴露它。
