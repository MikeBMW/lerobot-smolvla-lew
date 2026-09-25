# 本机网络体检 + DNS 清理 (2026-09-25 08:00 CST · 开机 19min)

> 按技能 `linux-host-maintenance` §2/§3 口径: 只做有证据的事, 每个动作报数字。
> 脚本落盘: `/tmp/dns_probe.sh`(清前) · `/tmp/dns_clean.sh`(清理+对照) · `/tmp/net_deep.sh`(网络体检) · `/tmp/tw_owner.sh`(TIME_WAIT 归因)

## ① 网络体检结论 (一句话)
链路**全绿**: 网关/DNS/公网/产线设备 0% 丢包、延迟正常; 两个外部问题 —— **datadrive.world/ws 502 (服务端 WS 进程没起)** + **IPv6 无出口但 DNS 先返 AAAA**(隐患, 未改动)。

## ② 链路实测
| 项 | 数字 | 判读 |
|---|---|---|
| 默认路由 | WiFi `wlp0s20f3` 10.163.146.78/23 → 10.163.147.254 (metric 600) | — |
| WiFi 协商 | SSID `Corp-Office` · 5280MHz(5G) · signal **-59dBm** · tx **573.5 Mbit/s** HE-MCS11 HE-NSS2 · rx 516 | 满速档(-59 比 09-24 的 -42 弱, 仍属好) |
| 网关 30 包 | 0% loss · 1.32/2.24/5.85ms | ✓ |
| 上游 DNS 10.160.0.68 30 包 | 0% loss · 1.24/1.96/5.10ms | ✓ |
| 公网 1.1.1.1 / 223.5.5.5 | 2.49 / 14.64ms | ✓ |
| 工控机 192.168.23.23 20 包 | 0% loss · 0.54/1.09/1.62ms | ✓ 产线口 192.168.23.50/24 |
| Orin 192.168.23.66 | 0.32ms | ✓ |
| 握手分解 | feishu dns 5ms/conn 14ms/tls 27ms · github 11/99/195ms · datadrive 2.5/39/84ms · npmmirror 24/39/63ms | 全正常 |
| 连接 | 建立 93 · TIME_WAIT 631 | 见 ④ |

## ③ DNS 清理 (核心动作)
| 阶段 | 数字 |
|---|---|
| 清前 | 缓存条目 **127** · Current Cache Size 29 · 命中/未中 180/229 · Total Transactions 1310 |
| 动作 | `sudo resolvectl flush-caches` ✅ |
| 冷解析(清后首次=上游真延迟) | baidu 0.00s(A/AAAA) · feishu 0.02s · github 0.01s · npmmirror 0.02s · datadrive 0.00s · pypi 0.00s |
| 热解析(紧接第二次=缓存命中) | 6/6 全部 **0.00s** |
| 清后 | 缓存条目 **40** · Cache Size 14 · 未中 259 |
| 解析链复核 | `127.0.0.53` → 上游 **10.160.0.68 / 10.160.0.67** (search `innolight.suzhou`) · 两个上游均直查应答正常 |

**顺手核对, 无需清理**: `/etc/hosts` 无陈旧条目(只有标准 localhost 行) · `/etc/resolv.conf` 正常(127.0.0.53 + edns0 trust-ad) · nsswitch `hosts: files mdns4_minimal [NOTFOUND=return] dns` 正常。

## ④ TIME_WAIT 631 条归因 (不是故障, 有账)
- 全部是 **`127.0.0.1:8790`**(状态空间推理服务)服务端 TIME_WAIT —— 客户端每帧一条 HTTP 短连接后关闭。
- 实测 8790 推理 **9 Hz**(10s 窗口 10350→10448), 理论稳态 = 9×60s = **540**, 实测 631(含其他客户)。
- 端口余量: `ip_local_port_range 32768-60999` = 28232 个, 占用 **2.2%** · `tcp_fin_timeout 60s`。
- 结论: **当前无害, 不构成端口耗尽**; 若要降, 改在 ss_bypass/客户端侧复用连接(keep-alive), 属链路优化不属网络故障。

## ⑤ 外部故障 (本机不可修)
- `https://datadrive.world/` 首页 **200**(nginx 正常), `https://datadrive.world/ws` 握手 **502 Bad Gateway** → **上游 WS 服务进程没起**(nginx 反代不到)。
- 影响: studio / auto_loop 每 5s 重连失败刷日志, 群聊/网页实时消息不通。
- 待办: 到 ECS(39.102.211.79) 重启 WS 后端服务(需用户点头, 属远端破坏性操作)。

## ⑥ IPv6 隐患 (未改动, 待决)
- 无 IPv6 默认路由, `curl -6` 失败; 但 DNS 对 baidu/npmmirror/pypi 先返回 **AAAA**。
- 影响面: 少数先试 v6 的库会先失败一次再回落 v4(本机测试 curl/git 均无可见拖慢, `curl -4` google connect 62ms)。
- 可选处置: ①在 systemd-resolved 关闭 AAAA 查询(`DenyList`/`DNSStubListener` 级) ②放行 v6。**未验证收益前不动**。

## ⑦ 可选清理量 (只估, 未删)
| 目标 | 用量 |
|---|---|
| journal | 309.9M(技能口径可压到 200M) |
| apt archives | 32K(已干净) |
| pip/uv 缓存 | 12K(已干净) |
| 回收站 | 12K |
→ 本机当前**没什么可清的**; 大头是 journal 110M, 磁盘 102G 可用/红线 300G 尚远。

## ⑧ 保护清单复核
- 未动任何服务(ss-local-infer / ss-bypass / ss-remote-tap / ss-yolo-bypass / l2_daemon 全 running, 已 `systemctl is-active` 双证)。
- 未删任何文件(本次只有 `resolvectl flush-caches` 一条状态变更)。
- 训练数据盘 / 模型缓存 / 在役仓库 / 在役权重均未触碰。
