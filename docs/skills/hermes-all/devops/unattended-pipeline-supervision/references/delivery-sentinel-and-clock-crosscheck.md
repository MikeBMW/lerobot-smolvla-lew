# 交付型哨兵 + 时钟交叉验证 (2026-09-14 实测)

> 应挂到本技能 SKILL.md 的「变体」与「坑」两节下 (SKILL.md 已含: 早收型哨兵 · 时钟跳变坑 · 僵尸进程坑)。

## 一、「交付型」哨兵: 落盘即自检, 然后才交付

触发: 老倪说「**半小时之内要有个模型, 我可以测试一下**」。

要点: 用户要的是**能测的东西**, 不是一个路径。产物一落盘就先自证再用, 别把未验证的路径丢给人。

1. **轮询文件 + 尺寸双条件** —— crash-safe 保存是 `.tmp` → 原子改名: 见到 `.tmp` 就继续等; 尺寸要够
   (实测基线: INTACT 权重 83,925,120 B)。
2. **落盘后立刻跑真推理冒烟**: 抽少量真帧 (例 `--n 24`), `--device cpu` 不抢训练显存; 读回
   `model_xyz_mae / const_xyz_mae / pred_std÷teacher_std` —— 证明"能加载 + 真出动作 + 不是零/常量"。
3. **交付三件套一起给**: 产物绝对路径 · 切换开关 (GUI 节点参数 / env, 例
   `INTACT_POLICY=<dir>/weights_epoch_1.pt` + `INTACT_RUNTIME=root`) · 一条可复现命令。
4. **等待期间别让人干等**: 先给"现在就能测的旧产物 (需仍在盘上)" + "N 分钟后落盘"的时间点。
5. 轮询文件**不依赖时钟** ⇒ 系统钟被 NTP 拨动也不会误判, 比"睡到某时刻再干活"稳。

实测脚本落档: `/home/ubuntu/l4_ab/wait_ep1_smoke.sh` (bg + notify_on_complete)。

## 二、时钟交叉验证 (报任何绝对时间之前)

本次事故: 会话开头读到 18:54, 真实是 10:54 —— 开机后 ~1 分钟 `systemd-timesyncd` 把偏了 **7.5 小时的 RTC**
拨正 (journald: `Time jumped backwards` / `Initial clock synchronization to ...`)。后果有两层:

1. **报给用户的绝对 ETA 整体错一截** (相对时长是对的, 只有标签错)。
2. **所有"每 N 分钟"的 cron 静默罢工**: `next_run_at` 是用旧钟算的, 拨正后落在将来 7.5h (本次 9 个 job
   受影响, 含关键判闸哨兵) → 必须逐个 `cronjob(action='update', schedule=<原样>)` 重算, 再 list 复核。

诊断配方 (照抄):

```bash
date; date -u; timedatectl | head -8                     # 时区/NTP 状态/RTC
journalctl --since "-2 hours" | grep -iE "time (jump|step)|timesyncd|chrony|clock"
# 与钟无关的交叉验证: 进度计数 × 实测速率 = 真实跑了多久
#   例: 训练 step 3750 × 0.48 s/step = 30.0 分钟 ↔ 训练起点日志 10:54 ↔ 当前 11:24 自洽
```

判断规则: **两个读数打架时, 相信"进度×速率"这种物理量, 不相信墙上钟**; 报时间段时优先给相对时长
("18 分钟后落盘") 而不是绝对时刻, 并在给绝对时刻前做上面两步核对。

复核 cron 是否全恢复 (一次看全, 别逐个猜):

```python
import json, os, datetime
jobs = json.load(open(os.path.expanduser("~/.hermes/cron/jobs.json"), encoding="utf-8"))["jobs"]
now = datetime.datetime.now().astimezone()
for j in sorted([x for x in jobs if x.get("enabled", True)], key=lambda x: str(x.get("next_run_at"))):
    t = datetime.datetime.fromisoformat(j["next_run_at"])
    d = (t - now).total_seconds() / 60
    print(f"{'🚨' if d > 150 else '  '} {d:+7.1f} 分钟  {t:%H:%M}  {j['name'][:38]}")
# 注意: 间隔本身 >150 分钟的 job (例 6 小时同步) 会假阳性 → 按各自 schedule 判
```

⚠️ 双系统 RTC 铁律不变: **不许动 `adjtime`/手工改 RTC**, 只做核对与重算。
