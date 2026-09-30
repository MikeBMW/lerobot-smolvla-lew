---
name: zmax-ws-chat-debug
description: Use when datadrive.world 群聊/WS 无消息, 诊断 WS 服务端推送。chat.html 空。
---

# Z-MAX WS 群聊/推送诊断 (2026-08-10)

## 触发条件
- datadrive.world/chat.html 群聊没消息
- WS 连接 / orin_status 推送 / 实时通道问题

## 快速诊断步骤
1. 测 WS 握手: `curl -H 'Connection: Upgrade' -H 'Upgrade: websocket' -H 'Sec-WebSocket-Version: 13' -H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' http://datadrive.world/ws`
   - **HTTP 101** = 通道通; 426 = HTTPS WS 未配 (用 http 页面 + ws://)
2. 发 hello 看回包 (用 /tmp/ws_probe2.py 模式, 带掩码!):
   - 回 `{"type":"orin_status",...}` = **服务端只做 Orin 状态, 没群聊**
   - 回 `{"type":"history","msgs":[...]}` = 群聊正常
3. chat.html 期望: `{type:"history"}` 或 `{type:"msg"}` — 其他 type 全被忽略 → 消息区空

## 根因 (2026-08-10 实测)
- **WS 服务端只推 orin_status, 未实现群聊广播** → chat.html 永远空
- ws://datadrive.world/ws = 101 通; wss:// = 426 (nginx 未配 SSL WS 转发)
- relay 的 status 命令 20s 未消费 = Mac 守护离线 (另一独立问题)

## 修复方向 (web 侧 zmax-website)
- 服务端收 `{type:"hello"}` → 回 `{type:"history", msgs:[最近50条]}`
- 收 `{type:"msg", from, msg}` → 存库 + 广播所有连接
- 可选: 飞书群消息桥接 → WS 广播

## 坑
- WS 客户端发消息**必须掩码** (masking), 否则服务端回 opcode=8 "incorrect masking" 关连接
- 浏览器自动掩码; 脚本测必须手动 XOR mask
- 服务端→客户端回包不需要掩码
