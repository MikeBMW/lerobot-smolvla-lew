---
name: linux-host-maintenance
description: "Use when 本机自检/重启后链路核验/清缓存/DNS/网络/性能体检 (Linux 工位机)。"
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [linux, maintenance, dns, network, cache-cleanup, performance, self-check]
    related_skills: [disk-redline-guard, linux-wifi-troubleshooting, hermes-crash-recovery]
---

# Linux 工位机系统体检 / 清理 / 性能 (只做有证据的事)

## When to Use
- 用户说"系统自检 / 清理 DNS / 检查网络 / 清理缓存 / 清洁系统 / 提升性能"(常见于**重启后**或**关机存档之后**)。
- 用户说"**重启了 / 机器回来了 / 元气恢复 / 静静**"(开机后) ⇒ 走 §9 的链路自愈核验, 四行给最简现状; 本机没自愈起来的按 §10 恢复。
- 跑长任务前想把机器状态摸一遍(服务在不在、盘够不够、GPU 有没有空转)。
- 磁盘吃紧 → **磁盘红线部分走 skill `disk-redline-guard`**, 本文管"系统层缓存/服务/性能"。

## 0. 铁律 (先立规矩再动手)
1. **保护清单先写出来**, 清理脚本里逐条核对: 训练数据盘、模型缓存根、在役仓库、数据中转目录、在役权重
   (`model.safetensors` + config + tokenizer)。删完必须复扫一遍"还在 + 无断链"。
2. **只删可再生的**(缓存/日志/转储/回收站)。备份件、镜像归档、旧数据集 → **问, 不要自己删**。
3. **指标不吹**: 拿不准的提升项就实测; 实测没差异 → **回滚**, 不留表演性设置 (实测: CPU 调频档在本机 3 组 A/B 全在噪声内)。
4. 每个动作**报数字** (前/后用量、释放量、耗时、丢包/延迟), 不许写"感觉快了"。
5. 服务启停会动到在役链路 → 长任务在跑时**只清理, 不动服务**。

## 1. 自检清单 (一次跑完, 只读)
```bash
date; uptime; uname -r; lsb_release -ds
systemctl --failed --no-pager            # 必须 0 loaded units
free -h; cat /proc/sys/vm/swappiness
df -h | grep -Ev 'tmpfs|efivarfs'
timedatectl                              # NTP synchronized: yes (负帧龄项目尤其要看)
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor; nproc
nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total,persistence_mode,pstate,temperature.gpu --format=csv
ps -eo pid,etime,pcpu,pmem,args --sort=-pcpu | head -15   # 谁在跑/有没有空转
for s in <在役服务名...>; do printf "%-16s %s\n" $s $(systemctl is-active $s); done
```
判读: GPU `utilization 0~3%` = 没在训练(别写成"在跑"); 桌面进程 tracker/gnome-shell 常驻是正常的。

## 2. DNS "清理"
```bash
resolvectl status | grep -E "Current DNS|DNS Servers"      # 先看解析链 (127.0.0.53 → 上游)
sudo resolvectl statistics | head                          # 清前 cache size (查询监控 socket 需 root; 不加 sudo 报 Permission denied)
sudo resolvectl flush-caches
for h in www.baidu.com open.feishu.cn github.com registry.npmmirror.com hf-mirror.com pypi.org; do
  printf "%-24s " $h; ( /usr/bin/time -f "%es" getent hosts $h >/dev/null ) 2>&1 | tail -1; done
```
口径: 用**逐域解析耗时的清前/清后对照**当证据 (实测 0.02~0.17s → 0.00~0.02s; 复跑: 冷 4~31ms / 热 2~21ms,
清掉的都是长尾域 `hf-mirror` 538ms、`pypi` 177ms)。
- **计时别包成 shell 函数再用 `$( )` 取值**: 调用点写成 `probe >/dev/null` 时重定向作用于**整个函数** ⇒ 命令替换拿到空串,
  每个域都打印成"失败", 看着像全网 DNS 挂了。要函数化就在**函数内部**用 `date +%s%N` 前后差算毫秒再 echo
  (分辨率也比 `/usr/bin/time -f %e` 的 0.01s 好用)。
- **重启后 (<10min) 缓存本就接近冷态** ⇒ 清 DNS 的真实收益只剩长尾项, 如实写"本轮无整体加速, 只清掉两条长尾",
  别把重启后的新气象记成清理收益。
复跑(2026-09-28, 重启后 ~15min 清): cache size 18 → 清前 hf-mirror **1294ms** / dataworld.world **1163ms** /
npmmirror 173ms / github 170ms / open.feishu.cn 110ms / baidu 32ms / pypi 10ms ⇒ flush 后冷解析
hf-mirror 11ms · dataworld 13ms · github 19ms · feishu 35ms · pypi 5ms, 复跑热 4~17ms。
同一时刻现场连通: 工控机 0.62ms · Orin 0.16ms · 产线口(无网关) 0.04ms, 全 0% 丢包。
⇒ 口径照旧: **只记“清掉两条长尾”, 不声称整体加速** (pypi/baidu 清前就只有 10~32ms)。
快栈: 一行出全部数字的脚本按本机实际写 /tmp/*.sh 再跑 (巨型内联命令行会被 Hermes 硬线拦, 不是命令本身的问题)。
局域网设备通常**没有 PTR**(`getent hosts 192.168.x.x` 空 = 正常, 不是故障)。

## 3. 网络连接检查 (一定要含"产线设备可达性")
```bash
ip -br a; ip route
GW=$(ip route | awk '/default/{print $3; exit}'); ping -c3 -W2 $GW        # 网关丢包/延迟
ping -c3 -W2 <局域网 DNS IP>
for t in 223.5.5.5 1.1.1.1; do ping -c3 -W2 $t | tail -1; done           # 公网
ping -c2 -W2 <工控机IP>; ping -c2 -W2 <Orin/设备IP>                       # 现场设备
iw dev <wlan> link | grep -E "SSID|signal|bitrate|freq"                   # WiFi 强度/协商速率
ss -s | head -4
```
真值参考(2026-09-24 工位机): 网关 3ms · 局域网 DNS 1.7ms · 公网 14.8/1.7ms · 工控机 0.9ms ·
WiFi -42dBm/573Mbit/s = 满速档。含 5GHz HE-MCS11/NSS2 才算"好"。
复跑(2026-09-27, 双活: 办公 WiFi + 产线口 192.168.23.50/24 无网关): 网关 2.27ms · 集团 DNS 2.38/2.46ms ·
223.5.5.5 14.9ms / 1.1.1.1 2.6ms · Orin 0.26ms · 工控机 1.10ms, 全 0% 丢包。
判读: WiFi 信号掉了(-42→-59dBm)但 **tx 协商速率没掉(573Mbit/s)+ 0 丢包 ⇒ 不用处理**, 只记数字别当故障报。

## 4. 缓存清理矩阵 (可再生 → 直接删; 曾实测释放)
| 目标 | 命令 | 实测 |
|---|---|---|
| journal | `journalctl --vacuum-size=200M` | ~1.1G |
| 轮转日志 | `rm /var/log/{syslog.1,kern.log.1} /var/log/*.gz` + installer 目录 | ~126M |
| apt | `apt-get clean && apt-get autoclean` | ~135M |
| 转储 | `rm -rf /var/crash/*` | ~7M |
| pip/uv | `rm -rf ~/.cache/pip/* ~/.cache/uv/*` | ~438M |
| 桌面/GL | thumbnails / tracker3 / mesa_shader_cache / gnome-desktop-thumbnailer | ~176M |
| IM 客户端 | `~/.cache/<客户端>` (先确认客户端**没在运行**) | 929M |
| snap 应用 | `~/snap/{firefox,snap-store,chromium,thunderbird}/common/.cache/*` | ~183M |
| 回收站 | `~/.local/share/Trash/{files,info}/*` — **先列文件名再删** | 546M |
| HF 模型缓存 | 只删**零引用**格式导出, 见 §5 | **4.02G** |

总量口径: 上表一轮实测 **7.18GB** (274G→267G)。清理脚本写成 `/tmp/*.sh` 文件再跑 (别塞内联长命令),
并落**台账 JSON**(每项前/后 MB + 总量) 到项目 `reports/`。

## 5. HF 缓存瘦身 (最大那一笔, 也能最危险)
先分形态再动手: `du -sh <模型目录>/blobs <模型目录>/snapshots` + 逐个 `du -Lh` 列 snapshot 里的符号链接。
- 本机代码 `grep -rn "onnx" --include=*.py tools/ .hermes/scripts` **零加载引用** ⇒ `onnx/*` 导出可删
  (实测 SmolVLM2-500M 的 12 个 onnx 变体 4.02GB, 而运行时只吃 `model.safetensors` 2.03GB)。
- 删法两条: ①先删 snapshot 里的 onnx 符号链接 ②再删"已无任何 snapshot 引用"的 blob → **不留断链**
  (扫 `find <目录> -xtype l` 应为空)。脚本: `scripts/hf_prune_onnx.py <模型目录> [--dry]`。
- 删后必须核对 `model.safetensors`/config/tokenizer 仍在且可解析; 记下重下命令
  `hf download <repo_id> --include 'onnx/*'`。**.incomplete 残留**永远可以直接删。

## 6. 性能: 先测, 再决定, 没收益就回滚
**协议**(照做, 否则得出的都是噪声):
1. 交错 A/B (A,B,A,B…≥3 轮), 每轮多次取中位数 —— 不要"先全 A 后全 B"。
2. **负载要选对**: 带宽瓶颈型 (大矩阵 matmul) 对调频档不敏感; 频率敏感型要用**缓存驻留**的计算密集负载。
3. 同一次会话里至少换 2 种负载; 差异落在噪声内 ⇒ 如实写"无可测影响"。

实测(2026-09-24 工位机, powersave vs performance): 2048³ 带宽型 0.90× · 2048³ 8 线程 1.013× ·
384³ 缓存驻留 0.997× ⇒ **CPU 调频档无收益 → governor/电源档全部回滚**(驱动 intel_pstate, EPP 本就偏性能档)。

**真正落地/确认过、能拿数字说话的 4 项** (2026-09-26 复跑全部确认在位):
1. GPU `sudo nvidia-smi -pm 1` → persistence_mode=Enabled (反复起停 CUDA 进程时省驱动重初始化)。实测 Disabled→Enabled 一步生效。
2. 关掉桌面索引器: `systemctl --user mask --now tracker-miner-fs-3.service`(+`tracker3 daemon -k`);
   恢复 `systemctl --user unmask --now tracker-miner-fs-3.service`。实测 → masked/inactive。
3. `fstrim.timer` enabled+active (NVMe TRIM); 未开就 `systemctl enable --now fstrim.timer`。实测本轮 `fstrim -v /` = **105.3 GiB trimmed**。
4. journal 封顶 + 缓存清理 = 降后台 I/O 与写放大。实测 journal **438MB→151MB**。
**2026-09-26 一轮清理实测 (脚本 /tmp/sys_clean_full.sh, 台账 reports/sys_cleanup_*.json)**: 合计 **835MB**
(apt 列表 271 + journal 287 + uv 254 + pip 11 + 日志轮转 5 + misc 7); DNS flush 后冷解析 0.00~0.03s、热解析 5/5=0.00s;
网络旋钮(bbr/fq/rmem32M/ssai=0/fastopen3)全部在效; 远端单流 4.27/4.49/5.36MB/s(中位 4.49, 与基线 4.30 同噪声带 → 不重复声明增益)。
新增 A/B 反例记录: **`tcp_tw_reuse` 关掉会慢 3.7%(3/3 轮), 但 1 vs 出厂 2 无差异 → 保持出厂不动** (见 `linux-network-perf-boot`)。
**如实结论**: 系统旋钮给不出"魔法加速"; 算力提升要走 GPU/训练口径 (batch、像素进 RAM、BLAS 后端)。
**网络旋钮单独成技能**: 开机自动优化网络性能(交错 A/B 实证 + systemd unit + 台账) → 见 `linux-network-perf-boot`。

## 7. 交付格式 (用户会拿它当结果看)
- 报告落项目 `reports/sys_maintenance_<日期>.md`: ①自检表 ②DNS/网络实测数字 ③清理明细表(每项 MB + 合计)
  ④性能(测了什么、结论、回滚了什么) ⑤保护清单复核 ⑥遗留待决项(备份件这类要人点头的)。
- 终端回复用纯文本分行, 数字在前, 结论一句话; 不写"已优化"这种没有数字的句子。

## 进度/占用口径：`ps %CPU` 是**生命周期均值**，不是现状
实测 `ps -eo pcpu` 报 100% 的推流服务，同一 PID 用 1 秒差分采样只有 **~45%**
（该值 = 累计 CPU 时间 ÷ 存活时长；跑了 9 小时的服务会把历史尖峰一直背在身上）。
⇒ 报"某进程吃满一个核"之前**必须做一次差分采样**（读 `/proc/<pid>/task/*/stat` 的 utime+stime，隔 1s 再读），
顺便就能定位是哪个线程在烧（`wchan` 能看出是 socket 轮询还是 nanosleep）；只看 `ps` 会把"9 小时均值"当"当前负载"汇报成夸大数字。

## 磁盘大象：先问再动，并且别让用户以为能腾出几十G
本机 285G 已用里真正的头是**训练缓存**，不是系统缓存：`/home/ubuntu/stable-wm-cache` ≈ **151G**
（datasets 137G + checkpoints 14G），其中单个 `datasets/cube_single_expert.h5` 就 **95G**。
它被 `INTACT-JEPA/config/train/*.yaml` 引用 ⇒ **属在用数据**，只能列清单问用户，不能自己删。
而系统层缓存（journal/apt/转储/日志轮转/用户缓存）一轮实测只能清出 **~280MB** ——
用户说"清理系统"时先把这句说清楚，别让对方以为能腾出几十G；真正的空间决策要指向大文件清单 + 用户点头。
**找大象的固定顺序**(别一上来 `du /`, 会挂): `df -h /` 看缺口 → 一级目录逐个加超时扫
`for d in /home /var /opt /usr /snap /root /srv; do timeout 90 sudo du -sh $d; done | sort -rh` →
对最大的那几个 `du -sh <dir>/* | sort -rh | head` 逐层下钻(实测 4 次下钻即定位到单个 95G 文件)。
每层都**同时查引用**: `grep -rn "<目录名>" --include=*.yaml --include=*.py <训练仓库>` ——
被训练配置引用的数据集属"在用", 只能列清单问用户, 绝不能自己删。

## 8. 关机前存档 / 交接 (用户说"保存数据, 小版本迭代, 准备关机")

**顺序固定跑, 每步留证据**:

1. **停 / 确认无在跑任务** (别在训练中途关机):
   `pgrep -af 'train|joint_train|annotate|yolo_annot'` 应为空; `nvidia-smi --query-gpu=utilization.gpu,memory.used`
   应 <10% 且显存 <1G (实测空闲 = 9% / 464MiB)。有活先停干净 (: 如 L5 编排 `--status` 确认终态再 pkill)。
2. **产物归集 (小文件入库, 权重只留清单)** —— 把运行产物快照到 `~/zmax_data/<环>/artifacts_<日期>/`:
   ⚠️ **权重文件不能直接拷** (单文件 1.29GB): 只生成 `WEIGHTS_MANIFEST.txt` =
   `md5sum + stat -c%s + 路径` 逐行; 小文件 (summary.json / *.jsonl / *.log / 配置 yaml) 才真拷。
   这样"权重在哪、哪个版本、多大"可追溯, 库里不涨一个字节。
3. **状态文件一起备份**: 编排的 `state.json` (含终态/缺口/每阶段 ok) → 快照目录。
4. **小版本迭代**: 写一份变更说明文件 → `tools/bump_version.py --to <X.Y.Z> --summary-file <f>`
   (它会改 update_checker/version_sync/docs_sync/integrity_check/VERSION.md/studio.py) → 回读 `CURRENT_VERSION` 核对。
5. **提交纪律**: `git add <显式列文件>`, **绝不用 `git add -A`** (会吸进运行态 churn + 别人的未完成改动)。
   暂存后必看 `git diff --cached --stat`, 并对每个文件核大小 (最大应 <1MB; 出现 .pt/.safetensors/视频 → 漏加了 ignore, 先修 .gitignore)。
6. **push + tag**: `git push origin main --tags` (tag 触发云端 CI 出包, 与本地关机无关, 可以放心打)。
7. **写交接报告** `reports/关机交接_<日期>.md`, 必含四块:
   ①关机前状态 (终态/缺口/产物路径/GPU 空闲) ②**开机后需手动恢复的** (自启单元里没有的手工进程 ——
   如取流服务完整命令行; 远端取流/相机/工控机接口) ③待办优先级 ④本轮代码改动清单。
   **重启后按 §9 逐项核验**；手工进程没自己起来时先读 §10（守护早退），再查服务本身。
8. **收尾核对**: `sync` → `df -h` → `git status --short` (应只剩运行态 churn) → `git log --oneline -1`。

**新增生成物顺手加 .gitignore**: 每次训练动态生成的 `config_*_lora_*.yaml`、
`reports/joint_train_*/` (内含 .pt) 这类必须显式 ignore, 否则下次 `add` 就会把权重拖进库。
临时脚本写在 `/tmp/*.sh` 再跑, 别塞巨型内联命令。

## 9. 重启后核验：链路自愈了没有（用户说「重启了 / 回来了 / 元气恢复」先跑这个）

这类话要的是**最简现状**：哪些自愈了、哪些还缺、缺在哪一层。一条命令跑完只读清点：
```bash
date; uptime
systemctl --failed --no-pager
for s in $(systemctl list-unit-files 'zmax-*' 'aoi-*' --no-pager | awk '/enabled/{print $1}'); do printf '%-28s %s\n' $s $(systemctl is-active $s); done
ss -ltnp | grep -E '8791|8793|8790|8891|8893'      # 8793=工位总览=动作授权唯一入口, 不可省
pgrep -af '<手工进程名>'                            # 自启单元管不到的手工进程(推流/采样/桥)
python3 tools/cam_dev_resolve.py                    # 相机按卡名实测解析(重启后设备号会变)
ls -l rokae_sdk/tcp_out/latest.json                 # 位姿真值(全 0/读不到=会话陈旧)
ip -br a; ping -c1 -W2 <Orin>; curl -s -o /dev/null -w '%{http_code}' http://<工控机>:10082/last_result
nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader; df -h /
```
判读口径：
- **本机链路 与 外设/网络在不在位，分两层报**：产线网卡不在位 ⇒ Orin / AOI 端口 / 珞石位姿真值**全不可达是环境缺失，不是服务故障**
  （珞石采样容器会一直 `Restarting`，属预期）。但**不许拿它当挡箭牌** —— 本机该起的服务没起，必须单独列出来说。
- **「有进程」≠「在役」**：端口没在监听就是没在服务。逐个 `ss -ltnp | grep <端口>` + 一次 HTTP 探活，双证后才敢说「起来了」。
- `systemctl is-active` 给 `activating` + 反复计数 ⇒ `journalctl -u <unit> -n 20` 看真实原因，不要因为「单元存在」就报正常。
- 汇报按「本机已起 / 本机还缺 / 外设缺失 / 资源(GPU·磁盘)」四行给，一眼能看完，不写「已恢复正常」。

## 10. 守护脚本的早退会吞掉它后面所有自愈（重启后最常中的一条）

一个守护里有多条自愈分支、又写成 `if bad: … return` 时，**排在前面的那条一坏，后面的自愈永远不执行**。
实测：`tools/cam_stream_guard.py` 的深度源分支（容器/源文件龄）直接 `return 1`，而「推流没跑就拉起」排在它后面
⇒ 深度容器早就不在时，脚本每 5 分钟都在深度分支退出，推流那一支**一次都没跑过**；表现就是重启后 8793 工位总览一直没人拉，
而 cron 日志里只看得到一行深度失败（看着像「守护在工作」）。
- **立即恢复**：跑那条**官方启动器**，不要手搓命令行 ——
  `cd /home/ubuntu/zmax_rel && bash tools/start_station_stream.sh`（它自己按卡名解析设备、抬 fd 上限、末尾复核 `8793/station → 200`）。
  手搓 `cam_live_stream.py` 会因为设备号写死串线/近黑。
- **治本**（2026-09-30 已在 `tools/cam_stream_guard.py` 落地并实测）：把每一项自愈都跑完再汇总上报
  （收集式 `notes.append(...)` 代替中途 `return`），只有全好才静默；退出码 = 有失败项才非 0。
- **守护判「环境缺失 vs 服务故障」**：先 `docker inspect -f {{.State.Status}} <容器>` 定容器状态，
  `running/exited/created` 才值得手动救；`restarting`（docker 自己正在拉起）与 `absent`（不在位）**只跳过**——
  否则每 5 分钟去 `docker exec`/`docker restart` 一遍，纯刷屏且无用（产线网卡不在位时 tap 容器
  一直在 netwait、珞石采样容器一直 crash-loop，都属预期）。
  ⚠️ **docker 新版报错是小写** `error: no such object: <name>`（实测 docker 28）——按 `"No such"` 做
  大小写敏感匹配会漏判成「查不了」→ 该跳过的自愈反而去瞎折腾。判「容器不在位」要用 `.lower()`。
- **改完必须真跑一遍故障路径**：`kill <8791 pid>` → 跑守护 → 复核 `8793/station=200` + `/stats` 帧号递增，
  这才证明「深度分支不再吃掉了推流分支」（自测开关 `--cmdline/--expect/--stats-json` 只验 judge 纯函数，验不到分支顺序）。
- **排查定式**：守护「确实每 N 分钟都在动、但目标服务就是不活」⇒ **先定位它从哪个分支返回的**，别先去怀疑被守护的服务本身。

## Pitfalls
| 坑 | 症状 | 修法 |
|---|---|---|
| 把"有进程"当"在役" | 报"服务正常"但链路其实没数据 | 逐个 `systemctl is-active` + 端口/HTTP 探活, 双证 |
| 探活脚本乱传参数 | 兜底通知脚本把 `--probe` 当**正文**发进群里 | 先 `read` 脚本用法; 别拿"发条测试消息"当探活(会污染群) |
| 清完不复核 | 删了在役权重的旁支文件 | 必扫保护清单 + `find -xtype l` 断链检查 |
| `sudo du` 挂在超大目录 | 命令超时/卡住 | 限定路径 + `timeout`, 别 `du /` 全盘 |
| 汇报 governor"提升 X%" | 单轮先 A 后 B 的顺序效应 | 交错多轮取中位; 带宽瓶颈负载不能用来测频率 |
| 顺手删备份件 | 用户其实还要那份镜像归档 | 备份/归档件**只列不删**, 让用户点头 |

> 📄 2026-09-24 完整实测数字/命令/产出路径: `references/2026-09-24-baseline.md`
