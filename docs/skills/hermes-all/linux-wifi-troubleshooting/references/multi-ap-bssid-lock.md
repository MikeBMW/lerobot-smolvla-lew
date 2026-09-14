# 多 AP 环境 BSSID 锁 + NM 漫游行为 (2026-08-27 实测)

## 症状
- 公司/园区 WiFi(如 Corp-Guest)部署十几个 AP(2.4G/5G 各信道),信号满格却"连不上"
- 或连上几分钟就掉,机器反复在手机热点和公司网之间切换
- 用户问"为什么连不上",但 `nmcli device wifi list` 显示目标 SSID 信号 90-100

## 根因
连接配置里 `802-11-wireless.bssid` 锁死了单个 BSSID(NM 首次连接某台 AP 时记录)。
此后只认这一台 AP——它不在服务/信号差就必失败,即使同 SSID 其他 AP 信号满格。

**另有 band 锁坑 (2026-09-07 实测)**: 档案里 `802-11-wireless.band: bg` 把连接
钉死 2.4G——同名 5G AP 信号 70-79 全被禁用。症状 = "Corp-Guest 反应慢/卡"(2.4G
信道被同网几十个 AP 挤爆: ~60 AP 挤 ch1/6/11 每信道 4-6 个互抢空口 + 蓝牙/USB3
干扰; 延迟抖动大, 内核日志呈连上 4 秒即 DEAUTH_LEAVING 本地主动放弃)。查法:
`nmcli connection show "Corp-Guest" | grep -E "band|bssid"`。修复: 只清 band 即可,
bssid 本来就空:
```bash
nmcli connection modify "Corp-Guest" 802-11-wireless.band ""   # 空=自动, 5G 优先
```
改档案不影响当前已激活连接, 下次 `nmcli connection up` 才生效。注意访客网段
(Corp-Guest)出口常限速/过滤, 外网 API(LLM token 请求)慢; 手机热点直连蜂窝无此
闸 — 同机"Mike 快 Corp-Guest 慢"的常见最终解释层。

```bash
nmcli connection show "Corp-Guest" | grep bssid   # 锁死则显示 8C:79:09:1C:CA:E1 而非 --
nmcli connection modify "Corp-Guest" 802-11-wireless.bssid ""   # 解除锁(空串即清除, 一条命令)
```
解除后 `nmcli connection up <名>` 会从所有同 SSID AP 里选信号最好的。

## NM 漫游行为(易误判)
NM **不会**因为另一个 WiFi 信号更好就自动切过去——当前连接不掉线就一直赖着。
- 机器停在手机热点上、公司网满格却不切 = 正常行为,不是故障
- "连不上公司网"的观感多半是:机器根本没尝试切(NM 机制),或配置锁 BSSID
- 手动切: `nmcli connection up <公司网>`

## ⚠️ 实测连接前先确认当前连接是不是用户手动选的
用户手动切到手机热点(本地管理 MAC 02:F8:4D 开头,网段 192.168.x / 10.x 非公司网段)
说明他有意图(公司网限网/屏蔽站点,如 bilibili)。
此时 `nmcli connection up <公司网>` 实测会把机器切走 → 用户看到网络又变了会以为又出问题。
先问一句或先看日志判断激活来源,别顺手切网。切走之后要主动切回并说明。

## 公司网"上不了某站"的验证(三个层面)
用户说公司 WiFi 上不了 bilibili 等,实测:
```bash
curl -sI https://www.bilibili.com                      # 网页 → 200
curl -s  https://api.bilibili.com/x/web-interface/nav  # API → 200
curl -sI https://upos-sz-mirror08c.bilivideo.com       # 视频 CDN → HTTP 959 是 CDN 对裸请求的正常返回, 非屏蔽
```
三处都通 = 该机器实测可达;用户手边其他设备上不了是设备/时段策略问题,与本机无关。
注意:公司网关常禁 ICMP(网关 ping 不通 ≠ 断网),以 TCP 实测为准。

## 本案例时间线(Z-MAX 4060 总工机)
- ~07:17 前: 连 Corp-Guest(BSSID E1, 10.163.148.6 公司网段)
- 07:17: 切 F22_2993(手机热点, 02:F8:4D 本地管理 MAC, 192.168.58.141) — 用户手动
- 14:43: NM 自动激活 Corp-Guest(priority 10 > F22 的 0), 又切回
- 用户再次手动切回热点(公司网上不了 bilibili)
- 修复: 解除 Corp-Guest BSSID 锁 → 以后自动连时挑信号最好的 AP(5G CH64 F1 信号 99)
