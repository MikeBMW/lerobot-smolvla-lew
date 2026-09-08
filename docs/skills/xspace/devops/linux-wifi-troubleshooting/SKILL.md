---
name: linux-wifi-troubleshooting
description: Use when Linux WiFi 连不上/掉线/只能连热点. 诊断国家码/省电/Intel驱动/信号.
---

# Linux WiFi 故障诊断

适用于：WiFi 连不上、连上就掉线、只能连手机热点不能连家里 WiFi、5G 频段扫不到、同一台电脑 Windows 能连 Linux 不能。

## 核心诊断顺序（按此排查，每步都有明确命令）

1. **网卡/驱动是否正常**
   ```bash
   ip -br link                      # 看 wlp* 是否 UP
   lspci | grep -iE "network|wifi"   # 网卡型号
   lsmod | grep -iE "iwlwifi|rtl|ath|brcm|mt76|rtw|cfg80211|mac80211"
   rfkill list                      # 看 Soft/Hard blocked
   ```
2. **能否扫描到目标网络**
   ```bash
   nmcli device wifi rescan && sleep 4
   nmcli -f SSID,BSSID,CHAN,FREQ,SIGNAL,SECURITY device wifi list
   ```
3. **当前连接与网关**
   ```bash
   nmcli -t -f NAME,DEVICE,TYPE,STATE connection show --active
   ip route | grep default
   ```
4. **掉线/失败日志（关键！）**
   ```bash
   journalctl -k --no-pager -n 200 | grep -iE "iwlwifi|wlp|deauth|disassoc|beacon|lost|timeout|assoc"
   journalctl -u NetworkManager --no-pager -n 200 | grep -iE "supplicant|Activation|reason"
   ```

## 根因 → 修复对照表

| 症状 / 日志特征 | 根因 | 修复 |
|---|---|---|
| `authentication with xx:xx timed out`（发 auth 3 次 AP 不回应） | regulatory 国家码 = 00 (world)，5G 信道 no-IR 禁止发射 | `sudo iw reg set CN` + 持久化 |
| `nmcli` 报 "The Wi-Fi network could not be found" 但主动扫描能找到 | wpa_supplicant 用旧 regulatory 被动扫描扫不到弱信号 | 重启 NetworkManager 重新初始化 |
| `CTRL-EVENT-DISCONNECTED reason=4 locally_generated=1` | 网卡省电模式主动断连（不是 AP 踢的） | 关 power_save |
| 能连上但 ping 丢包严重(>10%)、延迟飙到秒级 | 5G 信号边缘(-53dBm 左右)，物理限制 | 换 2.4G 或挪位置，软件无解 |

## 关键修复命令

**regulatory 国家码（最常见根因）**
```bash
sudo apt install -y iw                # iw 可能未装
sudo iw reg get                       # 看到 country 00 = world = 没设
sudo iw reg set CN
# 持久化：systemd oneshot 服务，启动时执行 iw reg set CN
sudo tee /etc/systemd/system/wifi-regdom-cn.service <<'EOF'
[Unit]
Description=Set WiFi regulatory domain to CN
After=multi-user.target
[Service]
Type=oneshot
ExecStart=/sbin/iw reg set CN
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload && sudo systemctl enable wifi-regdom-cn.service
```
设完 CN 后必须 **重启 NetworkManager**（`sudo systemctl restart NetworkManager`）让 wpa_supplicant 用新 regulatory 重新扫描，否则仍报"找不到网络"。

**省电模式（连上就掉线）**
```bash
sudo iw dev <iface> set power_save off   # 立即生效
sudo tee /etc/NetworkManager/conf.d/wifi-powersave.conf <<'EOF'
[connection]
wifi.powersave = 2
EOF
```

## 关键陷阱

- **Intel CNVi / AX211 是 "self-managed" regulatory（LARI）**：`iw reg set CN` 后 `iw reg get` 里 global 变 CN 但 `phy#0 (self-managed)` 仍显示 country 00。固件自己管 regulatory，但 global CN 仍会改变实际发射行为；固件连上 AP 后会从 AP 的 country IE 学到 CN。设 CN 后务必重启 NM 让扫描生效。
- **主动 vs 被动扫描**：`iw dev <iface> scan` 是主动扫描（发 probe），`nmcli device wifi list` 可能用被动扫描。弱 5G 信号下被动扫描扫不到 beacon，主动扫描能扫到——用这个区分"信号真没了" vs "regulatory 限制扫描"。
- **`iwlist channel` 的 5G 列表只到 140（缺 149-165）** = regulatory 没设对。中国移动 5G 光猫默认在 149-165（U-NII-3），country 00 下这些信道是 PASSIVE-SCAN，只能听不能主动连。
- **别把邻居的 AP 当成用户的**：同批次光猫 MAC 相邻（...E7 和 ...E8 只差一位但可能是两台设备）。连之前必须跟用户确认 SSID，别看到 MAC 接近就假定是同一台。
- **`wpa_supplicant` 日志 `reason=4 locally_generated=1`** 是网卡本地主动断开（省电/信号放弃），`locally_generated=0` 才是 AP 踢的——方向不同，修复完全不同。
- **信号物理限制**：-53 dBm 的 5G 在 Linux iwlwifi 下会丢包 10%~78%（驱动弱信号处理不如 Windows），关省电/降频宽/禁用 11ax/11ac 都救不了。这是物理问题，只能换 2.4G 或挪位置，不要无限折腾驱动参数。

## 验证

修复后必须实测，别只看"已连接"（可能是假连接）：
```bash
ping -c 60 -i 1 <网关IP>          # 丢包应 <5%，延迟稳定
sudo iw dev <iface> station dump | grep -iE "signal|tx retries|tx failed"
```

## 参考文件
- `references/log-signatures.md` — 各根因对应的精确内核/wpa_supplicant 日志签名。
