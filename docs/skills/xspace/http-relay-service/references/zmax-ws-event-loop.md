# Z-MAX WS 事件驱动闭环 · 实现细节 (2026-08-03 实测)

老倪场景: 静静(笔记本)总关机 / ECS(服务器)常驻 / 小芳(Mac+Orin)有时关机 / 演示要零等待。
结论: **WS 用于事件(data_arrived), HTTP 轮询用于状态(队列空? latest?)** — 事件型低延迟走 WS, 状态型自愈走轮询兜底。

## 三端架构

```
小芳 Orin 采集 → Mac(192.168.23.1:8769) → ECS relay(zmax_relay.py :39053)
                                            │  upload 成功后
                                            ▼
                                    本地 socket notify(:8766)
                                            ▼
                                    ws_relay.py (:8765 hub)
                                            │  广播 data_arrived
                                            ▼
                        静静 auto_loop.py v2 (WS订阅 → 立即训练)
                        (60s HTTP 轮询兜底 + 启动时拉一次全量)
```

## 1. ECS ws_relay.py v2 (:8765 hub + :8766 本地通知口)

- `websockets.serve(handler, "0.0.0.0", 8765)` 广播 hub (原功能: Orin 心跳 → `orin_status`)
- 新增 `asyncio.start_server(notify_server, "127.0.0.1", 8766)` — 本地 TCP 通知口
- notify_server: 收 `notify <latest> <frames>` 行 → `broadcast({"type":"data_arrived","latest":...,"frames":N,"ts":...})`
- 新客户端接入即推 `{"type":"orin_status", **ORIN_STATE}` (打开即有数据)
- `asyncio.gather(notify_srv.serve_forever(), asyncio.Future())` 双服务并存

## 2. ECS zmax_relay.py — 三处改动

1. **notify_data_arrived(name, frames)** 模块函数: `socket.create_connection(("127.0.0.1",8766), timeout=2)` 发 `notify {name} {frames}`; try/except 包住, ws_relay 不在线不阻塞上传。
2. **/upload 成功分支 (JSON 和二进制两处)** 调 notify_data_arrived()。
3. **GET/POST /command 采集指令端点**: `COMMAND_FILE = Path("/root/zmax-relay/command.json")`; GET 读文件返回 `{"cmd":"collect","ts":...}` (默认 collect), POST 写指令。用途: 4060 主动下发采集指令给 Mac 守护 → 4060→ECS→Mac→Orin 反向指令链路。公网 = `https://datadrive.world/api/relay/command`。

⚠️ **/status latest 排序坑**: `sorted(glob(...))` 按文件名排序 → `pkg_20260803_205315.npz` > `demo_ws_test.json` 字典序, 新 JSON 包永远被旧 npz 压住 → 消费者永远看到 npz (frames=?) 不处理。修: `sorted(..., key=os.path.getmtime)`。

⚠️ **二进制包无帧数坑**: 二进制分支 meta 只有 `{"binary":..., "size":...}`, 无 frames 键 → 消费者 `frames >= 20` 阈值逻辑 sees `frames="?"` 永不触发, 二进制数据静默不训练 (日志反复 "📥 新数据: xxx.npz | frames=?")。JSON 包才有 meta.frames。二进制生产者需带帧数 (side-channel/文件名/伴生 JSON), 或消费者自己解析 npz。

⚠️ **远程补丁吞函数头坑**: 用 `def enforce_buf_limit():` (含 docstring) 作锚点插入新函数时, 若 new_string 只含 def 行不含 docstring, 旧 docstring+函数体悬挂在新函数内 → `enforce_buf_limit` UNDEFINED → /upload 400 `name 'enforce_buf_limit' is not defined`。规则: 锚点必须含完整 def 行; patch 后 `ast.parse` + 真实端点测试 (小 JSON 上传), 不只语法检查; 先 `cp app.py app.py.bak_$(date +%s)`。

## 3. 笔记本 auto_loop.py v2 (WS 事件驱动 + 轮询兜底)

依赖: `pip3 install --break-system-packages websocket-client` (1.9.0)。

```python
def ws_listener():            # daemon 线程
    while True:
        try:
            ws = websocket.WebSocketApp(WS_URL,
                on_message=lambda w,m: ws_on_message(m),
                on_error=..., on_close=...)
            ws.run_forever()  # 阻塞到断开; 外层 while = 重连循环
        except Exception as ex: log(...)
        time.sleep(5)         # 重连间隔

def ws_on_message(raw):
    d = json.loads(raw)
    if d.get("type") == "data_arrived":
        threading.Thread(target=process_new_data, daemon=True).start()  # 不阻塞接收

def main():
    threading.Thread(target=ws_listener, daemon=True).start()
    while True:
        process_new_data()    # 轮询兜底 (WS 错过事件补拉)
        time.sleep(60)
```

- `process_new_data()` 抽成独立函数 (WS 线程和轮询循环共用): check_new_data → SEEN 去重 → frames≥20 → LOCK 防并发 → pull → 落地 orin_live → build_dataset → train → upload。
- **引导钩子同理 (zmax-console 教训)**: 状态推进/动作触发必须绑"实际生效" (worker 启动/数据落盘), 不能绑点击入口。

## 4. 验证 (2026-08-03 全部实测通过)

1. 上传 25 帧 JSON 测试包 → 守护日志 ~1s 内出现 `⚡⚡ [WS事件] 数据到达: demo_v2_test.json | 25帧 → 立即处理` (非 60s)
2. 后续自动: `📥 新数据 → ⚡ 数据量达标 → 💾 已存 → 🏋️ 开始训练 → ✅ 训练完成 → 🚀 模型已推回 ECS` (零等待全链)
3. WS 断开自愈: relay 重启 → 守护 ~5s 自动重连 (on_error/on_close → sleep(5) → run_forever)
4. relay 重启模式: `pkill -f '[z]max_relay'` 单条 ssh 可行; **pkill+启动同条 ssh 命令必 exit 255** (pkill 匹配到自己 bash -c 命令行里的 `python3 zmax_relay.py`) → 用 restart.sh 放 ECS 上 `bash restart.sh`

## 5. 遗留缺口 (下次迭代)

- auto_loop 训练完**没有自动基线对比** (auto_iterate 那套在 GUI 里, 守护端没接) — 老倪问过要不要加"无提升自动调参重训"
- Mac 端 zmax_auto_collector.py BACKEND 仍是旧地址 `http://106.75.239.80:50053` (非本 ECS) — 需小芳更新指向 `https://datadrive.world/api/relay` 才能收到 /command 采集指令
