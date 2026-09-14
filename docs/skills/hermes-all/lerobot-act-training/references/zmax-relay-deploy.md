# Z-MAX ECS 中转服务 + 部署链 (2026-08-02 实测)

Orin 采集 → MAC → ECS 中转 → 4060 训练 → 模型回传 ECS → MAC 拉取 → Orin 部署。

## 架构 (ECS 39.102.211.79)
- `zmax_relay.py` 监听 **39053** (原 50053 被安全组挡, 已 sed 改端口), `ws_relay.py` 监听 **8765**。
- 阿里云安全组只放行 80/443 —— **直连 50053/39053 公网不通** (本机 curl 公网 IP 也超时)。
- **解法: nginx 反代** (datadrive.world.conf): `location /api/relay/ { proxy_pass http://127.0.0.1:39053/; client_max_body_size 200m; proxy_read_timeout 300s; proxy_send_timeout 300s; }` 同样加 `/api/orin/`。HTTPS 443 即达。
- ufw: `ufw allow 50053/tcp` (但安全组才是真闸门)。
- 内存: ECS 仅 **3.5GB**, 两个 hermes-venv python ≈770MB, free 可低至 162MB → 大文件上传有 OOM 风险。

## 弹栈队列语义 (核心约定)
- `POST /upload` — 入队。JSON 包存 `.json`, 二进制存 `.npz`。
- `GET /latest` — **弹栈 (取走即删)**。消费方必须立即保存。
- `GET /peek` — 只读队头 (事故后新增): 先 peek 确认再 latest 消费。
- `GET /status` / `GET /packages` — 队列状态/列表 (glob `*` 含二进制, 别只匹配 `*.json`)。
- 缓冲上限 **100MB**, 超限删最旧 (`enforce_buf_limit`)。
- 事故复盘: 首次 `GET /latest` 弹出 87MB 二进制没保存 → 队列空 → 需重推。教训: 消费方 `curl -o file` 或用 `requests.content` 落盘, 绝不打到 stdout。

## JSON vs 二进制判定 (多个坑, 全踩过)
- safetensors 文件头**本身是 JSON** → 不能只看 `startswith("{")`。
- 只读 4KB 头判 JSON → **>4KB 的大 JSON 采集包被误判为二进制** (300 帧包 ≈97KB 存成了 .npz)。
- 修复: `Content-Type` 含 "json" 或 ≤64MB 尝试完整解析; 二进制走流式写盘。**注意 ctype 分支里 obj 变量必须在 is_json=True 前已赋值** (否则 NameError → 误落二进制分支)。
- 双通道实测: `t.json`(56B) / 300帧 JSON / 84MB model.safetensors 全部正确识别。

## 大文件上传 OOM (ECS 3.5GB)
- 整包 `rfile.read(length)` 读 84MB → relay 进程被 OOM 杀 (进程数变 0, 502)。
- 修复: 二进制**流式分块写盘** (16-64KB chunks), 头部已读部分先写。
- nginx 默认 proxy 超时 60s → 84MB 慢速上传 502 → `proxy_read/send_timeout 300s`。

## SSH 进程管理 (ECS, 坑)
- 裸 `nohup python3 x.py &` 随 SSH 会话退出被杀 → 用 `setsid nohup ... < /dev/null &` 或 start.sh 脚本。
- `pkill -f zmax_relay.py` 与 `nohup python3 zmax_relay.py &` 放**同一条命令**会把新进程也杀掉 (模式匹配自身命令行) → kill 和 start 分开两条 SSH, 或写 start.sh。
- start.sh 模式: pkill → sleep 1 → setsid nohup → sleep 2.5 → ps + tail 验证。
- BaseHTTPRequestHandler **必须有 else 兜底**返回 404, 否则未知端点无响应 → nginx 502。

## WS 实时心跳 (升级替代轮询)
- `ws_relay.py` :8765 (`websockets` 16.1.1; nginx `/ws` 已反代到 8765 遗留配置正好复用)。
- Orin `orin_infer_service.py` :8766: 每 5s WS push `{"type":"heartbeat",...,"sys":{...}}`, **HTTP /orin/heartbeat 兜底**, 无 websockets 库自动降级。
- 控制台订阅 `wss://datadrive.world/ws` → 打开即收初始状态, 之后毫秒级广播。
- ECS 状态聚合: `POST /orin/heartbeat` (别名 `/heartbeat`, 因为 nginx 剥 `/api/orin/` 前缀) → `GET /orin/status` 返回全量 (含 `sys` 字段: CPU/GPU/内存/温度/ROS2节点/关节 via `orin_sys_status.py`)。
- 坑: nginx 反代剥前缀 → 控制台读 `/api/relay/orin/status` 而不是 `/api/orin/status` (后者被剥成 `/status` 返回队列信息)。

## 部署脚本清单 (仓库内)
- 4060 侧: `tools/upload_model.py <model.safetensors>` (84MB 推 ECS), `tools/cicd_deploy.py push/status`, `tools/relay_train.py pull` (JSON 训练数据用, **不是**模型).
- MAC 侧: `hermes_gateway_mac/cicd_pull_deploy.py` (拉取+部署 Orin, 用 `.content` 落盘), `collect_upload.py` (Orin 采集→推 ECS), `orin_infer_service.py`, `orin_sys_status.py`.
- **注意区分**: `relay_train.py pull` (JSON 数据) ≠ `cicd_pull_deploy.py pull` (二进制模型)。中继弹栈一次成功, 不保存即丢。
- **小芳守护进程每 5s 轮询 /latest** → 模型上传后几秒内被自动拉走部署。看到队列空别慌, 查 relay.log `已转发二进制并删除` 即确认被消费。
- **模型被消费≠已部署 (2026-08-02 实测)**: 小芳拉取可能中断 (84MB 传输 41MB 超时), 弹栈队列取走即删 → 重试时队列已空, 模型丢失且未部署。对策: ①上传后立即 `curl /status` 确认在队列; ②若被消费但对方说没部署, **重新 `tools/upload_model.py` 推一次** (文件名带新时间戳, 对方守护自动再拉); ③给大文件提供 scp 直连通道 (`sshpass -p Nix19789 scp root@ECS:/root/zmax-relay/data/<pkg>.npz .`) 绕过弹栈时序。
- **闭环判断标准**: 采集✅→训练✅→模型推回✅ 只算前 3 步; 部署 Orin + 推理 + 再采集才算闭合。Orin `/orin/status` 的 `infer_count` 长期为 0 = 推理服务没被调用, 闭环未闭合。
- ECS 部署: `sshpass -p Nix19789 scp ... root@39.102.211.79:/root/zmax-relay/` + sed 端口 + `bash start.sh`。

## 快照归档 + 视频流端点 (2026-08-02 下午-晚上迭代)
- **快照自动归档**: `POST /upload` 收到的包若 `meta.source=="orin_snapshot"` 或含 `snapshot_b64` → 不占训练队列, 直接解码落盘 `/root/zmax-relay/archive/snap_<ts>_<action>.jpg` + `.json` (元数据: current_state/all_states/action/timestamp)。队列只留可训练数据包。
- **视频流端点 (cicd.html 实时画面)**: `GET /api/relay/cam/latest.jpg` 返回最新现场帧 (归档快照优先, `CAM_DIR` 实时推帧次之); `GET /api/relay/cam/status` 返回 ok/age_s/last。页面 `<img>` 2 秒刷新即可直播。
- **`/peek` 归档兜底**: 队列空时 peek 返回最新归档快照 (`archived_snapshot:true` + current_state + snapshot_b64) — 页面状态机/图像依赖 peek 的包在队列空时仍能显示现场。
- **快照是训练队列的污染源**: 每 30s 一个 orin_snapshot 会堆满队列 (467 个/小时)。归档机制上线前必须手动清: `json.load` 判 source==orin_snapshot → os.remove, 保留 orin 数据包。监控/守护脚本也要过滤 `orin_snapshot` 源。
- **nginx 正则 location 拦截 `.jpg` 请求 (2026-08-02 大坑)**: BT 面板默认 `location ~ .*\.(gif|jpg|jpeg|png|bmp|swf)$` 会先于 `/api/relay/` 前缀匹配, 把 `/api/relay/cam/latest.jpg` 当静态文件处理 → 404。**修法: 用 `location ^~ /api/relay/cam/` 前缀匹配** (nginx 中 `^~` 优先级高于所有正则), 或在正则之前插入。验证: `curl -o /tmp/t.jpg -w '%{http_code} %{content_type}' https://datadrive.world/api/relay/cam/latest.jpg` 应 200/image/jpeg。
- **新端点必须确认 nginx 反代 + relay 双端匹配**: 加 `/api/snapshot/latest` 别名端点时, nginx 反代 `proxy_pass http://127.0.0.1:39053/api/snapshot/` 的路径会拼接, relay 里 `self.path` 可能带/不带 `/api` 前缀 — 排查时先 curl relay 本机 (`http://127.0.0.1:39053/snapshot/latest` 与 `/api/snapshot/latest` 两个都试) 区分是 relay 还是 nginx 层 404; 本机 200 公网 404 = nginx 层问题。
- **页面并发编辑互相覆盖 (协作坑)**: web 与 4060 同时改 cicd.html, 后者更新会整体覆盖前者插入的 img/JS (会话内被覆盖 3 次)。分工: 前端页面归 web, relay 端点归 4060; 或改动后立即验证页面仍含自己的锚点 (`grep -c 'cam/latest' cicd.html`)。
- **Orin 全量状态 sys 字段**: `orin_infer_service.py` 心跳带 `sys` (CPU/GPU/内存/温度/ROS2节点/关节, 采集器 `orin_sys_status.py`)。`/orin/status` 的 `sys` 为空 = Orin 端跑的是旧版推理服务, 需小芳更新重启。

## 验证命令
```bash
curl -s https://datadrive.world/api/relay/status          # 队列
curl -s https://datadrive.world/api/relay/peek            # 队头只读
curl -s https://datadrive.world/api/relay/orin/status     # Orin 全量状态
curl -s -X POST https://datadrive.world/api/relay/upload --data-binary @<file>   # 二进制入队
```

## 跨机部署 fallback 链 (2026-08-10 模型给 Mac/小芳实测)
给 Mac/Orin 部署模型时按此顺序尝试, 别一上来就卡在 SSH:
1. **静态 URL 最优**: `sshpass scp model <ECS>:/www/wwwroot/datadrive.world/models/` + `chmod 644` → `curl -o model https://datadrive.world/models/<name>` — 不弹栈可重试。
2. **relay POST /upload 只适合数据包, 不是文件网盘 (2026-08-10 实测)**: 上传 2.3MB tar 返回 `{"ok": true, "name": "pkg_xxx.npz", "size": ...}`, 但 **`GET /latest` 弹的是最新命令/数据包 (multipart 响应体), 不是刚上传的文件** — relay 的上传端点是给 Orin 采集数据设计的 (存元数据+帧), 不能当通用文件传递用。下载自己刚传的文件没有可靠端点。
3. **ECS SSH 密码可能过期 (2026-08-10 实测)**: `Permission denied (publickey,password)` 且两个历史密码都拒 — 密码改了不会通知, 别反复试旧密码, 直接问老倪要新的或走飞书通道。
4. **Mac 守护进程可能离线**: relay `request()` 20s 未消费 = 守护没跑, relay 命令发不进去 — 先确认对方守护在线再依赖 relay 自动部署。
5. **最终 fallback: 飞书 MEDIA 发小包** (2.3MB tar 直接发群里, 对方解压即部署) — 小模型/脚本/配置这类 <10MB 的包最省事, 别为它折腾 SSH/relay。
- 部署包内容惯例: `model.pt + config.json + 独立 eval 脚本 + README` (eval 脚本须自带 LeftBrainMLP/RightBrainWM 类定义, 不依赖 WSL 仓库 import)。
