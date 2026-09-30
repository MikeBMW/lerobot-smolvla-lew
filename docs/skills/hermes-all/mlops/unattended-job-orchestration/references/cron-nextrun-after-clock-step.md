# 时钟被拨 → Hermes cron 全体 next_run 后移 → 哨兵整天静默 (2026-09-15 实录 + 修复脚本)

## 症状 (与"没活儿"无法区分, 最坑的是它零报错)

- 用户只发「静静」。查实况发现: 13 个 enabled 任务 `next_run_at` 全在 **8 小时后**
  (`last_run_at = 2026-09-16T00:46`, 而 `date` = `2026-09-15 17:17`) ⇒ 整晚不会触发,
  但 `state=scheduled` / `last_status=ok`, 一切"看起来正常"。
- 根因: 本机 RTC 在开机时先被内核用来置系统钟, NTP 约 30s 后才拨正 ⇒ **网关在"偏掉的钟"下算的
  next_run 被推到 8 小时后**; 只有 agent 类任务 (带 workdir/API 调用, 用墙上时间重新排相位) 免受影响,
  `no_agent` 脚本类哨兵 **全体中招**。历史上还有一次 20:21 → 次日 00:46 → 又回 16:59 的来回拨钟。

## 判据 (30 秒自查)

```bash
date; timedatectl | head -6                 # 先确认现在几点、NTP 同步状态
curl -sI https://www.baidu.com | grep -i '^date:'      # 外部时间交叉核对 (系统钟可能才是错的)
python3 - <<'PY'                            # 每个任务: next_run 距现在多少分钟
import json, datetime
jobs = json.load(open("/home/ubuntu/.hermes/cron/jobs.json"))
jobs = jobs if isinstance(jobs, list) else jobs.get("jobs", [])
now = datetime.datetime.now(datetime.timezone.utc).astimezone()
for j in jobs:
    if not j.get("enabled"): continue
    d = datetime.datetime.fromisoformat(j["next_run_at"])
    print(f'{(d-now).total_seconds()/60:7.1f}min  {j["id"]}  {j.get("name")}')
PY
```
**任何 next_run 超过 2×interval 的任务 = 相位被推走, 立刻重算。**
(`catch_up_occurrences` 文件 / `.fire-*.lock` 文件也可旁证上次触发时间。)

## 修复: 逐个重算 next_run (幂等, 网关运行中也生效)

```bash
cd /home/ubuntu
python3 - <<'PY' > /tmp/_reclock.txt          # 只处理 enabled 且非 paused
import json
jobs = json.load(open("/home/ubuntu/.hermes/cron/jobs.json"))
jobs = jobs if isinstance(jobs, list) else jobs.get("jobs", [])
for j in jobs:
    if not j.get("enabled") or j.get("state") == "paused": continue
    disp = (j.get("schedule") or {}).get("display") or j.get("schedule_display")
    if disp: print(j["id"], disp)
PY
while read -r id disp; do hermes cron edit "$id" --schedule "$disp" | head -1; done < /tmp/_reclock.txt
# 然后复查: 再用上面的 python 片段打印, 确认全部落回 now+interval
```

实测要点:
- `hermes cron edit <id> --schedule "every 15m"` 输出是 `Updated job: <id>` + Name/Schedule/Skills/Script/Mode —
  **没有 "Next run" 行**; 用 `grep -c "Next run"` 判断成败会永远得 0 (旧脚本就踩了这个, 日志全是 `next_run_lines=0`)。
- 编辑**离线改 jobs.json 并持久化**, 网关不会用内存副本回写覆盖: 改完 75s 后再读, 值未变 (实测)。
- 官方 cron 列表接口 (`cronjob action='list'`) 复查最直观。

## @reboot 自动重算脚本的两个坑 (修好的版本在 ~/.hermes/scripts/hermes_cron_reclock.sh)

1. **cron 裸环境 PATH 里没有 hermes** ⇒ 脚本里写 `hermes cron edit ...` 每次开机静默
   `command not found`, 13 个任务一个都没重算, 而日志只记 `next_run_lines=0` 看不出问题。
   修: `export PATH="/home/ubuntu/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"` +
   用绝对路径 `/home/ubuntu/.local/bin/hermes` 调用 + **开头自检** (`hermes cron list` 失败就显式
   写 FATAL 到日志并 exit 1)。
2. **判据要能自证**: 重算后打印每个任务的 `next=(+Nmin)`, 把 `>120min` 的标成
   `<== 可疑(未重算?)` 并统计个数 —— 否则"脚本跑了"和"脚本有效"分不清。
   挂法: `@reboot sleep 30 && /home/ubuntu/.hermes/scripts/hermes_cron_reclock.sh`
   (睡 30s 等 NTP 拨正; 脚本内部还会轮询 `timedatectl show -p NTPSynchronized` 最多 6 分钟)。

## 顺带: 恢复被时钟搞死的守护进程

时钟错乱期间 @reboot 起的守护进程 (如数据闭环 `tools/auto_loop.py`) 可能已崩, 且崩溃原因与时区无关
(本次是输出目录不存在 + 异常发生在"标记已消费"之后 → 数据包被永久丢弃)。
恢复顺序: ① 手工 `mkdir -p` 缺目录 + 修代码 ② `pkill -f '[a]uto_loop.py'` 后重启
(**必须用 `[a]` 括号技巧**: `pkill -f 'tools/auto_loop.py'` 会匹配到调用它的 shell 自身命令行 →
把自己 SIGTERM 掉, 实测 exit -15 且后续命令全没执行; 顺带 `pgrep -f` 同样要把模式写进括号)
③ 加 `*/5` crontab 守护 `pgrep -f "[a]uto_loop.py" >/dev/null || ( cd <repo> && <venv>/bin/python tools/auto_loop.py >> <log> 2>&1 )`。
