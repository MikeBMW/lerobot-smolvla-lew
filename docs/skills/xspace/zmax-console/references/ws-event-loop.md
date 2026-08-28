# WS 事件驱动数据闭环 (2026-08-03, 演示零等待)

老倪需求演进: "为什么不用websocket长连接?" → "websocket不可靠么?" → 最终场景: 静静是笔记本总关机, ECS 常驻, 小芳有时关机; **演示时三端在线且不希望等待**。
结论: **事件型用 WS 推送 (数据到达即触发), 状态型用 HTTP 轮询 (幂等自愈), 配合启动全量拉取兜底**。

## 三端架构 (全部实测打通)

```
小芳采集 → Orin → Mac(8769) → ECS relay /upload
                                    │ 存队列 (100M 缓冲, 关机不丢)
                                    ├─ notify → ws_relay(:8766) → 广播 data_arrived 事件 (WS)
                                    └─ /status (轮询兜底)
4060 auto_loop v2: WS 订阅 wss://datadrive.world/ws → 事件到 → 立即拉取+训练 (零等待)
                   + 每60s HTTP /status 轮询兜底 (WS 掉线/错过事件补拉)
```

## ECS 侧改动

### ws_relay.py v2 (ECS :8765 + 本地通知口 :8766)
- 原 v1: Orin 推理服务 WS 心跳 → 广播 `{"type":"orin_status",...}` 给订阅端 (新客户端接入即推当前状态)。
- v2 新增 `notify_server(reader, writer)`: `asyncio.start_server` 监听 **127.0.0.1:8766** — 收到 `notify <latest> <frames>` 文本 → 广播 `{"type":"data_arrived","latest":...,"frames":...,"ts":...}`。main() 里 `asyncio.gather(notify_srv.serve_forever(), asyncio.Future())` 与 websockets.serve 并存。
- 广播函数泛化: v1 只广播 orin_status, v2 的 `broadcast(obj)` 接受任意 dict。

### zmax_relay.py /upload 成功后 notify
```python
def notify_data_arrived(name, frames=None):
    try:
        import socket as _sock
        msg = f"notify {name} {frames or 0}".encode()
        sk = _sock.create_connection(("127.0.0.1", 8766), timeout=2)
        sk.sendall(msg); sk.close()
    except Exception:
        pass  # ws_relay 不在线不阻塞上传
```
- JSON 上传成功分支 (存盘后) 和 二进制上传成功分支 (写盘后) **都要调** — 两条分支各有一个 `self._send({"ok":True,...})`。
- ws_relay 不在线必须静默 (上传是主链路, 通知是增值)。

### ⚠️ 补丁吞函数头坑 (2026-08-03 实测, `name 'enforce_buf_limit' is not defined`)
用 `str.replace("def enforce_buf_limit():", "def notify_data_arrived(...): ...\n\ndef enforce_buf_limit():")` 插入新函数时, 若替换串里把原函数头换掉了 → 原函数 docstring + 函数体残留进新函数体内, **原函数头消失** → 运行时 NameError。
教训: 插入函数用 replace 时锚点必须选**函数头本身作为前缀** (new = 新函数全文 + 原函数头), 且补丁后必须验证:
```bash
grep -c 'def enforce_buf_limit' /root/zmax-relay/zmax_relay.py   # 必须 == 1
python3 -c "import ast; ast.parse(open('...').read())"
# 以及功能验证: curl -X POST /upload 真实传包, 别只信语法
```
本会话就是只验证了 ast.parse 没查函数数, 直到真实上传 400 才暴露。

### /status latest 排序 bug
`pkgs = sorted(glob.glob(str(DATA_DIR / "*")))` 按文件名排序 — `pkg_20260803_205315.npz` > `demo_ws_test.json` (字典序), 新 JSON 包永远排最后 → /status 的 latest/latest_meta 恒指向旧 npz → auto_loop `check_new_data()` 拿 frames=? 不达标永远不训练新 JSON 包。
修: `sorted(..., key=os.path.getmtime)` (按时间取最新)。

## 4060 侧: auto_loop.py v2

依赖: `pip3 install --break-system-packages websocket-client` (PEP 668)。

关键结构:
```python
def process_new_data():   # 原 main 循环体抽成函数 (WS 事件和轮询共用)
    latest, meta, n = check_new_data()
    if latest and latest not in SEEN:
        frames = meta.get("frames", "?")
        if isinstance(frames, int) and frames >= 20:   # 阈值 20 (npz 包 frames=? 会被跳过)
            if LOCK.exists(): return                    # 训练锁防并发
            SEEN.add(latest)
            pkg = pull_data()          # GET /latest 弹栈
            ...落地 data/orin_live/auto_<ts>.json → build_dataset() → train() → upload()

def ws_listener():   # 守护线程, 断线 5s 重连
    ws = websocket.WebSocketApp(WS_URL,
        on_message=lambda w,m: ws_on_message(m),
        on_error=..., on_close=...)
    ws.run_forever()

def ws_on_message(raw):
    d = json.loads(raw)
    if d.get("type") == "data_arrived":
        threading.Thread(target=process_new_data, daemon=True).start()  # 不阻塞 WS 接收

def main():
    threading.Thread(target=ws_listener, daemon=True).start()
    while True: process_new_data(); time.sleep(60)   # 轮询兜底
```

设计要点:
- **SEEN 集合去重**: 同一包名不重复处理 (事件 + 轮询双触发只跑一次)。
- **LOCK 文件锁**: 训练中收到事件 → 留待下一轮 (防并发重建数据集)。
- 事件触发是异步线程 → 训练同时 WS 继续收消息。
- npz 二进制包 meta 无 frames → `frames="?"` 被阈值跳过 — 已知缺口 (JSON 包正常)。若小芳改传 npz 需在 meta 带帧数或 relay 解析 npz 头。

## 验证方法
- ECS 侧: `echo notify test.json 107 | nc 127.0.0.1 8766` 或 python socket → 看 ws_relay.log 出 "📢 数据到达广播"。
- 端到端 (本会话实测): 本地 POST /upload 25帧 JSON 包 → 4060 auto_loop 日志秒级出现 `⚡⚡ [WS事件] 数据到达: ... 立即处理` (非等 60s 轮询) → 拉取→训练→推回 ECS 全自动。
- 断线自愈: 重启 ECS relay → 4060 WS 断开 → 5s 自动重连 (日志 "🔌 WS 断开, 转轮询兜底" + "🔌 WS 连接 ..." 交替)。
