# 常驻守护进程的存活纪律 + 消费型循环吞包 (2026-09-15 实测)

无人值守体系里, "长跑脚本" 之外还有一类更脆的组件: **常驻消费型守护** (边学边练闭环 `tools/auto_loop.py`
这类: WS 订阅数据到达 → 落盘 → 触发训练 → 上传)。本次它静默吞掉一包数据, 并暴露三个通用坑。

## 坑① 消费型循环「吞包」= 顺序反了 + 目录没建 (最贵的一条)

现场: 小芳侧推来一包 `pkg_20260915_171114.json` (115 帧) → WS 事件触发处理 → 日志一句
`Exception in thread Thread-2 (process_new_data): FileNotFoundError: .../data/orin_live/auto_...json`
→ 之后一切正常, 但**那包数据永久消失**, 训练没起。

根因两条, 都是通用反模式:
1. 写入前没建目录: `fp.write_text(...)` 目标是 `data/orin_live/`, 该目录不存在 (或被清理) ⇒ 抛异常。
2. **先标记「已处理」再落盘**: 代码在写盘之前就 `SEEN.add(latest)`, 于是异常后该包被永久视为已处理,
   轮询兜底也不会重试 ⇒ **静默丢包** (日志里只有一次线程栈, 守护本身继续跑, 用户侧只看到\"没训练\")。

修法 (顺序铁律):
```python
LIVE.mkdir(parents=True, exist_ok=True)          # ① 写前建目录
try:
    fp.write_text(json.dumps(pkg, ensure_ascii=False))
except Exception as ex:
    log(f"❌ 落盘失败, 该包保留待重试: {ex}"); return   # ③ 失败不置已处理
SEEN.add(latest)                                  # ② 落盘成功之后才标记
```
自检问句: 「这一步失败时, 这个包/任务会不会被永远跳过?」顺序错了就答\"会\"。

## 坑② 常驻守护静默死亡 → 用 5 分钟兜底守护自愈

- `@reboot` 只能保证开机拉起; 进程中途死掉 (线程异常/被杀/OOM) 没人管, 而它的失败模式正是\"静默\"。
- 兜底行 (幂等, 与 `@reboot` 共存):
  ```cron
  */5 * * * * pgrep -f "[a]uto_loop.py" >/dev/null || ( cd /home/ubuntu/lerobot-smolvla-lew && /home/ubuntu/lerobot-venv/bin/python tools/auto_loop.py >> /home/ubuntu/lerobot-smolvla-lew/outputs/auto_loop.log 2>&1 )
  ```
- 复核要\"实际在跑什么\": `pgrep -af '[a]uto_loop.py'` (pid) + 日志尾 (是否真在等数据/真在训练)。
  只看到 cmdline 出现过不算 —— 本次重启后必须确认 WS 重连成功 + 队列读取正常。

## 坑③ `pgrep/pkill -f` 匹配到调用 shell 自身 = 自杀 (exit -15)

一条复合命令 `pkill -f 'tools/auto_loop.py'; ... | crontab -` 执行到一半整个 shell 被 SIGTERM
(`exit_code: -15`), **crontab 那半步没执行** —— 因为调用行的命令行里含同样的字面量, 被 `pkill -f` 一起匹配。
- 修法: 模式加方括号打断自匹配 —— `pgrep -f '[a]uto_loop.py'` / `pkill -f '[a]uto_loop.py'`
  (调用行里是 `[a]uto...`, 不再匹配正则 `auto...`); 更稳: 先 `pgrep -af` 列 pid, 再逐个 `kill <pid>`。
- 连带纪律: 破坏性命令执行后**必须复核副作用是否落地** (本次 crontab 没装上, 若不复核就会以为装了)。

## 坑④ Hermes 环境里怎么起常驻进程

前台命令里写 `nohup` / `setsid` / 结尾 `&` 会被 Hermes **硬拦** (返回 error, 命令不执行)。
- 正解: `terminal(background=true)` 启动; 要跨会话/跨重启存活就靠 `@reboot` + 坑②的 `*/5` 兜底行。
- 别为了绕过拦截去拼字符串, 那是给守护进程埋雷。

## 相关

- 时钟复位导致\"所有 \"每 N 分钟\" 任务静默罢工\": `references/clock-reset-cron-reclock.md`
  (@reboot 脚本在 cron 裸环境里没有 `hermes` PATH → 每次开机白跑; 判成功要读 jobs.json, 别 grep CLI 文本)。
- 终态一次性上报 (静默=无事 的去噪机制): 本技能 SKILL.md 的三态 flag 设计。
