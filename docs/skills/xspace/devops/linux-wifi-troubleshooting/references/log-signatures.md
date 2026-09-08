# 各根因对应的精确日志签名

（案例：Ubuntu 24.04 + Intel Wi-Fi 6E AX211 [8086:7a70]，移动光猫 5G SSID 在信道 48）

## 1. regulatory 国家码 00 → 5G 认证超时

内核日志（`journalctl -k`）反复出现，AP 完全不回应 auth 帧：

```
wlp0s20f3: authenticate with 84:53:cd:9b:25:e8 (local address=30:e3:a4:79:f7:66)
wlp0s20f3: send auth to 84:53:cd:9b:25:e8 (try 1/3)
wlp0s20f3: send auth to 84:53:cd:9b:25:e8 (try 2/3)
wlp0s20f3: send auth to 84:53:cd:9b:25:e8 (try 3/3)
wlp0s20f3: authentication with 84:53:cd:9b:25:e8 timed out
```

NetworkManager 侧对应：

```
device (wlp0s20f3): supplicant interface state: inactive -> authenticating
device (wlp0s20f3): supplicant interface state: authenticating -> disconnected
<warn> device (wlp0s20f3): Activation: failed for connection 'CMCC-wzvc-5G'
```

判定：发 auth 帧 AP 无响应 = 发射被 regulatory 禁止（no-IR），不是密码错（密码错会走到 4way_handshake 失败，不会 auth timeout）。

## 2. Intel self-managed regulatory（LARI）

`iw reg get` 输出，global 已设 CN 但 phy 仍是 00：

```
global
country CN: DFS-FCC
    (5725 - 5850 @ 80), (N/A, 33), (N/A)      # 149-165 已可用

phy#0 (self-managed)
country 00: DFS-UNSET
    (5230 - 5250 @ 160), ..., PASSIVE-SCAN     # 信道 48 仍 PASSIVE-SCAN
```

关键：`phy#0 (self-managed)` 是 Intel LARI 模式，固件自管 regulatory。global CN 仍会改变实际发射行为（主动扫描立刻能扫到之前扫不到的 AP），但需重启 NetworkManager 让 wpa_supplicant 重新扫描。连上 AP 后固件会从 AP 的 country IE 学到 CN，`phy#0` 的 country 会从 00 变 CN。

## 3. 省电模式主动断连

```
wlp0s20f3: Connection to AP 84:53:cd:9b:25:e8 lost
wpa_supplicant[2962]: wlp0s20f3: CTRL-EVENT-DISCONNECTED bssid=84:53:cd:9b:25:e8 reason=4 locally_generated=1
```

判定：`locally_generated=1` = 网卡本地主动断开（省电/信号放弃），不是 AP 踢。`reason=4` = inactivity/disassoc。修复 = 关 power_save。对照：`locally_generated=0` 才是 AP 主动踢的。

## 4. 假连接（association 在，数据层已废）

```
# ping 网关：丢包 10%~78%，延迟飙到秒级
100 packets transmitted, 22 received, 78% packet loss
rtt min/avg/max/mdev = 1.407/485.686/1912.339/514.144 ms

# station dump 仍显示已关联、beacon 正常
signal: -53 [-53] dBm
beacon loss: 0
tx retries: 205        # 重传高 = 信号质量差
```

判定：`nmcli` 显示 activated 但 ping 丢包严重 = 假连接。根因是 5G 信号边缘（-53 dBm），Linux iwlwifi 弱信号处理差。关省电/降频宽/disable_11ax/disable_11ac 均无效，物理限制，换 2.4G 或挪位置。

## 5. `iwlist channel` 缺 149-165 信道

```
Channel 140 : 5.7 GHz      # 到这里就断了
Current Frequency:2.457 GHz (Channel 10)
# 没有 149/153/157/161/165
```

判定：regulatory country=00 下 U-NII-3 (149-165) 被限制。`iw reg set CN` 后 `iwlist channel` 应列出 149-165，`iw reg get` 里出现 `(5725 - 5850 @ 80)`。

## 6. NetworkManager "找不到网络"（但主动扫描能扫到）

```
Error: Connection activation failed: The Wi-Fi network could not be found
Hint: use 'journalctl -xe NM_CONNECTION=... + NM_DEVICE=wlp0s20f3'
```

判定：nmcli 的扫描缓存里没有该 SSID（被动扫描没扫到弱 beacon）。`sudo iw dev <iface> scan`（主动）能扫到。重启 NetworkManager 后用新 regulatory 重新扫描即可解决。
