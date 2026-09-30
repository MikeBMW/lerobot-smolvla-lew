# 时钟被拨 / cron next_run 被推到数小时后 → 哨兵集体静默 (2026-09-15 实录)

**症状**: 开机后 (uptime 3 分钟) 查 hermes 定时任务: 所有任务 `last_run_at` 与 `next_run_at`
都落在**未来 ~8 小时** (例: 现在 17:17, next_run=次日 01:06), 间隔本该 10-30 分钟。
⇒ 全部 watchdog 整晚不触发 = **无人值守防线静默死亡**(没有任何报错, 只有"没消息")。

**根因链**:
1. 开机早期内核先用 RTC 置系统钟, 之后 NTP 才拨正 → 期间网关用**偏掉的时钟**算 `next_run`;
2. 时钟被往回拨后, 已写死的 `next_run_at` 仍是"旧时间轴上的未来" → 调度器认为还没到点;
3. 本机 `@reboot` 修复脚本 `~/.hermes/scripts/hermes_cron_reclock.sh` **每次开机都白跑** ——
   cron 裸环境 `PATH` 里没有 `hermes` (命令 not found 被 `grep -c "Next run"` 吞成 0, 日志全是 0 也没人看)。

**修 (两步都要)**:

```bash
# ① 先核对真实时间 (别信系统钟): 与外部对照 + NTP 状态
date; timedatectl | head -3; curl -sI https://www.baidu.com | grep -i '^date:'
# ② 逐个重算 next_run (用**绝对路径**调 hermes; 幂等, 时钟正常时只是把相位排到 now+interval)
python3 - <<'PY'   # 只取 enabled 且非 paused 的任务
import json
j=json.load(open('/home/ubuntu/.hermes/cron/jobs.json')); j=j if isinstance(j,list) else j['jobs']
for x in j:
    if x.get('enabled') and x.get('state')!='paused':
        d=(x.get('schedule') or {}).get('display')
        if d: print(x['id'], d)
PY
while read -r id disp; do /home/ubuntu/.local/bin/hermes cron edit "$id" --schedule "$disp"; done < <(上面输出)
# ③ 复查: 60-90s 后再读 jobs.json, 确认 next_run 都在各自 interval 内且**没被网关回写覆盖**
```

**复查时排除的假象**: 编辑后值一直是新的 (网关不会用内存副本回写覆盖), 所以改完再读一次即可;
`grep -c "Next run"` 这种输出计数在 hermes CLI 里恒 0 (**别用它判断成败**, 用 jobs.json 里的时间字段)。

**写进哨兵脚本的纪律**:
- `@reboot` 脚本里凡是调 `hermes` 一律用绝对路径 (`~/.local/bin/hermes`), 并把真实 stdout/stderr 落日志,
  **失败要显式报警**(exit≠0 或日志里写 FATAL), 不许"静默成功";
- 重算后自检: 打印每个任务的 `next=... (+Nmin)`, 把 `+Nmin > 2×interval` 的标为可疑;
- 任何"watchdog 一整天没消息"先查这条, 而不是先怀疑业务逻辑。
