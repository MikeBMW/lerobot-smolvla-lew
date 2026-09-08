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
- **pkill bracket trick `[z]` still fails when the SAME ssh command also starts the service (2026-08-03 实测)**: `pkill -f '[z]max_relay'` alone works (exit 0), but `pkill ... ; sleep 1; setsid nohup python3 zmax_relay.py ...` in one ssh command → exit 255, because pkill ALSO matches the `python3 zmax_relay.py` text inside its own bash -c command line. Fix: kill in ONE ssh call, start in a SEPARATE call, or put both in a start.sh on the host and run `bash start.sh`.

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
- `references/zmax-relay-deploy.md` — Z-MAX deployment specifics (endpoints, nginx block, client scripts, bug history)
- `references/websocket-relay.md` — WS 状态中转实测: ws_relay.py 广播 hub + Orin WS主/HTTP兜底 + 路径别名坑 + 验证步骤
- `references/zmax-ws-event-loop.md` — WS 事件驱动闭环实测 (2026-08-03): data_arrived 事件广播 (notify:8766→hub) + auto_loop.py v2 订阅端 + /command 采集指令端点 + 三个新坑 (/status mtime 排序 / 二进制包 frames=? / 远程补丁吞函数头)
