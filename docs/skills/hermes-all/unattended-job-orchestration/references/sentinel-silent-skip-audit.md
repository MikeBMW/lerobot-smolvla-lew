# 哨兵自身的审计 —— "我坏了"如何伪装成"没新东西" (2026-09-14 实录)

## 为什么单开一份

no_agent 哨兵的静默语义 (stdout 空 = 不推送) 是设计优点, 但它让**哨兵故障**与**真的没新产物**
输出完全一致: `零输出 + rc=0`。
实测代价: 判闸哨兵连续两次"零输出 exit 0", 逐项排查后才定位到是**防抖窗口 + 本机 NTP 拨钟**
联手把该判的一轮安静吃掉了 —— 期间一度怀疑"没有新 ckpt""标记被顶掉""脚本没被 cron 调起",
全是错的。

**铁律: 哨兵零输出时, 不许直接判定"没活儿"; 必须用独立探针复核。**

## 独立探针四件套 (缺一不可)

```bash
# ① 目标产物是否存在且新鲜 (别只看"存在")
ls -l /path/checkpoints/<run>/weights_epoch_*.pt | tail -3
stat -c '%y %s' /path/checkpoints/<run>/weights_epoch_1.pt

# ② 进程是否真在跑 (注意 pgrep -f 会匹配到自己的命令行 → 用 ps + grep 排除)
ps -eo pid,etime,args | grep "[t]rain.py --config-name"

# ③ 哨兵的 mark/flag 目录里有没有对应条目 (缺 = 哨兵根本没走完判定)
ls -lt /path/judged/ | head

# ④ **把哨兵内部那个判据数字单独复算一遍** (最容易被跳过的一步)
python3 - <<'PY'
import glob, os, re, time
d = glob.glob("/path/checkpoints/<run-glob>")
fam = os.path.basename(max(d, key=os.path.getmtime))
ws  = glob.glob(f"/path/checkpoints/{fam}/weights_epoch_*.pt")
newest = max(ws, key=os.path.getmtime)
print("family =", fam, "| newest =", os.path.basename(newest))
print("距写入 =", int(time.time() - os.path.getmtime(newest)), "s | GRACE =", 180)
PY
```
本例第 ④ 步一跑就露馅: 打印"距写入 100s", 而按墙上时间我以为是 7 分钟 ⇒ 防抖窗口没到,
哨兵按设计静默退出。**没有这一步, 剩下的三个探针全都"正常", 会把人带到错误的方向。**

## 三个具体坑 (都在本例踩到, 已修)

### 1) 去重键用了会重复的短 id
标记名写成 `v6_epoch_{n}.json` + "文件存在就跳过" ⇒ 续训/换轮次 (v6r2 → v6r5) 时,
新轮次的 ep1/ep2 被**上一代**同名标记顶掉 ⇒ 新轮次永远判不出, 且哨兵每次静默。
修: 键 = `{family}_epoch{n}.json` (family = 训练输出目录名); 同时继续写老名字的**兼容别名**
给老读者 (飞书进度报/人工看老路径), 别名覆盖不造成假跳过, 因为去重只看 family 名。

### 2) 用 mtime 增量 / 墙上时间差做防抖
哨兵 GRACE 语义 (刚写完的产物先不判, 防半截 json) 本身没错, 但判据是
`time.time() - mtime < GRACE` —— 本机 RTC/NTP 中途被拨过钟 (同一份产物"距今 7 分钟"实为 100 秒)。
可靠替代: 让执行体自己写 ready 文件, 或用**产物内自证时长**判断 (`[Epoch] done in 511.4s`)。
排查时同理: 算耗时用日志里的 done-in 值, 别用墙上时钟相减。

### 3) 限流规则在短跑场景变成黑洞
"只判 epoch 1/2 与偶数轮"是为长跑省算力写的; 换到短跑 (每轮 400~1000 步) 后,
ep3 这类奇数轮被直接丢 ⇒ 用户看到的是"又没数"。规则随任务形态变时必须重审。

## 判据变更后的作废纪律

口径修复会让**历史判据本身失效** (本例: 运行时图像口径错 ⇒ 所有历史"未过闸"结论作废)。
处置三步, 缺一步就会出现"新结论出不来 + 旧数字被当成本轮读数":
1. 旧标记/产物**改名留证**: `*__prefix_<原因>.json` (例: `..._epoch1__prefix_imgfix.json`)
2. **清掉会挡住重判的条目** (去重键指向的那个文件), 但保留留证副本
3. 用同一套哨兵重跑, 并让报告显式区分"修前/修后"两张表

## 附带: 长跑命令的工具参数
`terminal` 的等待参数名是 `timeout` (前台上限 600s); `timeout_s` 是 browser_exec 的参数名。
**写错不报错**, 静默按 180s 默认值执行 → 几分钟的任务被拦腰掐断, 现象像"任务自己失败"。
>3 分钟一律 `background=true` + `notify_on_complete=true`。
