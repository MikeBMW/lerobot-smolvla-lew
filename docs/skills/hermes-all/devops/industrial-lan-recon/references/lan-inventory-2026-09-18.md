# 192.168.23.0/24 产线网实测快照 (2026-09-18)

本机网卡：`enx00e04c0c32a0`(USB 千兆 RTL8153) = **192.168.23.50/24 无网关**。
枚举方式：ARP 层（见 `scripts/lan_inventory.py`）+ MAC 厂商 + TTL + 端口/banner + NBSTAT + GVCP。
**结果：6 台设备 + 本机；其余 247 个地址全空。**

| IP | MAC | 厂商 | 判据 | 是什么 |
|---|---|---|---|---|
| .50 | 00:e0:4c:0c:32:a0 | Realtek | USB 千兆 | 本机 4060 工作站 |
| .66 | 74:25:54:00:10:83 | NVIDIA | SSH `OpenSSH_8.9p1 Ubuntu` · 111 · **8000 uvicorn** · ROS/DDS | Orin 边缘机（采集侧） |
| **.23** | cc:82:7f:c9:cf:d3 | **研华 Advantech** | TTL=128 · SMB 135/139/445 · NetBIOS `DESKTOP-NV6ATND`(WORKGROUP) · 10081 Werkzeug/Flask · 1947/5040/5059/5308/48001/50001 · 49664-49871(Windows RPC) | **Windows 工控机（研华 IPC）** |
| .160 | 34:df:20:0b:45:e4 | 深圳康士达 Comstar | SSH `OpenSSH_7.2p2 Ubuntu-4ubuntu2.10` · **7777** | 珞石 XMS5-R800 控制器 |
| .203 | 3c:6d:66:a3:b2:53 | NVIDIA | SSH `OpenSSH_7.6p1 Ubuntu`(18.04) · 111 | 另一台 Jetson 边缘盒（用途待确认） |
| .2 / .8 | 00:02:c4:40:44:fd / :e0 | **OPT 奥普特** | TTL=128 · **无任何 TCP 端口** · **UDP 3956 GVCP 应答 256B** | 两台 GigE Vision 视觉设备/控制器 |

其它实测结论：
- **网关 192.168.23.1 不存在**（本机与 Orin 的 ARP 都是 INCOMPLETE；Orin 路由表里却写着 `default via 192.168.23.1`，是无效网关）。
- **192.168.23.7 空地址**（本机 + Orin 双向 ARP INCOMPLETE、ICMP 100% 丢包、无 NBSTAT 应答）→ 用户提到的 .7 工控机当前不在线。
- .2/.8 若只做 TCP 扫描会得出"没有服务"的错误结论 —— 它们是 GigE Vision 设备，只讲 UDP。

## .23 工控机的访问判定（用户给 admin/admin）

- 认证：**通过**（SMB 可列共享）→ 但共享只有 `ADMIN$ / C$ / D$ / IPC$`，**无任何用户级共享**。
- 权限：`lookupnames admin` → SID `S-1-5-21-…-1001`，**RID=1001 = 普通用户**（内置管理员是 500）
  ⇒ `C$`/`D$` 一律 `NT_STATUS_ACCESS_DENIED`；`netshareenumall` = `WERR_ACCESS_DENIED`。
- 机器上确有 `Administrator`(RID 500)，但**密码不是 admin**（`NT_STATUS_LOGON_FAILURE`，只试一次，不重试不爆破）。
- 免密入口全关：匿名 `ACCESS_DENIED`、`guest` `NT_STATUS_ACCOUNT_DISABLED`、匿名 IPC$ `ACCESS_DENIED`。
- 远程通道：**RDP(3389) / WinRM(5985) / SSH(22) / VNC(5900) 全关**，只有 SMB。
- 结论：**网络可达但取不到文件**；要拿数据须 (1) 现场建只读共享授权给该普通账号，或 (2) 给管理员账号，或 (3) 开 RDP/WinRM。

## 待办 / 后续（本轮未完成）

- 用户稍后会从该工控机启动 **FastAPI 服务，占用 10082 与 10083 两个"通道"**；
  起来后按 `industrial-lan-recon` §6 轮询器抓 `Server` 头 / `openapi.json` 路由清单 / `docs` 标题（只读，不调 POST）。
- 机上 **10081 已存在一个 Werkzeug/Flask (Python 3.12.9) 服务**，路由是自定义的（`/`、`/api`、`/status`、`/docs`、`/openapi.json` 全 404）→ 起新服务前先确认端口没撞。
- 未清点的段：本机 WiFi `10.163.146.78/23`（公司网）、Orin 的 WiFi `192.168.124.59/24`。
