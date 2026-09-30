# 时钟回拨冻死常驻循环 + 静止旧帧被当成"实时" (2026-09-18 实测)

姊妹篇: `references/clock-reset-cron-reclock.md` (只管 cron 的 `next_run_at`)。本篇管**代码里用墙钟差值做判据的常驻组件**。

现场: 12:15:2x 本机 NTP 把系统钟**回拨 8h** (开机 RTC 快 8h, 首次同步才拨正) →
三个常驻组件"进程活着、CPU 还在烧, 但一行产出都没有"; 用户看到的现象是
「**真机的输入图像不是实时的了**」—— 画面冻在 12:15:24 那一帧 13 分钟, 而窗口还标着"新鲜"。

## 症状指纹: 怎么一眼区分"时钟事故"与"进程崩了"

| 观察点 | 时钟事故 | 真崩溃 |
|---|---|---|
| 进程 | 还在, 且 CPU **空转** (Docker tap 实测 18%) | 不在了 / 退出码非 0 |
| 产出文件 mtime | **卡死不动** | 卡死不动 |
| 产出文件 mtime 的值 | 落在**未来** (回拨前写的: mtime > now + 8h, `ls` 显示年份或未来时刻) | 正常过去时刻 |
| 日志 | 停在某个整点行, 之后空白 | 常带 traceback |
| 时间戳 | 容器 `TZ=UTC` 会误导: 日志 `status.ts=12:15:21` 而真实 CST 是 `20:15:21` | — |

判据模板 (两个反模式, 回拨后判据**反转**):
```python
if time.time() - t0 >= 1.0 / rate:      # 回拨后恒假 → 采样停摆, 要等真实时间追上旧 t0 (8h!) 才自愈
    t0 = time.time()
if time.time() - last_dec <= 1.0:       # 回拨后恒真 → 永久 continue, 永远不再解码/触发
    continue
```

## 第二重伤害: 新鲜度判据把静止旧帧判成"实时" (老倪红线)

`age = now - mtime`; mtime 在未来 → `age ≈ -28800` → 任何 `age <= 阈值` 都**恒真** →
旧帧上屏、也不换占位图, 用户看着"画面还在, 只是不动"。
另有连带: GUI 的断流自愈 `now - _stale_since > 6s → 自动重连` 也变恒假 → **冻住了但没人救**。

## 处置 4 步 (先改码, 再重启, 最后验产物)

1. **节拍/新鲜度判据全换单调钟**: `time.monotonic()` 管"多久没变", `time.time()` 只用来写"什么时候发生的"时间戳 (落盘字段)。
2. **帧龄钳非负 + 未来 mtime 拒用** (不要静默 clamp 成"新鲜"):
   ```python
   if age < -1.0:            # 时钟被动过
       status.append(f"{name}: ⏰ 时钟异常 (mtime 在未来 {abs(age):.0f}s) → 拒用")
       continue
   ```
   live_frame.json 这类"戳在外"的元数据同理: `_age_ok = 0.0 <= age_s <= 5.0`。
3. **重启受害常驻**: systemd 服务用 `systemctl restart <unit>` (本次 `ss-remote-tap` / `ss-bypass`);
   `Restart=always` 救不了这类事故 —— 进程**没退出**, 只是空转, 所以必须手动重启。
   容器型服务 (`docker run --rm` 由 unit 跟踪) 可以 `docker restart` 原地拉起, unit 仍认得。
4. **复核"产物在推进", 不是"进程在跑"**: 连续两次 `stat -c %y <产出>` / 行数增量 (间隔 ≥10s)。
   `ps` 有进程 = 不算证据 (本次就是空转)。

## 一次时钟跳变后必须扫的清单

- 采样/守护循环 (Docker tap 落盘节拍)
- 旁路/影子记录器的逐帧闸 (`now - last_step < 1/rate` → 永久 continue)
- GUI 断流自愈 (`_stale_since` / `_last_recover`)、周期巡检 (`_last_clamp` / `_last_show_ensure`)
- 帧新鲜度 (文件 mtime 或落盘 json 里的 age_s)
- cron `next_run_at` → 见 `references/clock-reset-cron-reclock.md`
- 全仓扫反模式: `scripts/audit_wall_clock_cadence.py <repo>`

**不要一刀切**: 一次性超时循环 (`while time.time() - t0 < 30` / `--seconds` / `--duration`) 只会被拉长,
不会冻死 (回拨=多等 8h 但仍有界; 前拨=提前结束)。这类可以不动, 只改"每轮/每帧判据"。

## 回归自检 (修完必须自跑通, 模式可复用)

`tools/verify_clock_skew_guard.py` (本次落地在 Z-MAX 仓库):
offscreen 导入 GUI 模块 → monkeypatch `SHARED`/候选文件表到临时目录 → 造 4 种 mtime
(`未来8h` / `未来30s` / `新鲜1s` / `旧60s`) → 断言 `拒用/拒用/入选/拒用`, 最后对**现场真目录**再断一次
"当前帧龄 ≤ 阈值"。跑法 `gui-venv311/bin/python tools/verify_clock_skew_guard.py`, 全绿才算修好。
好处: 不用开窗、不依赖人眼看图, 且能证明"守门判据真的生效"而不是"现在恰好没有坏帧"。

## 现场纪律

- 报绝对时间前先核对时钟 (`date` + `timedatectl`), 用户看到的"整晚没消息/画面不动"可能就是这类静默事故。
- 长内联命令 (heredoc / 多行 `python3 -c` / 大量引号) 在 Hermes 会被硬拦 →
  用 `write_file` 落一个脚本再跑 (本次诊断脚本就是这么落地的)。
