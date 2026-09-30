# 哨兵自身崩溃 + 并行线共存时的巡检纪律 (2026-09-26 实测)

无人值守体系里最贵的一类故障不是"任务挂了", 而是**守护脚本自己挂了却在静默**。本次两件事同时踩到。

## 坑① 哨兵自身崩溃, 只在 cron 里留一个 error
- 现场: `~/.hermes/scripts/chain_health.py` (数据链路 30 分钟巡检) 连续多轮 `last_status=error`, 好几天没人发现。
- 根因: 判定行把**值型字段**当状态字符串用 ——
  ```python
  bad = [k for k, v in res.items() if v.startswith("FAIL") or v in ("DOWN", "OFFLINE")]
  ```
  上游 `/api/relay/orin/status` 的 `model` 为 `null` 时 `res["orin_model"] = None` → `None.startswith` →
  `AttributeError: 'NoneType' object has no attribute 'startswith'`, 整个脚本退出, 一条状态都报不出来。
- 修法 (两条一起用):
  ```python
  STATUS_KEYS_SKIP = ("ts", "disk", "orin_model")          # 值型键只进日志, 不参与状态判定
  bad = [k for k, v in res.items()
         if k not in STATUS_KEYS_SKIP
         and (str(v or "").startswith("FAIL") or str(v or "") in ("DOWN", "OFFLINE"))]
  ```
- 纪律: **每次交接/巡检逐个 `cronjob list` 看 `last_status`**; 出现 `error` 一律当故障处理, 不要默认
  "本地脚本不会有事"。守护脚本挂掉比被守护对象挂掉更危险 —— 它让你以为有人在看。

## 坑② 未被监控的"活跃信号"容易被漏掉
本次 `save_freq=500 > steps=400` 的训练**中途不落 ckpt** —— 只有读到 config 才知道, 光看 GPU 100%/
日志在涨会误判"跑得好好的, 关机没事"。凡是要在关机/重启前判断"能不能停"的任务, 都必须读它的
**落盘策略** (save_freq / steps / 是否只存 last), 而不是看进程活没活。

## 坑③ 同一台机同一仓库跑两条线 → 检出目录必须按线隔离
- 并行线 (硬件遥测: 每 2 分钟自动 commit 一条 `chore(hw)`) 会把**共享工作目录**切到自己的分支。
- 后果: 主线的脚本 / 画布 JSON / 新模块**从磁盘消失**; 引用它们的 systemd 服务还在跑(内存里),
  但 `systemctl restart` 必挂; 控制台重启后加载的是旧版本代码。
- 自证与修法:
  ```bash
  git branch --show-current                 # 提交/发版前先自证在正确的线上
  git worktree add /home/ubuntu/<line-dir> main   # 本线独立检出, 发布/归档都在这里做
  ls -l $(grep ExecStart /etc/systemd/system/<svc>.service | cut -d= -f2 | awk '{print $1}')
  #   ↑ 复查服务引用脚本在"当前检出"里是否存在 —— 进程活着不代表文件还在
  ```
- 细节配方(6 处版本真源漂移 / VERSION.md 被文档迁移删掉 / push 抢推 rebase / 归档别塞大快照):
  `zmax-console/references/release-and-version-sync-under-parallel-lines.md`。

## 相关
- 静默去噪与三态 flag 设计: 本技能 SKILL.md
- 时钟回拨导致"每 N 分钟"任务静默罢工: `references/cron-nextrun-after-clock-step.md`
