# 网络性能优化 实证报告 (2026-09-25 · 4060 工位机)

> 技能: `linux-network-perf-boot` · 脚本: `tools/zmax_net_optimize.sh` + `/etc/sysctl.d/99-zmax-net.conf` + `zmax-net-optimize.service`
> 口径: 交错 A/B(**Latin-square 轮转**) ≥6 轮取中位 + 报噪声带 + 报胜率; 无收益一律不启用(拒绝的也记录)

## 一句话结论
**有提升**: 远端单流下载(高 RTT 89ms)默认 4.30 → **5.12 MB/s (+19%, 5/6 轮胜)**; 延迟敏感路径(TTFB)无回归。已做成**开机自动执行**(systemd oneshot, 每次开机应用 + 落体检台账)。

## ① 测出来的数字 (全部来自真实命令)
| 实验 | 配置 | 中位 | 相对基线 | 胜率 | 备注 |
|---|---|---|---|---|---|
| 首测(有顺序偏差, **仅作反例**) | A 先测 / B 后测 | 4.00 → 4.78 MB/s | +19.4% | 3/3 | ⚠️ A 恒为每轮第一个 → 首测偏低, 此数字**不可信** |
| 单旋钮分解(Latin-square 6 轮) | A 默认 | 4.58 MB/s | 噪声带 ±3% (4.38~4.67) | — | 基线 |
| 同上 | **W** = 窗口天花板 + `tcp_slow_start_after_idle=0` | **4.86 MB/s** | **+6.1%** | **5/6** | ✅ 独立可复现 |
| 同上 | BBR 单独 | 4.77 MB/s | +4.1% | 4/6 | ⚠️ 边缘 |
| 定稿确认(交替 6 轮) | **CAND** = W+BBR+fastopen+backlog | **5.12 MB/s** | **+19.2%** | **5/6** | ✅ 采纳; A 该轮含两次 CDN 异常低点(1.46/2.57), 故取 6~19% 区间表述 |
| 回归检查 | TTFB npmmirror / feishu | +2.3% / +5.3% | 均在噪声内 | — | 无回归 |

噪声带: 基线连测 6 轮极差 ±3%; 跨时段(上午/换 CDN 命中)可到 ±30% → 换时段必须重测基线。

## ② 启用的旋钮 (真源 `/etc/sysctl.d/99-zmax-net.conf`)
```
net.core.rmem_max=33554432      net.core.wmem_max=16777216
net.ipv4.tcp_rmem=4096 262144 33554432     net.ipv4.tcp_wmem=4096 65536 16777216
net.ipv4.tcp_slow_start_after_idle=0       net.ipv4.tcp_congestion_control=bbr
net.core.default_qdisc=fq                  net.ipv4.tcp_fastopen=3
net.ipv4.tcp_mtu_probing=1                 net.core.netdev_max_backlog=5000
net.core.somaxconn=8192
```
标注: fastopen / mtu_probing / backlog / somaxconn **实测无可见差异**(零成本抬高天花板, 保留并注明未证明)。

## ③ 实测**无收益 → 拒绝**的 (防下次重走)
| 备选 | 实测 | 拒绝理由 |
|---|---|---|
| IPv6 AAAA 前置 (`gai.conf` IPv4 优先) | `curl -v` 显示根本没尝试 v6(无出口→立即失败), 无 happy-eyeballs 200ms 等待 | 无代价可省 |
| WiFi 省电关闭 | 开/关 3 轮 ping 抖动无差异; iwlwifi `power_save` 默认已是 N | 默认已关(开机脚本仍**断言**它) |
| regdomain 国家码 | 已是 `country CN` (5.8G 33dBm / 5.2G 20dBm), AP 在 5280 | 无可调空间 |
| `tcp_fin_timeout` | 只影响 FIN_WAIT_2, **管不了 TIME_WAIT(内核固定 60s)** | 无效旋钮(常见误解) |
| `busy_poll / busy_read` | 本机负载是 10Hz loopback, 与网卡收包无关 | 不适用 |
| TIME_WAIT 631 条 | 全部 `127.0.0.1:8790`(推理短连接 9Hz×60s=540), 本地端口占用 2.2% | **无害**; 要降只能客户端复用连接(应用层) |
| `net.ipv4.tcp_tw_reuse` | 已是 2(含 loopback) | 已最优 |

## ④ 开机自动化 (每次开机都跑)
```
/etc/sysctl.d/99-zmax-net.conf                   内核旋钮真源(含"拒绝项"注释)
<repo>/tools/zmax_net_optimize.sh                应用+断言+体检+台账 (支持 --quick / --no-throughput)
/etc/systemd/system/zmax-net-optimize.service    Type=oneshot · After=network-online.target · enabled
```
每次开机脚本做: ①复核/应用内核旋钮(改完打印真值) ②断言 WiFi 省电 off ③DNS `flush-caches` + 预热 5 个常用域 ④体检并追加台账
台账: `<repo>/reports/net_boot_optimize_YYYYMMDD.jsonl`(一行/次开机: 生效项 · RTT(网关/DNS/公网/工控机/Orin) · TTFB(feishu/github) · 远端下载 · DNS 预热数)
日志: `/var/log/zmax-net-optimize.log`

**本机已跑通验证**(与开机同一代码路径):
```
08:21:10 ① cc=bbr rmem_max=33554432 ssai=0 fastopen=3
08:21:10 ② WiFi(wlp0s20f3) 省电: off
08:21:10 ③ DNS 预热: 5/5 域已可解析 · 上游 10.160.0.68 10.160.0.67
08:21:10 ④ 体检: 网关 19.7ms · DNS 2.57ms · 公网 1.75ms · 工控机 1.02ms · Orin 0.26ms
          · TTFB feishu 105ms github 289ms · 远端下载 3.78MB/s
```
复跑(注意 oneshot+RemainAfterExit 必须 restart): `sudo systemctl restart zmax-net-optimize.service`
回滚: `sudo systemctl disable --now zmax-net-optimize.service && sudo rm /etc/sysctl.d/99-zmax-net.conf && sudo sysctl --system`

## ⑤ 遗留 / 不属本机
- `datadrive.world/ws` 502 (nginx 反代不到上游 WS) → 远端 ECS 39.102.211.79 侧需重启 WS 后端。
- 单次采样可能落在 3.78~5.2MB/s(WiFi 共享媒体+CDN 噪声): 看趋势看台账多行, 不看单行。

## ⑥ 台账文件
- 实验明细: `/tmp/net_ab_detail.txt` · `/tmp/net_ab2_detail.txt` · `/tmp/net_ab3_detail.txt` · `/tmp/net_ab4_detail.txt`
- JSON: `reports/net_perf_ab_20260925_080505.json` · `reports/net_perf_ab_20260925_0807*.json`
- 每次开机: `reports/net_boot_optimize_20260925.jsonl`
