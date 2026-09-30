# cron 写锁争用 与 空转哨兵的审计/退休

来源: 2026-09-20 一次性体检 (用户回来只说了句"元气恢复"). 两个真实故障都是**从 cron 作业健康面**
查出来的, 不是从 `ps` 查出来的 —— 这就是本文的用法: 例行体检必须把 `cronjob(action='list')` 当一等公民。

## 故障 A: 同一 workdir 的两个 LLM cron 抢 TERMINAL_CWD 写锁

观测: job「L4性能提升进度报告」16:05 那轮 `last_status=error`, 报告文件里只有一段:

```
## Error
TimeoutError: Timed out waiting for the TERMINAL_CWD write lock after 660s — another cron job
(a workdir writer, or long-running readers) has held it for longer than the cron inactivity limit.
If a workdir job is the holder, stagger its schedule or remove its workdir to unblock this job (#79768).
```

机制: 带 `workdir` 的 job 是**串行**执行的 (为了让每个 job 的 cwd / 项目上下文隔离)。两个 job 都设成
`/home/ubuntu/<repo>` 且都是 `every 30m` (`:04` 与 `:06`) → 前者一轮要跑几分钟到十几分钟, 后者拿不到锁,
干等 660s 后整轮失败。受害者可能是**更重要的那个** (L4 进度报告), 而凶手是早已无用的空转 job。

判据 (list 里就能看出苗头):
- 两个或更多 job 的 `workdir` 相同;
- `schedule` 有重叠 (`every 30m` / `*/15 * * * *` 混搭最容易撞);
- 其中一个长期 `last_status: error` 且报错文本是 TERMINAL_CWD / write lock.

三条修法 (按优先级):
1. **删掉非必要 job 的 `workdir`**: 真正需要仓库上下文 (跑 pytest / 相对路径脚本 / 需要 AGENTS.md 注入) 的才留。
   只读日志/读绝对路径产物的 job 完全不需要 workdir。
2. 时间错开 (至少错开一个 job 的典型耗时, 实战取 ≥10min)。
3. 保留 workdir 但把并发降为 1 的唯一 job, 其余改 `no_agent` 脚本 (脚本不受 cwd 锁影响)。

验证要看**下一轮**是否恢复: 手动 `cronjob(action='run', job_id=..., prompt='【人工验证】...')` 触发一次,
在 prompt 里要求报告开头带一句证认 (如"验证运行:锁已放开"), 这样飞书里那条消息本身就是证据。

## 故障 B: 哨兵的生命周期没有终点

v10 足量训练 09-12 14:55 就完成并评估完 (结论: 不能接管, 维持影子集成), 但对应训练哨兵 cron
又空转 8 天, 每 30 分钟出一份"目标已终结, 建议停用"的报告并推飞书 —— 同时还占着 workdir 锁 (故障 A 的凶手)。

纪律:
- 建哨兵时就在 prompt/脚本头部写清 **退出条件**: "目标 ckpt 目录出现最终步数 + 评估完成 → 报一次并 `touch .reported`"
  或明确"新训练启动后需要重新挂钩"。
- 例行体检 (`cronjob(action='list')`) 逐项核对: `last_status` 有没有 error / `next_run_at` 是不是被时钟拨到
  很远的将来 / 有没有 job 的目标产物早已终结。
- 退休用 `pause` 不用 `remove` (可逆), 并在回复里说明"已暂停, 需要时一条命令恢复"。
- 顺带: 停掉凶手 job 后, 受害 job 的失败会自动恢复 —— 这就是"止损"的具体动作, 比通知用户"报告坏了"有用得多。

## 体检清单 (用户说"静静/怎么样了/元气恢复"时一次并行取)

不许凭记忆答, 一次并发取完再写:
1. `date; uptime` + `ps -eo pid,etime,pcpu,cmd --sort=-pcpu | grep -Ei 'python|train|ros2|studio'` — 本地在跑什么
2. `nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv` + `df -h /` — 卡和盘
3. `cronjob(action='list')` — 每个 job 的 `last_status` / `last_run_at` / `next_run_at`
4. `~/.hermes/cron/output/<job_id>/` 最新一两份报告 — job 到底在说什么 (本轮两个真问题都藏在这里)
5. **外部依赖可达性**: 网关/中转域名一次 `curl -w '%{http_code} {time_connect}'` (见 `http-relay-service`
   的 `references/host-down-vs-service-down-triage.md`)
6. 本地链路的"还在长"证据: 关键产物文件的 mtime (例: `ls -lt <state.jsonl>`) —— 证明采集/推理真的活着

报告写法: 每行"在跑什么 + 数字 + 有没有异常", 分组 (本地链路 / 外部故障 / 已处理 / 待办), 只给真实值。
**不要列 A/B/C 菜单** —— 用户明确说过"别选那么多"; 有真决策时给一条建议 + 一句"要不要我…"。
