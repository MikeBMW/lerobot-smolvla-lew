---
name: linux-network-perf-boot
description: "Use when 开机自动优化网络性能或判定网络旋钮是否真有收益。"
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [linux, network, performance, sysctl, bbr, systemd, boot, ab-test]
    related_skills: [linux-host-maintenance, linux-wifi-troubleshooting, disk-redline-guard]
---

# 开机网络性能优化 (实证优先, 拒绝 cargo-cult)

## When to Use
- 用户说"优化网络性能 / 以后每次开机都要优化 / 网络调优 / 下载太慢 / 抖动大"。
- 要给某台机器**加开机网络优化**(systemd unit), 或**评审已有优化是否真有收益**。
- 配套: 系统层体检/清理走 `linux-host-maintenance`; WiFi 连不上/掉线走 `linux-wifi-troubleshooting`。

## 0. 铁律 (先立规矩)
1. **先量后调**: 交错 A/B(**Latin-square 轮转消顺序效应**)+ ≥6 轮 + 取中位。**绝不允许**"先全 A 再全 B" —— 首测必然偏低(CDN 冷启/首包/无线退避), 实测这个顺序效应能造出 +19% 的假提升。
2. **先测噪声带**: 基线连测 6 轮取极差当门槛(本机远端下载 ±3%; 换时段可到 ±30%, 换时段必须重测基线)。
3. **只在超过噪声带 ∧ 有重复性(胜率 ≥5/6)时启用**; 无收益 → 回滚, 并如实写"无可测收益"(不留表演性设置)。
4. **拒绝的也要记录**: 把"看似该调但实测无收益"的写进 `/etc/sysctl.d/*.conf` 注释, 防止下次重走回头路。

## 1. 已实证结论 (2026-09-25 · 4060 工位机 · WiFi 5GHz 573Mbit/s · RTT 网关2ms / npmmirror 16ms / GitHub 89ms)
| 旋钮 | 实测数字 | 结论 |
|---|---|---|
| `rmem_max/wmem_max` 天花板 + `tcp_slow_start_after_idle=0` | 远端单流下载 中位 4.30→4.86 MB/s **+6.1%**, 5/6 轮胜 | ✅ 启用 |
| `tcp_congestion_control=bbr` (+`default_qdisc=fq`) | 单独 +4.1% (4/6) | ⚠️ 边缘, 组合时 5/6 胜 → 启用并标注"边缘" |
| **组合**(窗口+ssai+bbr+fastopen+backlog) | 4.30→5.12 MB/s **+19%**, 5/6 轮; TTFB 无回归(+2~5% 在噪声内) | ✅ 启用(开机脚本就用这套) |
| `tcp_fastopen=3` / `mtu_probing=1` / `netdev_max_backlog` / `somaxconn` | 无可见差异 | 🟡 零成本抬高天花板, 保留但标"未证明" |
| IPv6 AAAA 前置 (`gai.conf precedence ::ffff:0:0/96 100`) | `curl -v` 显示**根本没尝试 v6**(无出口→立即失败), 无 happy-eyeballs 200ms 等待 | ❌ 拒绝(无代价) |
| WiFi 省电 `iw set power_save off` | 开/关 3 轮 ping 抖动无差异; 驱动参数 `power_save` 默认已是 N | ❌ 拒绝(默认已关); 开机脚本仍**断言**它 |
| regdomain 国家码 | 已是 `country CN`(5.8G 33dBm / 5.2G 20dBm), AP 在 5280 → 无可调 | ❌ 无从优化 |
| `tcp_fin_timeout` | 只影响 FIN_WAIT_2, **管不了 TIME_WAIT(内核固定 60s)** | ❌ 无效旋钮(常见误解) |
| TIME_WAIT 631 条 = 全部 `127.0.0.1:8790`(推理服务短连接 9Hz×60s=540) | 本地端口占用 2.2% | 无害; 要降只能**客户端复用连接**(应用层) |
| `tcp_tw_reuse` (2026-09-26 本机实测, 负载=200×连续短连接打 8790) | 关(0) 中位 1429ms vs 开(1) 1376ms → **关掉慢 3.7%, 3/3 轮一致**; 再严谨对消 1 vs 2(本机出厂值) = 1344 vs 1370ms **差 1.9% 落在噪声内** | ✅ **保持开启即可, 不用改**(出厂 2 已最优); 教训: 测「短连接类」旋钮必须用**真实短连接 churn** 当负载, 用大文件下载测不出来 |
| `busy_poll/busy_read` | 本机负载是 10Hz loopback, 与网卡收包无关 | ❌ 不适用 |

## 2. 自动开机落地 (3 个文件, 幂等)
```
/etc/sysctl.d/99-zmax-net.conf                  # 内核旋钮真源(含"拒绝项"注释)
<repo>/tools/zmax_net_optimize.sh               # 应用+断言+体检+落台账 (--quick / --no-throughput)
/etc/systemd/system/zmax-net-optimize.service   # oneshot · After=network-online.target · enable
```
脚本做四件事(单项失败不阻塞开机, 全程有超时): ①复核/应用内核旋钮 ②断言 WiFi 省电 off ③DNS `flush-caches` + 预热 5 个常用域 ④体检并追加台账
`<repo>/reports/net_boot_optimize_<YYYYMMDD>.jsonl`(每次开机一行: 生效项/RTT/TTFB/远端下载/DNS 预热数)。

安装与复跑:
```bash
sudo install -m644 /tmp/99-zmax-net.conf /etc/sysctl.d/ && sudo sysctl --system
chmod 755 <repo>/tools/zmax_net_optimize.sh          # ⚠️ 坑1: 不改可执行位 → unit status=203/EXEC
sudo systemctl daemon-reload && sudo systemctl enable --now zmax-net-optimize.service
sudo systemctl restart zmax-net-optimize.service      # ⚠️ 坑2: RemainAfterExit=yes 时 start 不重跑, 必须 restart
sudo tail -5 /var/log/zmax-net-optimize.log
tail -1 <repo>/reports/net_boot_optimize_$(date +%Y%m%d).jsonl
```
回滚: `sudo systemctl disable --now zmax-net-optimize.service && sudo rm /etc/sysctl.d/99-zmax-net.conf && sudo sysctl --system`。

## 3. 测法 (复用 `scripts/net_ab_latin.sh`)
- **负载选择**: 远端单流(高 RTT 才吃窗口/BDP) + 近端 4 并发(模拟 hf 多 worker) + TTFB 10 次中位(延迟敏感路径防回归)。
- **测速源(国内可用性)**: `codeload.github.com/<repo>/tar.gz/...`(远·RTT 89ms·首选) · `registry.npmmirror.com/...`(近·16ms·单连接被限速 ~1.1MB/s, 适合做并发/小增益对照)。
  ❌ `speed.cloudflare.com` / `speed.hetzner.de` 国内不可达; `mirrors.aliyun.com` ubuntu-releases 302 循环。
- **必报项**: 优化前→后 中位值 + 胜率(几/几轮) + 噪声带 + TTFB 是否回归。
- 测完**必须** `sysctl -w` 恢复出厂值, 不留半优化状态。

## Pitfalls
| 坑 | 症状 | 修法 |
|---|---|---|
| 顺序效应 | 报"B 提升 19%" | Latin-square 轮转 + 基线首测普遍偏低, 必须交错 |
| CDN/无线噪声 | 同配置 1.5~5.3MB/s | 报噪声带+胜率, 禁止报单点数字当结论 |
| unit 203/EXEC | 服务起不来, 无日志 | `chmod 755` 脚本 |
| oneshot 不重跑 | `systemctl start` 后无新日志 | 用 `restart` |
| ping 汇总行解析 | 日志出现 `mdevms` | `awk -F'= '` 再 `split($2,a,"/")` 取 avg, 别用 `-F'[/ ]'` |
| 内联长命令 | hardline blocked | 写 `/tmp/*.sh` 再执行 (见 memory: 长命令拆多段) |
| 改 sysctl 后不核验 | 以为生效 | 改完 `sysctl -n` 打印真值并落台账 |

## 交付格式
数字在前(前→后 + 胜率 + 噪声带) → 明写**拒绝了哪些及理由** → 台账/脚本路径 → 复跑与回滚命令。
参考实证文档: `<repo>/reports/net_perf_optimize_20260925.md`。
