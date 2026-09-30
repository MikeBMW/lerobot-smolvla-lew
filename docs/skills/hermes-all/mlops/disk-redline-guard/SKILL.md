---
name: disk-redline-guard
description: 磁盘红线守护, 训练产物只留最后ckpt, HF缓存清incomplete, cron每2h自动执行。
---

# 磁盘红线守护 (老倪硬性指令: 磁盘绝不允许增长)

## 触发
- 磁盘使用率上升 / 训练产物堆积
- 老倪指令"磁盘红线/不允许增长"

## 核心规则
1. **训练产物**: 每目录只留最后 checkpoint (中间 ckpt 全删)
2. **HF 缓存**: 删除 .incomplete (下载残留)
3. **红线 300G** (系统盘/根 = E盘 p5; 2026-09-09 老倪从 80G 上调到 200G, 2026-09-13 再上调到 300G — 目标"不超过 300G", 超了报警)
   ⚠️ 2026-09-14 实测: 上调后仍会被训练数据/旧代数据集顶穿 (307G) —— 光靠"删中间 ckpt"不够,
   要按下面 §清理清单 手动清**被取代的旧代数据集**才算真压回来。

## 新增实测坑 (2026-09-29 根目录大整理)

### 坑 1: 按文件名 grep 引用会漏掉“变量拼接的路径”
脚本里常见 `INIT=$CACHE/$PREV/weights_epoch_1.pt` —— 按 `weights_epoch_1.pt` grep 能查到, 但**根本不知道是哪个目录**;
按目录名 grep 又查不到(`$PREV` 是变量)。后果: 删中间轮时会删掉暖启动链需要的那一轮。
**规矩**: ① 每个 ckpt 目录**至少保 `weights_epoch_1.pt` + 最后一轮**;
② 凡在 `tools/*.sh` 里被赋值的目录名(`PREV=xxx` / `ART=xxx` / `NAME=xxx`)全部当活引用, 整目录不删;
③ 删后核对: 每个被删目录的“最后一轮”+上述命名目录的引用文件仍在。

### 坑 2: 通配符消费的原料 npz 不是“零引用”
`intact_insert_dataset_v5.py --parts 'reports/X_part*.npz'` 这类**按 glob 读**的文件, 按真名 grep 永远 0 引用。
删前必须 `grep -rn '_part[0-9*]|part\*|--parts'` 查 glob。

### 坑 3: 嵌套重复目录
`stable-wm-cache/checkpoints/checkpoints/<同名 4 个目录>` —— 某次复制错位的产物(324M)。
判据: 子目录名集合 ⊆ 外层且无独有内容 ⇒ 整目录删。

### 根目录瘦身(老倪: “有用的整合”)
散落脚本/小目录一律 `mv` 进工程对应位置 + 在旧路径 `ln -sfn` 留软链(兼容优先); 删完跑一遍
`crontab -l | grep -oE '/home/ubuntu/[A-Za-z0-9_.-]+'` 逐项验证路径仍存在。

### 坑 4: 清理时控制台/GUI 会 ABRT
批量删/移多 GB 文件时, 控制台后台的扫描线程(dataset/model 遍历)会撞到正在被删的文件 →
原生库 abort(SIGABRT), 表现为“清理期间 GUI 连崩两次”。**先把 GUI 停掉或先不做扫描页**, 清完再起。

## 清理清单 (超红线时按此顺序, 2026-09-14 实测把 307G→295G)

| 序 | 目标 | 判据 | 省 |
|---|---|---|---|
| 1 | INTACT 权重目录中间轮 `$CACHE/checkpoints/*/weights_epoch_*.pt` | 每目录留最后轮; **保护** train config `init_weights_path` 指向的轮 (暖启动源) | 百 MB/个 |
| 2 | 被取代的**旧代数据集** | 只留 官方(cube 95G/reacher 93G) + 当前在用 `optical_insert_v5_disturb.h5`; 更早代 v3/v4.h5 可删 (可重采) | GB 级 |
| 3 | 旧代/无效链权重目录 | 无任何引用 + 判闸数字已落 reports/*.json | 百 MB 级 |
| 4 | 冒烟/探针帧包 `reports/*_smoke_part*.npz`、`*_probe_part*.npz` | 冒烟残渣 | 百 MB 级 |
| 5 | HF `*.incomplete` | 下载残留 | 视情况 |
| 6 | **docker 未用镜像** `docker system df` (Images ACTIVE=0, 无容器) | 本机训练走原生 venv 时容器镜像纯占地; `docker rmi <img>` 可重拉 | **GB 级** (本次 pytorch-cuda 9.6G) |
| 7 | 系统缓存: `journalctl --vacuum-size=200M` / `apt-get clean` / `/var/crash/*` / `~/.cache/pip` / `~/.cache/LarkShell` | 可再生的日志/包/崩溃转储/客户端缓存 | ~1.3G |
| 8 | 训练侧**零代码引用**的旁支 ckpt 链 (`grep -rln <名> --include=*.py --include=*.sh --include=*.yaml . ~/.hermes/scripts` 排除 outputs 自身与日志/state.db) | 本次 v10_r2/v10_r2b 零引用可删; 但被 tools/ 活代码引用的 v10/v10_full/_1h/_fast/_v8/_d1 **必须留** | 百 MB~GB |

**2026-09-14 22:15 实测**: 295G→281G (解放 14G), 最大两笔 = docker 镜像 9.6G + 零引用 ckpt 链 2.8G。台账 `reports/disk_cleanup_ledger_20260914_b.json`。

**删前三条铁律 (v4 脚本已内建前两条)**:
1. `grep -rn "<文件名>" --include=*.py --include=*.sh --include=*.yaml ~/.hermes/scripts l4_ab lerobot-smolvla-lew/tools INTACT-JEPA/config` — 有引用先问"引用的还活着吗"
2. 被**启用中的 cron** 引用的文件: 先 `pause` 那条 cron 再删 (本次: v5 判闸哨兵 cron 24dd99948466 引用 v4.h5 → 先 pause)
3. 先 `sha256sum` 留证 + 写台账 JSON (含 sha256/尺寸/重采命令/保护区核对), 台账样例
   `lerobot-smolvla-lew/reports/disk_cleanup_ledger_20260914.json`

**红线** 300G; 删完必须复核保护区 (在用的数据集/暖启动源/在跑目录) 仍在, 且训练进程仍活着。


```bash
# 手动执行
bash ~/.hermes/scripts/disk_redline.sh
# 已注册 cron (每 2h 自动, job: 磁盘红线守护)
```

## 脚本位置
`~/.hermes/scripts/disk_redline.sh` — 清理 + 检查 + 告警一体
⚠️ 红线改值要 **SKILL.md 与 disk_redline.sh 两处同步** (2026-09-09 80→200G: SKILL 核心规则 + 脚本
`used_gb -gt 200` / `红线 200G` echo 字符串三处都改; 只改一处下次告警口径就不一致)

## 注意
- bc 算术在 WSL 可能缺失 → 用 `awk int()` + `[ -gt ]`
- 只删中间 ckpt 不动 last (训练需要)
