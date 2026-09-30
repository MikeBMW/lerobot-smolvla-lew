---
name: http-relay-service
description: Use for HTTP relay/queue services on remote hosts.
---

# HTTP Relay / Queue / Bridge Services

Patterns for stateless HTTP relay services that shuttle data between machines (edge collectors → cloud relay → training nodes), with queue semantics, status feedback, and robust big-file handling.

## When to use
- Building a relay/bridge/forwarder between hardware nodes and training/cloud machines
- Fixing relays that crash on big uploads, lose data on GET, or die after SSH logout
- Adding status/health feedback for deployed services (heartbeat → dashboard/console)

## Core patterns

### 1. Queue semantics: pop endpoints need a peek companion
- `GET /latest` that deletes after serving = stack/queue pop. Consumers who don't save the body LOSE the item permanently.
- ALWAYS add `GET /peek` (read-only; binary items return metadata only, never the bytes) so consumers can confirm before consuming.
- Document one-shot semantics in the CLIENT script header too — teammates will forget and re-fetch into stdout.
- Keep status/heartbeat on SEPARATE endpoints (e.g. `/orin/status`) from the data queue so status reads never consume data.

### 2. Binary upload: stream to disk, never read whole body into memory
- On small-RAM hosts (3-4GB VPS), `rfile.read(length)` for 50-100MB uploads can OOM-kill the process SILENTLY — no traceback, process just vanishes.
- Stream: read first 4KB to sniff type, then write the remainder in 16-64KB chunks directly to file.
- Verify the process survives a full-size upload (`ps aux | grep` + file size matches).

### 3. Binary vs JSON sniffing — model-file headers ARE valid JSON, AND large JSON packets fool 4KB sniffs
- safetensors/npz files often start with `{` and decode as UTF-8 → naive `startswith("{")` misclassifies them as JSON.
- Decide by attempting a FULL `json.loads()` of the head chunk; only a complete parse counts as JSON.
- Catch `Exception`, NOT `json.JSONDecodeError` — decoding arbitrary bytes raises `UnicodeDecodeError` first.
- **Inverse trap (2026-08-02 实测)**: sniffing only the first 4KB misclassifies LARGE JSON packets too — a 300-frame collection JSON (~97KB) does NOT fully parse within 4KB → falls through to the binary branch → stored as `.npz` instead of `.json`. Collection data silently lands in the wrong queue format.
- Robust ordering: (a) trust an explicit `Content-Type` containing `json` FIRST; (b) else sniff with a bigger head (64KB) and full-parse ≤64MB; (c) else binary. 
- **NameError trap**: if you set `is_json = "json" in ctype` but `obj` is only defined inside the parse branch, a JSON Content-Type skips the parse → `json.dump(obj)` raises NameError → caught by a blanket `except` → silently treated as binary. Always ensure `obj` is bound before the `if is_json:` storage block (parse first, then branch), or init `obj = None` and check `obj is not None`.
- Verify BOTH directions after changing the sniff: small JSON (`t.json`), large JSON (300 frames), and an 80MB+ binary model — all three must land with correct names/extensions.

### 4. nginx reverse proxy to bypass cloud security groups
- Cloud security groups (Aliyun/AWS) often only open 80/443; high ports stay blocked even after ufw allows them. Test from the box via its PUBLIC IP: still times out = security group, not ufw.
- Bind service to 127.0.0.1:highport; add nginx location with `client_max_body_size 200m;` AND `proxy_read_timeout 300s; proxy_send_timeout 300s;` — default 60s proxy timeouts kill slow 80MB uploads with 502.
- Endpoint becomes `https://domain/api/<name>/<endpoint>`.
- Port mismatch between service and nginx upstream causes silent 502s — grep BOTH sides.
- **Prefix stripping**: `proxy_pass http://127.0.0.1:PORT/;` (trailing slash) STRIPS the location prefix — `/api/orin/heartbeat` arrives at the service as `/heartbeat`. The service must accept BOTH the bare path and the prefixed path (`if path in ("/orin/heartbeat", "/heartbeat")`). And the mirrored GET path may now collide with an existing bare endpoint (`/api/orin/status` → `/status` returns queue status, NOT orin status) — after adding a new location, curl BOTH the public URL and the localhost path and compare response bodies.

### 5. SSH process management: setsid, never bare nohup
- Plain `nohup python3 app.py &` dies when the SSH session closes. Use `setsid nohup python3 app.py > log 2>&1 < /dev/null &` or a start.sh run via `bash start.sh`.
- PITFALL: `pkill -f 'app.py' && restart` in ONE ssh command line kills the freshly-started process too (pkill matches the new cmdline). Split kill and start into separate invocations, or put pkill inside a start script.
- After restart: `ps aux | grep app | grep -v grep`, then curl localhost:port.

### 6. WebSocket long-connection upgrade (heartbeat/status push)
When asked "why not websocket?" — answer: HTTP polling is the fast-first implementation (stdlib-only, works everywhere); WS is the durable upgrade. Apply it as **WS primary + HTTP fallback**, never a hard cutover:
- Edge service tries WS first; if the `websockets` lib is missing on the edge, degrade to HTTP heartbeat automatically (graceful, no dependency wall).
- WS server on the relay acts as a **broadcast hub**: keep a `clients` set; on heartbeat → `broadcast()` to all subscribers. New subscriber receives **initial state immediately on connect** (console opens with data, not blank).
- Reconnect loop pattern: `while True: try: async with websockets.connect(URL) as ws: ... await asyncio.sleep(5) except: await asyncio.sleep(5)`.
- Heartbeat payload stays the SAME shape as the HTTP version (`{type:"heartbeat", online, model, infer_count, ...}`) so both paths feed one status store; keep the HTTP `/heartbeat` endpoint alive as fallback.
- nginx `/ws` location needs Upgrade headers (`proxy_set_header Upgrade $http_upgrade; Connection "upgrade"; proxy_read_timeout 86400s;`) — same security-group-bypass as §4, works out of the box with wss://domain/ws.
- Verify: connect a subscriber + a fake publisher, assert subscriber receives initial state AND the broadcast after publisher sends.

#### 6b. Event-driven "data arrived" — WS as the zero-wait trigger (2026-08-03 实测)
When the consumer is a laptop that shuts down often, ECS is always-on, and demos must not wait: **WS for EVENTS, HTTP polling for STATE**. State queries (queue empty? latest?) are self-healing under polling — reconnect → next poll sees current state, nothing lost. Events (data just arrived!) are LOST during a WS disconnect window unless compensated. Pattern = WS event → react immediately; slow HTTP poll (60s) stays as the missed-event fallback; subscriber polls `/status` once at startup to replay anything missed.

- Wiring: `ws_relay.py` (websockets hub :8765) ALSO runs `asyncio.start_server(notify_server, "127.0.0.1", 8766)` — a local TCP notify port. `zmax_relay.py` upload handler, after successful store, opens a plain stdlib socket to 127.0.0.1:8766 and sends `notify <name> <frames>`. ws_relay broadcasts `{"type":"data_arrived","latest":...,"frames":N,"ts":...}` to all subscribers. **Don't make sync zmax_relay POST as a WS client** — sync http.server + async websockets don't mix; the tiny TCP line is the clean bridge.
- Subscriber (auto-trainer): `threading.Thread(target=ws_listener, daemon=True)` running `websocket.WebSocketApp(WS_URL, on_message=...)`; on `data_arrived` → spawn another thread for processing so the receive loop never blocks; on_error/on_close → `time.sleep(5)` + reconnect (the while-loop around `run_forever()` IS the reconnect).
- Verify end-to-end: POST a small JSON package → subscriber log shows `[WS事件] 数据到达` within ~1s (not 60s) → pipeline starts. Also restart the relay → subscriber reconnects in ~5s.

### 7. Serving realtime images through nginx (live frames / snapshots)
- Static-file regex locations (`location ~ .*\.(gif|jpg|jpeg|png|bmp|swf)$` with `expires 30d`) CACHE image responses and shadow prefix proxy locations — a live-stream endpoint like `/api/relay/cam/latest.jpg` gets eaten by the `.jpg` regex and returns stale/404.
- Fix priority: `location ^~ /api/relay/cam/` — the `^~` prefix match beats ALL regex locations regardless of config order. Plain prefix `location /api/relay/` does NOT beat regexes.
- Realtime frames need `location = /orin_realtime.jpg { add_header Cache-Control "no-store, no-cache, must-revalidate"; expires -1; }` or nginx/browser serves the cached frame → "I see the old image" complaints.
- Distinguish "pipeline broken" from "just test data": download the frame and check **unique color count** (`np.unique` of all pixels == 1 → solid test/placeholder frame) or luminance std ≈ 0. Static test pages with hardcoded base64 images are NOT live feeds — verify the actual endpoint.
- Frame push options: SCP overwrite of a website-directory file (simple, needs sshpass + write perms) vs POST /cam/upload endpoint on the relay (no scp, any HTTP client).
- **Archive frames should be PRIMARY, not fallback (2026-08-02 实测)**: when a snapshot-archiving producer updates the archive every ~1s, `GET /cam/latest.jpg` must prefer the NEWEST archived snapshot over the CAM_DIR live-push dir — CAM_DIR can hold STALE sim/test frames (a killed push service leaves old frames behind; `age_s` balloons to minutes while the archive keeps refreshing). Order: archive glob first → CAM_DIR second. Apply the same order in `/cam/status` so `age_s` reflects the real feed. Verify: pull twice 2s apart and diff bytes, plus status `age_s` < 2.
- **`/peek` archive fallback keeps page state machines alive (2026-08-02 实测)**: pages that poll `/peek` to render current state + image (fields like `current_state` / `all_states` / `snapshot_b64` from queue packets) go blank once snapshots are auto-archived and the queue only holds data packets. Fix: when the queue is empty, `/peek` falls back to the newest archived snapshot — return `{archived_snapshot: true, current_state, all_states, action, timestamp, snapshot_b64}` (re-encode the archived .jpg to base64). Queue-first, archive-fallback. A stray binary packet in the queue still shadows the fallback — drain the queue to observe the fallback path.
- **PIL text() silently renders NOTHING without a font file (2026-08-02 实测)**: `ImageDraw.text()` on a bare PIL install (no default font resolution) draws zero pixels and raises nothing — your simulated frame appears as a solid color, and direction markers made of text are invisible. Use GEOMETRIC anchors instead: red triangle polygon at top, blue bar at bottom, moving rectangle + barcode-style bit bars for frame number. Verify by counting colored-pixel regions, never by expecting rendered text.
- **Frame orientation verification**: after pushing frames, verify direction programmatically — count anchor-color pixels in the top rows (e.g. red `(255,60,60)` triangle → `top_red > 50`) and bottom rows (blue bar → `bot_blue > 500`). This answers "图像没正过来" objectively instead of eyeballing.
- **Stress-test marker prefix trap**: if your integrity marker is `PKG-{i:04d}-` the 5th char is a DIGIT (`PKG-0000-`), so `got[:5] == b"PKG-"` is False for valid payloads → false FAIL on a healthy link. Check `got[:4]`. Also: pop-queue semantics mean a concurrent test can consume your just-uploaded packet — verify marker prefix, not exact size, and drain the queue before a cycle test.

### 8. Queue hygiene: purge by metadata, keep data packets
- Relay queues accumulate junk when an upstream producer keeps pushing (snapshot/thumbnail streams): thousands of small packets, tens of MB. Don't `rm -rf` the whole queue — iterate packets, inspect `meta.source` (or equivalent tag), delete `snapshot`/`thumbnail` types, keep real `data` packets. Report deleted-vs-kept counts.
- Fix the upstream so it stops pushing junk (pause the producer), not just clean once.

### 10. agent 消息通道 (2026-09-25 实测: 与 web 智能体交换提示词/回执)
`zmax_relay.py` 上纯追加一组路由 (数据队列不动), 落盘 `/root/zmax-relay/agent/{prompt,reply}.jsonl`:
```
POST /agent/prompt  {"text","from","meta"} → {"ok":true,"seq":N}      # web agent 下发
GET  /agent/prompt?after=N                 → {"prompts":[...],"next":M} # 本机只读游标拉取 (幂等, 不 pop)
POST /agent/reply   {"prompt_seq","text","data"} → {"ok":true,"seq":M}  # 本机回执
GET  /agent/reply?after=N                  → {"replies":[...],"next":K}
GET  /agent/status                         → 两侧计数 + last_prompt/last_reply
```
- 为什么不用 `/command`: 那是**单槽覆盖** (后一条吃掉前一条) 的采集指令; agent 消息要可重放/不丢 → append-only + `?after=N`。
- ⚠️ `seq` 是小整数: 想"跳到队尾"必须读 `/agent/status.last_prompt.seq`, 用 `after=1e9` 会把新消息也过滤掉。
- ⚠️ 消费者(本机 5s 常驻) 与取证脚本会抢同一条消息 → 取证时先 `systemctl stop` 消费者。
- 补丁锚点唯一性: `if path == "/command":` 在 do_GET/do_POST 各出现一次, 别拿它当锚点; 用 `def do_POST(self):\n        path = self.path.split("?")[0]\n`。

#### 10b. 消费者侧铁律 (本机常驻、拿消息去跑模型/动作的环)
这组路由的典型消费者是一个"看消息 → 干活(几秒~上百秒) → 回执"的常驻环。它跑偏的四种方式:
- **游标锚队尾, 只处理新消息**: 启动时先读 `/agent/status.last_prompt.seq` 当起点, **绝不回放历史**
  (否则一启动就把陈年消息逐条答一遘)。游标**落盘**(如 `reports/<环>_state.json`), 重启接着跑。
- **被过滤掉的条目也必须推进游标**: 维护一个"本进程见过的最大 seq"(含被过滤的), 单独用它推游标;
  只在"处理列表"里推 ⇒ 被过滤的消息永远不会被跳过去 ⇒ 每 3s 重读同一批, 游标卡死。
- 🔴 **队列里有机器消息**: 本地硬件桥/看门狗会定期发探询词(如 `status 状态空间`, 实测每 ~60s 一条)。不区分来源
  ⇒ 一条机器探询就白跑一轮 (实测 65s 的视觉模型调用) 并把人工触发的标注**覆盖掉**。定式: `from` 黑名单
  (web-hw-bridge / *-bridge / watchdog …) + **整条就是探询词的**正则过滤; 宁松勿严 —— 「状态: 看光模块」这种带内容的
  必须放行。"跳过"也要记一行(同一条只报一次, 不刷屏)。
- **回执带 `prompt_seq`**, 且把"收到什么/跑了多久/产出什么"写进回执正文; 队列两端都靠这个对账。
- 停自家消费者用**括起一个字符**的写法 (`l5_hil_[a]gent.py`): `pkill -f l5_hil_agent.py` 会匹配到自己这条命令行。

### 11. 两个进程都不在时的恢复 (2026-09-25 实测)
症状: `/api/relay/*` **全部** 502 且 `/ws` 也 502, 但首页 200 → 说明 nginx 活着, **zmax_relay(39053) 与 ws_relay(8765) 双双不在** (无人监管, 重启/崩溃后静默死掉)。
恢复: 各用自带脚本拉起 (`bash /root/zmax-relay/start.sh`、`bash /root/zmax-relay/start_ws.sh`), 两次 ssh 分开执行 (脚本内 pkill 会匹配同一条命令行)。复核 status/peek/packages/orin/status/cam/status + `/ws`(426=升级协商, 说明 WS 服务活了; 502=还没起)。

### 12. 无登录口主机的反向命令通道 (poll-and-exec client)
场景: 目标机只开几个业务口(如 135/139/445 + 服务端口), 无 SSH/RDP/WinRM, 也无 SMB 凭据 ⇒ 唯一可控手段是**在那台机上跑一个轮询客户端**主动来 hub 取命令。

结构(实测可用):
- hub 侧: 命令队列 + `GET /agent/cmd?t=<token>`(取一条) + `POST /agent/out?t=<token>`(回执) + `GET /agent/beat?t=<token>`(探活); **队列只允许 hub 本机写入**, 网络侧只能取/回。
- 客户端(hub 派发的静态脚本, **纯 ASCII**): 每 3s 取一条 → 执行 → 回执。

必守四条(每条都踩过):
1. **命令必须在子进程里跑, 不能内联在主循环里**: 内联写法 `$o = (Invoke-Expression $c 2>&1 | Out-String)` 一旦碰上抛**终止性错误**的命令(不存在的外部程序、语法错), 整个轮询循环一起退出 → 客户端悄悄死掉。
   症状 = hub 日志出现了「下发」但后面**没有对应的「回执」**, 之后永远没有新的「下发」。
   修法: 命令先写进临时 `.ps1`(**UTF-8 带 BOM**, 否则 PS 5.1 把中文解析成乱码; 首行 `Set-Location -LiteralPath '<工作目录>'` 把工作目录补回来),
   再 `& powershell -NoProfile -ExecutionPolicy Bypass -File <文件> 2>&1 | Out-String` 取输出; 主循环整体再包 try/catch。
2. **主循环不依赖一次性成功**: 取命令失败(超时/ARP 抖动)只跳过本轮, 不退出。
3. **两端都要能自愈**: 目标机的**分钟级看门狗**里加一条「没有客户端进程在跑 → 重新触发它的计划任务/unit」; 客户端启动时自己拉一次最新看门狗脚本(自举), 否则看门狗升级永远只能靠人手贴。
   - **升级看门狗不必重启客户端**: 看门狗是**独立计划任务**每分钟执行那个文件 ⇒ 让目标机 `iwr <hub>/<看门狗>.ps1 -OutFile <同名路径> -UseBasicParsing -TimeoutSec 20` 覆盖同名文件即可**立刻生效**, 且零风险
     (重启客户端会短暂断通道, 一旦拉不起来就只能等人在现场)。生效核对三样: 文件里的**版本标记**(如 `rev6`) · 新增那段的**特征串命中数** · 业务口 200。
   - 往看门狗里加的"防呆"要能治 §12.5 的死锁: 杀掉**挂在取命令临时脚本上超过 N 分钟**的子进程(实测 10 分钟), 只杀子进程、主循环不动。
4. **通道死了就从外面救不回来** (无登录口 = 无第二入口) ⇒ 把「让人在那台机贴一行」当正式恢复手段写进 runbook, 交付时就把那一行贴出来。一行模板:
   `cd <工作目录>; iwr http://<hub>:<port>/<client>.ps1 -OutFile <client>.ps1 -UseBasicParsing -TimeoutSec 20; powershell -ExecutionPolicy Bypass -File .\<client>.ps1`
   (PS 5.1 下下载/轮询一律带 `-UseBasicParsing -TimeoutSec N` —— 不带会卡在 IE/代理初始化, 现场表现就是"怎么卡住了")。

5. **命令必须"有界": 子进程没有超时, 一条卡住的命令会把整条通道堵死**. 循环是**同步**执行子进程
   (`& powershell -NoProfile -ExecutionPolicy Bypass -File <临时.ps1> 2>&1 | Out-String`), **没有任何超时**;
   而目标机的看门狗只看"客户端进程在不在"(CommandLine 含客户端脚本名) ⇒ **卡住但活着的客户端永不自愈**。
   症状: hub 日志里最后一条「下发」没有对应「回执」、beat 文件停更、回执目录不再增长。
   挨雷的命令型(实测把通道堵死十几分钟): 通配删除(`Remove-Item <dir>\*.png`)、扫系统大目录
   (`Get-ChildItem C:\Windows\Temp`)、任何会弹交互提示的调用。定式: 一次只做一件事、**不通配删、不扫大目录**,
   长活拆成多条短命令、每条自带 `-TimeoutSec`; 清文件交给对方的定时任务或分页做。
   恢复(无登录口 ⇒ 必须让人在现场跑一行; 只杀卡住的子进程即可, 主循环会自己接着跑, 队列里的命令会继续执行):
   `Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | Where-Object { $_.CommandLine -like '*<临时脚本名>*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }`
   判活: `beat` 文件 mtime < 90s **且** 回执目录出现了新文件(只看一条会误判)。

判活与取证:
- **别用取命令端点探活**: `curl http://127.0.0.1:<port>/agent/cmd?t=<token>` 会把队列里的一条待办命令**取走**(hub 日志会记成"下发给了 <本机IP>" = 自己吞了一条正经命令)。要探活就发一条真命令当探针, 或只看 hub 日志。
- 回执文件按去队秒命名, 同秒两条互相覆盖 ⇒ 认回执看 hub 日志的 `← 回执 <n> 字节 → <路径>` 行, 不要 `ls -t` 目录里最新那个(可能还没落盘, 你会看到上一轮的内容并误判通道已活)。
- 命令里别用 `Write-Host`(写 information 流, `2>&1|Out-String` 抓不到 → hub 端只拿到空回执); 用字符串表达式/cmdlet 的输出。
- **验收远端服务时, HTTP 客户端必须保留状态码**: `except Exception` 一律 `(0, str(e))` 会把 404/500 全变成 0
  ⇒ 该当"合法未就绪"的 404 认不出来(异常文本是 `HTTP Error 404: NOT FOUND`, 拿不到服务端 JSON) ⇒ **假失败**。
  单独捕 `urllib.error.HTTPError` 回 `(e.code, e.read())`; 中文 body 常被 Flask `jsonify` 转义成 `\uXXXX`
  ⇒ 判"合法 404/未就绪"要同时认 **原文 / 转义 / 空 body** 三种形态。
- **自动回滚只该由"本轮真改了文件"的那一路触发**: 多路一起验收时, 另一路自己抽风会把本轮修复误判为失败
  ⇒ 触发回滚(用 `.bak` 覆盖) ⇒ **刚推上去的新版又被换回旧内容**。先比对方与本地的内容哈希, 没变的那路只报状态、不计入成败。
- **`.bak` 只代表"上一版"**: 每次部署都覆盖它 ⇒ 想留"真正的老版本"必须**另存一个名字**, 否则回滚点一路被推着走, 真要回老版时已经没有了。
- **异步服务的验收基准要等落盘稳定再取**: "操作前后文件数不变"这类断言, 基准若取在后台 worker 还在写的时候
  ⇒ 假失败(且会连带触发回滚)。等连续两次计数相同再取基准。

### 13. 上传口 ≠ 快照入口（探语义要用无副作用的方式）
同一个服务上常并存两条完全不同的数据路：**包队列**（`POST /upload` → `pkg_<ts>.<ext>`，供训练/消费者读）
与**对外快照文件**（nginx/BT 直接吐的那张图，如 `/api/snapshot/latest`）。
- **往队列推图片不会更新那张快照**：实测 POST 一张 JPEG 回 `{"ok":true,"name":"pkg_....npz","size":102571}`，
  而 `/api/snapshot/latest` 字节不变。要图对外可见，必须让域名侧把快照文件指到同一处、或另加一个收图的口
  —— **别把"推上去了"当成"对外可见了"**。反之，快照停更是推方停了（`cache-control: no-store` 且多次取回字节完全相同
  = 服务器上那个文件没被写，不是 CDN 缓存）。
- 探语义的代价从低到高：`OPTIONS`（看允许方法）→ `GET <上传口>`（多数实现返回自描述 JSON：端点清单/字段格式）
  → `POST 空体` → `POST 最小 JSON`。每步记下返回的 `name/size/frames`。
- ⚠️ **`POST 空体` 会真的落一个 0 字节的包** ⇒ 探测即产生垃圾文件。只读够用时绝不 POST；
  写过测试件就在交付说明里如实告知（对方会看到碎文件，自己删）。
- ⚠️ **服务自述的端点清单 ≠ 实际可路由的路径**：手册里写的 `GET /latest` / `/packages` 实测可能是 nginx 404
  （只转发了部分前缀）。判端点存在与否要实测，不照抄自述。
- 判"某路径是不是真端点"不能只看 200：设备/中继常见 catch-all（未知路径返回同一份默认 JSON）。
  逐路径比 `%{size_download}` + 首字节（`head -c 4 | xxd -p`）—— 大小与类型完全一致 = 兜底路由，端点不存在。

## Verification checklist
1. `curl -X POST <relay>/upload` small JSON → `{"ok": true}`
2. `curl <relay>/peek` → item present, still queued after
3. `curl <relay>/latest` → item returned AND removed (next peek = no data)
4. Full-size binary upload (80MB+) → process alive, file size matches
5. `curl <relay>/status` → correct counts

## Pitfalls
- relay.log appended with `>>` may hold stale entries — check process start time, not just log tail.
- Heartbeat/status state is lost on process restart unless persisted to disk.
- **do_POST needs an else fallback**: if do_POST only `if`s known paths and falls off the end, unknown endpoints get NO response → nginx reports 502 (not 404). Add `self._send({"error": f"unknown endpoint: {path}"}, 404)` at the end of do_POST. Symptom: curl → 502 but relay log shows no POST record for that path. do_GET usually already has the else — only do_POST forgets.
- **Heartbeat freshness ≠ online flag**: a status field like `last_seen` frozen at an old timestamp means NO live heartbeats are arriving (could be stale simulation/test residue). Real edge device online → last_seen refreshes every heartbeat interval and counters increment. Check freshness, don't trust `online: true`.
- **`/status` "latest" must sort by MTIME, not filename (2026-08-03 实测)**: `pkgs = sorted(glob.glob(...))` sorts by NAME — `pkg_20260803_205315.npz` > `demo_ws_test.json` alphabetically, so the newest JSON packet is permanently shadowed by an older binary → auto-trainers polling `/status` never see the JSON packet. Fix: `sorted(..., key=os.path.getmtime)`. Symptom: upload OK, queue has 2 items, but `/status.latest` always shows the binary. Verify: upload a new JSON after an older npz, confirm `latest` flips.
- **Binary packets lack frame counts → threshold logic silently skips them (2026-08-03 实测)**: binary upload branch stores `.npz` with `meta = {"binary":..., "size":...}` — NO `frames` key. Consumer gates like `frames >= 20` see `frames="?"` and NEVER fire → binary data sits in the queue untrained while the trainer logs "队列空". JSON packets carry `meta.frames`; binary producers must include a frame count (side-channel, filename, or a small companion JSON) or the consumer must parse the npz itself. Detect: trainer keeps re-logging the same `latest` with `frames=?`.
- **Remote patch scripts can swallow a function header (2026-08-03 实测)**: replacing `def enforce_buf_limit():` (with its docstring) as the anchor, then injecting a new function BEFORE it, left the old docstring+body orphaned inside the new function → `enforce_buf_limit` UNDEFINED → `/upload` returns 400 `name 'enforce_buf_limit' is not defined`. Rule: when string-patching remote scripts, the anchor must include the FULL function header line; after patch run `ast.parse` AND exercise the real endpoint (small JSON upload), not just syntax check. Always `cp app.py app.py.bak_$(date +%s)` first.
- **pkill bracket trick `[z]` still fails when the SAME ssh command also starts the service (2026-08-03 实测)**: `pkill -f '[z]max_relay'` alone works (exit 0), but `pkill ... ; sleep 1; setsid nohup python3 zmax_relay.py ...` in one ssh command → exit 255, because pkill ALSO matches the `python3 zmax_relay.py` text inside its own bash -c command line. Fix: kill in ONE ssh call, start in a SEPARATE call, or put both in a start.sh on the host and run `bash start.sh`. 本质是**模式出现在自己这条命令行里** ⇒ 括起一个字符(`l5_hil_[a]gent.py`)即可自排除。
- **消费者环把机器消息当人话**: 同一队列上硬件桥每 ~60s 发一条探询词, 不滤 ⇒ 白跑一轮模型+覆盖人工结果; 同时被过滤的条目不推游标 ⇒ 每轮重读同一批。两处都要修(详见 §10b)。

### 9. Relay "collection query failed" — nginx + relay double-death recovery (2026-08-05 实测)
Symptom: console status bar shows red error for every poll of `https://domain/api/relay/status`; `curl https://domain/api/relay/status` returns EMPTY body / HTTP 000.

Diagnostic ladder (each step narrows it):
1. `curl -s -o /dev/null -w "%{http_code}" https://domain/` → 000 + `getent hosts domain` resolves + `ping <ECS-IP>` OK (29ms) = **host alive, web layer dead** (nginx or 443 listener gone). GitHub 200 rules out local network.
2. SSH in: `systemctl status nginx` → `inactive (dead)`. `ss -tlnp | grep :443` → **no 443 listener at all**; `ps aux | grep '[z]max_relay'` → empty (relay died too — it was started via setsid but nothing supervises it, so a reboot/nginx crash takes both down).
3. **⚠️ Dual nginx installs on 宝塔 (BT Panel) hosts — the #1 trap**: systemd nginx (`/usr/sbin/nginx`) loads `/etc/nginx/conf.d/*` + `sites-enabled/` — it does NOT load the BT vhosts at `/www/server/panel/vhost/nginx/*.conf`. `systemctl start nginx` reports `active` but the site config (listen 443 ssl, all `/api/relay/` locations) never loads → still no 443 listener. BT runs its OWN binary: `/www/server/nginx/sbin/nginx` with conf at `/www/server/nginx/conf/nginx.conf`. **Start BT's nginx, not systemd's**: `pkill -f 'nginx: master'` (separate call), then `/www/server/nginx/sbin/nginx`.
4. If BT nginx fails with `[emerg] bind() to 0.0.0.0:443 failed (98: Address already in use)` — another nginx instance (the systemd one you started) still holds the port. Kill ALL masters first, then start BT's.
5. `nginx -t` PASSING does not guarantee startup: `duplicate location` errors in `/www/server/nginx/logs/error.log` may be STALE from older config versions — grep the CURRENT conf (`grep -n '<pattern>' /www/server/panel/vhost/nginx/<domain>.conf`) before assuming the config is broken.
6. Restart relay via its start.sh (`bash start.sh` inside the project dir — pkill + setsid + verify in one script). Then verify ALL layers: local `curl http://127.0.0.1:39053/status` → JSON; public `curl https://domain/api/relay/status` → same JSON; homepage 200.
7. Console self-heals on the next poll cycle (~5s) — no control-console restart needed once the endpoint responds.

Prevention note: nothing supervises relay/nginx on the ECS — a reboot or crash leaves both down silently. If the user accepts a watchdog, the recovery script (nginx BT-binary start + `bash start.sh`) is the candidate body.

## References
- `references/host-down-vs-service-down-triage.md` — 整站不可达: 实例停机 vs web 层死的判据表 + 可直接复用的取证命令 + 「它真的重启了吗 / 服务自愈了吗」的判据
- `references/zmax-relay-deploy.md` — Z-MAX deployment specifics (endpoints, nginx block, client scripts, bug history)
- `references/websocket-relay.md` — WS 状态中转实测: ws_relay.py 广播 hub + Orin WS主/HTTP兜底 + 路径别名坑 + 验证步骤
- `references/zmax-ws-event-loop.md` — WS 事件驱动闭环实测 (2026-08-03): data_arrived 事件广播 (notify:8766→hub) + auto_loop.py v2 订阅端 + /command 采集指令端点 + 三个新坑 (/status mtime 排序 / 二进制包 frames=? / 远程补丁吞函数头)
