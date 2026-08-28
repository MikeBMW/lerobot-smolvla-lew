# WebSocket 状态中转 · Z-MAX 实测 (2026-08-02)

链路: Orin 推理服务 --WS长连 wss://datadrive.world/ws--> ECS :8765 广播 --> 控制台 GUI 订阅

## ECS 端 ws_relay.py (websockets 库 16.1.1 已装)
- 监听 0.0.0.0:8765；`clients` set 保存订阅者；`ORIN_STATE` dict 存最新状态。
- handler: 新客户端接入先发初始状态 `{"type":"orin_status", **ORIN_STATE}`；收到 `{"type":"heartbeat", ...}` 则更新 ORIN_STATE + broadcast 所有客户端。
- broadcast 用 `json.dumps({"type":"orin_status", **state}, ensure_ascii=False)`。
- 启动: `bash /root/zmax-relay/start_ws.sh` (setsid nohup，模板同 relay start.sh)。
- nginx `/ws` location 早已存在 (proxy_pass 127.0.0.1:8765 + Upgrade 头) — 无需新配置，`wss://datadrive.world/ws` 直接可用。

## Orin 端 orin_infer_service.py (WS 主 + HTTP 兜底)
- `heartbeat_loop()`: asyncio 里 `websockets.connect(WS_URL)`，连接后每 5s send heartbeat JSON；断开/异常 sleep 5 重连。
- `http_fallback()`: 独立线程每 10s POST `/api/relay/orin/heartbeat` (WS 不可用时兜底)。
- 启动时 `try: import websockets` → 有则起 WS 线程，无则打印 "降级 HTTP 心跳" — 双保险不阻塞。
- 本地/Orin 无 websockets 库时自动降级，不影响链路。

## 踩过的坑 (路径别名)
- 小芳侧脚本心跳发 `POST /api/orin/heartbeat` (无 /relay 段)，nginx `/api/orin/` location 反代剥前缀后到服务是 `/heartbeat`；服务端必须同时接受 `/orin/heartbeat` 和 `/heartbeat` (`if path in (...)`）。
- 新加 `/api/orin/` location 后 `/api/orin/status` 会撞上裸 `/status` (返回队列状态而非 orin 状态) — 控制台读取务必用 `/api/relay/orin/status`。

## 验证 (本地 venv 需先 `uv pip install --python .venv/bin/python websockets`)
1. 订阅端 connect → 收到初始状态 (online:false 或上次值)
2. 发布端 connect → send heartbeat → 订阅端 5s 内收到广播
3. 断言广播 JSON 含 `type: orin_status` + `last_seen` 已刷新
