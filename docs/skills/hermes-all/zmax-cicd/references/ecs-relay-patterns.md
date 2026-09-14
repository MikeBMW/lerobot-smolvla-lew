# ECS 中转 (zmax_relay.py :39053) 设计模式与坑

## 部署要点
- 服务: `/root/zmax-relay/zmax_relay.py` (HTTP relay) + `ws_relay.py` (:8765 WebSocket 广播)
- 启动用 `start.sh` (setsid + nohup + 日志)，**裸 nohup 会随 SSH 会话退出**；start.sh 里 pkill 和启动分两个脚本/两步，`pkill -f xxx && nohup python3 xxx` 同命令会杀掉刚启动的进程
- 端口在文件内 `port = 39053` (50053 是历史遗留，nginx 反代指向 39053)

## 弹栈队列语义 (核心)
- `GET /latest` 取走即删 (pop)；`GET /peek` 只读不删 (查看队头，二进制只返回元信息)
- 消费方流程: **先 peek 确认 → 再 latest 消费 → 立即落盘**。首次联调教训: 小芳 GET /latest 拿到 87MB 二进制没保存，队列已空 → 数据丢失
- 二进制包用 `application/octet-stream` 回传原始字节；JSON 包返回对象
- 缓冲总量上限 100MB，`enforce_buf_limit()` 超限删最旧 (老倪约束)

## 二进制 vs JSON 判定 (关键 bug 史)
- 只读前 4KB 判断 JSON 会误判: safetensors 文件头**是合法 JSON** (以 `{` 开头)，且大 JSON 采集包 (>4KB) 4KB 内解析失败被误判为二进制 (.npz)
- 正确逻辑: `Content-Type` 含 json 直接走 JSON；否则 ≤64MB 读完整尝试 `json.loads`；失败走二进制流式写盘 (16KB chunks，防 3.5GB 内存 OOM)
- 模型 84MB > 64MB 限制 → 自动走二进制流式，正确

## nginx 反代 (datadrive.world.conf)
- `location /api/relay/ { client_max_body_size 200m; proxy_pass http://127.0.0.1:39053/; proxy_read_timeout 300s; proxy_send_timeout 300s; }` — **大文件必须加 300s**，默认 60s 导致 84MB 上传 502
- `proxy_pass` 末尾 `/` 会剥前缀: `/api/relay/cam/latest.jpg` → 后端 `/cam/latest.jpg`；`/api/orin/heartbeat` → 后端 `/heartbeat`，所以后端兼容多路径 (`path in ("/orin/heartbeat","/heartbeat")`)
- **正则 location 优先级**: `location ~ .*\.jpg$` (静态资源) 会拦截 `/api/relay/cam/latest.jpg` 返回 404 → 用 `location ^~ /api/relay/cam/` (前缀匹配优先于所有正则) 反代到 39053/cam/
- 改完 `nginx -t && /etc/init.d/nginx reload` (systemctl 不可用: nginx 由宝塔管理，`systemctl reload nginx` 报 not active)
- 安全组未放行 39053 公网 → 必须走 443 反代；ECS 本机 curl 127.0.0.1 可通

## 端点模式
- do_GET / do_POST 未知路径必须有 else 兜底 (404 JSON)，否则 nginx 无响应 502
- Orin 心跳: `POST /orin/heartbeat` 存 ORIN_STATE (独立于弹栈队列，不占缓冲)，`GET /orin/status` 控制台轮询；心跳带 `sys` 字段 (CPU/GPU/内存/温度/ROS2节点/关节，由 orin_sys_status.py 采集)
- 相机帧: `POST /cam/upload` (JPEG 字节) → cam/ 目录只留最新 3 帧 → `GET /cam/latest.jpg` + `/cam/status`；网页 2s 轮询 latest.jpg (加 ?t= 防缓存)

## WebSocket 模式 (ws_relay.py)
- `websockets.serve(handler, "0.0.0.0", 8765)`；新客户端接入即推当前状态 (控制台打开即有数据)；Orin 推 heartbeat → broadcast 给所有订阅者
- nginx `location /ws { proxy_pass http://127.0.0.1:8765; proxy_http_version 1.1; proxy_set_header Upgrade $http_upgrade; proxy_set_header Connection "upgrade"; }`
- Orin 端双通道: WS 主心跳 (5s) + HTTP 兜底 (10s)，无 websockets 库自动降级 HTTP
- 测试: 本地 venv 需 `uv pip install websockets`；wss://datadrive.world/ws 实测 Orin 推→ECS 广播→控制台收

## 压测要点 (tools/stress_test.py)
- 弹栈队列压测必须先排空 (while latest!=404)；并发+弹栈会有消费竞态，纯循环(串行) 10/10 字节级一致才可信
- 载荷带标记 `PKG-{i:04d}-`，校验 `got[:4]==b"PKG-"` (不是 [:5]，第5字符是序号)
