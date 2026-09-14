# 公司网络 "agent 卡死, 只有热点好使" — 诊断流程 (2026-09-08 corp guest 实锤)

## 背景
用户机器 (公司笔记本 Ubuntu) 反复出现: 切公司 Corp-Guest 后 agent/Hermes "卡死没反映",
切手机热点 (Mike) 立即恢复。用户记忆 "你之前不是说 2.4GHz 有问题么" — 旧诊断 (09-07:
"2.4G 频段锁死+信道拥挤") 只是当时一半真相, 09-08 数据推翻频段论。本文是完整判定法。

## 关键结论 (2026-09-08 实锤)
- 根因 = **公司出口到海外 LLM API (api.deepseek.com) 高峰劣化**, 与无线频段无关:
  同 corp guest, 2.4G (2412MHz) 夜间 deepseek 零超时; 5G (5320MHz) 早高峰 06:00 起
  14 次 ConnectTimeout。无线链路没变, 变的是时间 (公司上班高峰) 和出口。
- corp guest 下国内全通 (baidu 200 / open.feishu.cn 404=通 / github 200), 唯独海外 API 超时。
- 手机热点直连不受公司出口影响 → 任何时候稳。**白天热点, 夜间 corp guest 出口通常恢复**。

## 判定流程 (全日志, 无需用户配合)
1. **先查是否整机关机** — "没反映" 可能机器关机/重启, 不是网:
   - `last reboot` 看运行段
   - journalctl 找关机风暴: 同一秒大量 "Deactivated successfully" + gateway 日志
     `Shutdown context: signal=SIGTERM under_systemd=yes`
   - `ps aux | grep -i hermes` 看 gateway 启动时间 vs 用户抱怨时刻
2. **归因频段/AP** (区分无线 vs 出口):
   - journalctl wpa_supplicant: `Trying to associate with xx (SSID='X' freq=NNNN MHz)`
   - 2412/2422≈2.4G, 5320≈5G; 按每次开机/切换时刻查实际连的 AP
   - corp guest 13+ BSSID 企业 AP, NM 每次自由选 (2.4G 或 5G), 不锁 bssid
3. **归因出口** (海外 vs 国内):
   - `~/.hermes/logs/errors.log` 可能是 binary → **`grep -a`**
   - `grep -aE 'APITimeoutError|ConnectTimeout|API call failed' errors.log | grep -aoE '^2026-..-.. ..:..' | cut -c1-13 | uniq -c | sort` 按小时分布
   - 对照该时段网络归属 (journalctl 时间线), 找出超时爆发时刻
4. **实测 (切过去)**:
   - `nmcli connection up 'Corp-Guest'`; 连上后 curl 多测:
     `timeout 8 curl -s -o /dev/null -w '%{http_code} %{time_total}s' https://api.deepseek.com`
   - ⚠️ **首连 8s 超时 ≠ 稳定封锁** — 实测 corp guest 下第一次 curl TIMEOUT, 紧接着 3 次全
     401 0.2s。抖动性劣化, 必须多次采样才下结论
   - 测完**主动切回热点** (用户可能不在), 再汇报
5. **NM 陷阱**: 重启后 corp guest autoconnect=yes priority=10 也可能不触发 → 手动 up。
   切换 corp guest 但日志无 Activation 记录 = 用户点了没成功, 别假设已切。

## 机器侧排障顺序要点
- 事件时间戳以 journalctl 系统时间为准; 会话消息时间戳可能带 gateway 时钟偏移 (+8h 曾出现)。
- errors.log 行分布要先过滤错误类型 (APITimeoutError 等), 别把全部日志行当超时统计。
