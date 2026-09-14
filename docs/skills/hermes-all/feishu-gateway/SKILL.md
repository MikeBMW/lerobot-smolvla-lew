---
name: feishu-gateway
description: "Set up Feishu/Lark gateway for Hermes Agent from scratch."
version: 1.0.0
author: Hermes Agent
tags: [feishu, lark, gateway, websocket, hermes-setup, platform-config]
---

# Feishu Gateway Setup for Hermes Agent

Use when: A fresh Hermes Agent install needs Feishu/Lark connectivity — no prior config exists, `.env` has no FEISHU vars, and `platforms.feishu` is not in `config.yaml`. This covers the **fresh-install setup** path, distinct from troubleshooting an existing connection.

> For **troubleshooting** an existing Feishu gateway that's failing, load the `hermes-feishu-troubleshooting` skill from the repo's `docs/skills/shared/` directory.

## Prerequisites

Before starting, you need from the user:
- **FEISHU_APP_ID** — e.g. `cli_a87851ffe46b500d`
- **FEISHU_APP_SECRET** — The corresponding secret string

The user must also have:
- Created a Feishu app at [open.feishu.cn](https://open.feishu.cn)
- Enabled **Bot capability** in the app
- Granted permissions: `im:message`, `im:message:send_as_bot`, `im:resource`, `im:chat`, `im:chat:readonly`
- Subscribed to event `im.message.receive_v1` (WebSocket mode)
- Published the app (permissions only take effect after publishing)

## Setup Procedure

### Step 1 — Install dependencies

Hermes's Feishu adapter needs `lark-oapi`. The Hermes venv uses `python -m pip` (not pip from the system).

```bash
# Check if already installed
~/.hermes/hermes-agent/venv/bin/python -c "import lark_oapi; print('OK')" && \
  ~/.hermes/hermes-agent/venv/bin/python -c "import websockets; print('OK')"

# Install lark-oapi if missing
~/.hermes/hermes-agent/venv/bin/python -m pip install lark-oapi
# websockets is usually bundled with Hermes already
```

**Key trap**: Do NOT use `pip3 install` (installs to system Python, Hermes won't see it). Do NOT use the venv's own `pip` (it doesn't exist — the venv was created by `uv`). Use `/path/to/hermes/venv/bin/python -m pip install`.

### Step 2 — Configure environment variables

Add Feishu credentials and gateway settings to `~/.hermes/.env`:

```bash
cat >> ~/.hermes/.env << 'ENVEOF'

# Feishu Gateway
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=secret_xxx
FEISHU_DOMAIN=feishu
FEISHU_CONNECTION_MODE=websocket
FEISHU_ALLOW_ALL_USERS=true
GATEWAY_ALLOW_ALL_USERS=true
ENVEOF
```

**Variable reference:**

| Variable | Required | Value | Purpose |
|----------|----------|-------|---------|
| `FEISHU_APP_ID` | ✅ | `cli_xxx` | Feishu app ID from open platform |
| `FEISHU_APP_SECRET` | ✅ | `secret_xxx` | Feishu app secret |
| `FEISHU_DOMAIN` | ✅ | `feishu` or `lark` | `feishu` for China, `lark` for international |
| `FEISHU_CONNECTION_MODE` | ✅ | `websocket` or `webhook` | `websocket` is preferred for real-time |
| `FEISHU_ALLOW_ALL_USERS` | ❌ | `true` or `false` | Allow all Feishu users to send messages to the bot |
| `GATEWAY_ALLOW_ALL_USERS` | ❌ | `true` or `false` | Allow all gateway users (superset of FEISHU_ALLOW_ALL_USERS) |
| `FEISHU_ALLOWED_USERS` | ❌ | `ou_xxx,ou_yyy` | Comma-separated open IDs for white-list (also needed for approval card clicks) |

**⚠️ Critical distinction**: `GATEWAY_ALLOW_ALL_USERS=true` only opens **message receiving**. The **command approval card click** event uses a separate authorization path that still requires `FEISHU_ALLOWED_USERS`. If a user can message the bot but gets `[Feishu] Unauthorized approval click` when tapping an approval card, add their `open_id` (from error logs) to `FEISHU_ALLOWED_USERS`.

### Step 3 — Enable the Feishu platform

```bash
# This adds platforms.feishu.enabled: true to config.yaml
hermes config set platforms.feishu.enabled true

# Verify
grep -A3 'feishu' ~/.hermes/config.yaml
# Expected:
#   feishu:
#     enabled: true
```

**Why this step matters**: Without `platforms.feishu.enabled: true`, the Feishu adapter is never loaded and `check_fn` returns `False` — the gateway starts but Feishu tools silently don't appear.

### Step 4 — Start the gateway

```bash
# Run in background (for long-lived connections)
hermes gateway run
```

This is a long-lived process (server/daemon pattern). Do NOT use foreground `&` — use `terminal(background=true)`.

### Step 5 — Verify the connection

Wait 5 seconds then check the logs:

```bash
sleep 5
grep -i "feishu\|connected" ~/.hermes/logs/gateway.log
```

**Success signals:**
```
[Feishu] Connected in websocket mode (feishu)
✓ feishu connected
Gateway running with 1 platform(s)
```

**Failure patterns:**

| Log message | Likely cause | Fix |
|-------------|--------------|-----|
| No Feishu lines at all | Platform not enabled | Re-check Step 3 |
| `ModuleNotFoundError: No module named 'lark_oapi'` | Dep missing | Re-check Step 1 |
| `Failed to connect` / `WebSocket error` | Wrong App ID/Secret, or app not published | Verify credentials, publish app in Feishu console |
| `[Feishu] Unauthorized approval click` | User's open_id not in ALLOWED_USERS | Add to `FEISHU_ALLOWED_USERS` |
| `check_fn _check_feishu returned False` | Platform not enabled or dep missing | Check Steps 1 + 3 |

## Verifying Message Flow (Beyond Connection)

After the gateway logs "✓ feishu connected", verify the bot can **actually receive and send messages**. Connection ≠ delivery.

### Check which groups the bot is actually in

The bot only receives messages from groups it is a member of:

```bash
TOKEN=$(curl -s -X POST 'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal' \
  -H 'Content-Type: application/json' \
  -d '{"app_id":"cli_xxx","app_secret":"secret_xxx"}' | \
  python3 -c "import sys,json; print(json.load(sys.stdin).get('tenant_access_token',''))")

curl -s "https://open.feishu.cn/open-apis/im/v1/chats?page_size=20" \
  -H "Authorization: Bearer $TOKEN" | \
  python3 -c "
import sys,json
d=json.load(sys.stdin)
for i in d.get('data',{}).get('items',[]):
  print(f'chat_id={i[\"chat_id\"]} | name={i[\"name\"]} | members={i.get(\"member_count\",\"?\")}')
"
```

If the target group doesn't appear, the bot **is not a member** and won't receive messages.

### Why bot is connected but not replying

| Symptom | Likely cause | User translation |
|---------|-------------|------------------|
| ✓ connected but no messages arrive | Bot not in target group | 机器人没进群 |
| Bot in group but ignores messages | `im.message.receive_v1` not subscribed | 飞书开放平台没勾选事件 |
| All messages fail silently | App not published | 权限只在发布后生效 |
| Bot receives DM but not group msgs | Bot added via user-link, not group settings | App links add PEOPLE; bots need Group→Robots→Add |
| Bot IS in group, DM works, but group @-mentions never answered | Group message receive not effective in open platform: `im.message.receive_v1` event not re-saved / version not re-published (permissions may show as granted but events still don't fire) | Re-save/add `接收消息 im.message.receive_v1` in 事件订阅 + create & publish new version |
| **DM works, group never replies, subscription CONFIRMED present (user says "之前能回复，崩溃恢复后就不行了")** | **Local admission gate: `FEISHU_GROUP_POLICY` unset → defaults to `allowlist`; empty `FEISHU_ALLOWED_USERS` → ALL group messages rejected in-adapter with only a DEBUG log line** | **Add `FEISHU_GROUP_POLICY=open` (or populate `FEISHU_ALLOWED_USERS`) to `~/.hermes/.env`, then restart gateway from a SEPARATE shell** |

**Key**: App invite links (`applink.feishu.cn/client/chat/chatter/add_by_link?link_token=...`) invite people, not bots. Bots must be added via **Group Settings → Robots → Add Robot**. When added correctly, the gateway logs `[Feishu] Bot added to chat: oc_xxx`.

### ⚠️ DM works but group @-mentions never answered — full evidence chain

**FIRST: check the LOCAL admission gate before touching the open platform.** Proven 2026-08-01: bot in group, real @-mention, subscription confirmed on open.feishu.cn, DM flows — yet group events died. Root cause was 100% local: `~/.hermes/.env` lost `FEISHU_GROUP_POLICY` in a crash recovery, and the adapter defaults it to **`allowlist`**. With `FEISHU_ALLOWED_USERS` empty, `_allow_group_message()` returns False for every group message → `_admit()` returns `group_policy_rejected` → **only a DEBUG log line**, invisible in gateway.log. DMs keep working because `FEISHU_ALLOW_ALL_USERS=true` bypasses the gate for p2p.

Local-gate checklist (do these before the API chain below):
1. `grep -E "FEISHU_GROUP_POLICY|FEISHU_ALLOWED_USERS|FEISHU_ALLOW_ALL_USERS" ~/.hermes/.env` — missing policy var = the bug. **After any crash recovery, verify these survived** (recovery often rebuilds .env from a template that omits them).
2. Fix: `echo 'FEISHU_GROUP_POLICY=open' >> ~/.hermes/.env` (or `FEISHU_ALLOWED_USERS=ou_xxx` for a whitelist).
3. Restart gateway **from a separate shell** — `hermes gateway restart` cannot run from inside the gateway process (SIGTERM propagates; Hermes blocks it with "cannot restart or stop the gateway from inside the gateway process"). Use `systemd-run` (root), a one-shot cron entry, or ask the user to run it.
4. Re-test with a fresh group @-mention, then `grep -i "Inbound" ~/.hermes/logs/gateway.log`.

Only if the env gate is confirmed open/allowlisted AND the user's open-id is allowed do you proceed to the open-platform evidence chain below.

**Open-platform evidence chain** (use only after the local gate is ruled out):

This is the tricky case: bot is confirmed in the group, user correctly @-mentions it, gateway is online, DM messages flow — yet group events never arrive. **Do NOT assume the bot-add method is wrong; verify with the open-platform API first.**

Evidence chain (each step either confirms or rules out a cause):

1. **Check gateway log for group events**: `grep -i "Inbound" ~/.hermes/logs/gateway.log` — if only DM chat_ids appear and the group's `oc_xxx` never shows, events are not being pushed at all (server-side issue, not gateway code).
2. **Confirm bot membership**: `GET /open-apis/im/v1/chats` — group must appear in the list. (Rules out "not in group".)
3. **Confirm the user really @-mentioned the bot**: `GET /open-apis/im/v1/messages/{message_id}` — inspect `mentions[]`: `name` must equal the bot name (e.g. `xspace`) and `id` is the bot's open_id. Text containing "静静" without a real mention doesn't trigger events. (Rules out "wrong @".)
4. **Check what the app actually subscribes to**: `GET /open-apis/application/v6/applications/{app_id}?lang=zh_cn` — look at `callback_info.subscribed_callbacks`. If it lists only `card.action.trigger` (card events) and NOT the message receive event, the group-message subscription is not effective server-side. Also confirm scopes include `im:message.group_at_msg:readonly` / `im:message.group_msg`.
5. **Compare against a working bot in the same group** (e.g. another app's bot): if the other bot receives & replies to group messages, the group itself is fine — the difference is per-app event subscription config.
6. **Send-path sanity check**: `POST /open-apis/im/v1/messages?receive_id_type=chat_id` with the group chat_id — if sending works but receiving doesn't, it's purely the receive-side subscription.

**Fix** (user-side, 2 min on open.feishu.cn): 事件订阅 → add/re-save `接收消息 im.message.receive_v1` → confirm `获取群组中用户@机器人消息` permission granted → **创建版本并发布** (permissions/events only take effect after publishing a new version). Then have the user @ the bot in the group again and re-check step 1.

Full working command sequence (token + all 4 API calls): see `references/group-receive-debugging.md`.

### Proactive send test

```bash
TOKEN=$(curl -s -X POST 'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal' \
  -H 'Content-Type: application/json' \
  -d '{"app_id":"cli_xxx","app_secret":"secret_xxx"}' | \
  python3 -c "import sys,json; print(json.load(sys.stdin).get('tenant_access_token',''))")

curl -s -X POST "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"receive_id":"oc_xxx","msg_type":"text","content":"{\"text\":\"🤖 Gateway test: bot is online\"}"}'
```

### When user says "你怎么不回答？" / "你得回复啊"

1. Check group membership (chat list API)
2. Verify `im.message.receive_v1` is subscribed AND app is published
3. Restart gateway (WebSocket reconnection clears stale state)
4. Tell the user the specific action needed, not just the technical limitation

## Gateway Lifecycle Management

```bash
# Check if gateway is running
hermes gateway status

# Stop the gateway
hermes gateway stop

# Restart (hot reload)
hermes gateway restart

# View full logs
cat ~/.hermes/logs/gateway.log | tail -50

# Persistent run (survives terminal close)
tmux new -s hermes 'hermes gateway run'
```

### "飞书又不好使了" — gateway 进程死了 (2026-08-02 实测)

**症状**: 群里发消息无响应, 但 `~/.hermes/logs/gateway.log` 最后写入时间已停滞 (无新日志)。

**诊断顺序**:
1. `ls -lt ~/.hermes/logs/gateway.log` — 时间戳停滞 = gateway 已死或断连
2. `ps aux | grep "gateway run"` — 无进程 = gateway 进程根本没在跑 (日志文件时间戳 + 进程双重确认)
3. `cat ~/.hermes/logs/gateway-exit-diag.log` — 显示历史启动是独立进程 (`hermes gateway run`, stdin_is_tty:false), 证明 gateway 不是主 CLI 进程的一部分, 崩溃/重启后不会自动拉起

**根因**: gateway 是**独立守护进程**, 手动启动后无人监管 — WSL 重启、进程被杀后不会自愈。这是"又不好使"反复出现的真正原因 (区别于 .env 丢 FEISHU_GROUP_POLICY 的群拦截问题)。

**即时修复**: `~/.local/bin/hermes gateway run --replace` (background=true)。`--replace` 会替换任何现有实例 — 从 CLI 会话直接跑没问题, 因为 CLI 会话不是 gateway 进程。验证: 日志出现 `[Feishu] Connected in websocket mode` + `✓ feishu connected`。

**根治 — systemd 用户服务 (Restart=always, 崩溃/开机自动拉起)**:

```bash
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/hermes-gateway.service << 'EOF'
[Unit]
Description=Hermes Agent Gateway (Feishu/Telegram/etc)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/home/<user>/.local/bin/hermes gateway run --replace
Restart=always
RestartSec=5
Environment=HOME=/home/<user>
WorkingDirectory=/home/<user>

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload && systemctl --user enable --now hermes-gateway
systemctl --user status hermes-gateway --no-pager
```

- `ExecStart` 必须带 `--replace`, 否则 systemd 启动与手动实例并存会出问题; 换用 systemd 管理后手动起的旧实例会被自动替换
- systemd 拉起后 gateway 日志仍写 `~/.hermes/logs/gateway.log`, 验证方式不变
- 注意: 直接跑 `~/.hermes/hermes-agent/hermes` (源码入口) 会用系统 python 报 `ModuleNotFoundError: No module named 'dotenv'` — 必须用 `~/.local/bin/hermes` 启动器 (它走 venv)

### "飞书又不好使了" — systemd 时代排查 (2026-08-05 实测, WSL 重启后)

systemd 服务接管后 (Restart=always), WSL/OS 重启时 gateway **会自动拉起** — 大部分"飞书又不好使"是用户检查时服务刚重启/连接未建立, 不是故障。诊断顺序 (全只读, 30 秒):

1. `systemctl --user is-active hermes-gateway` → active; 再看 `systemctl --user status hermes-gateway` 的 `Active: active (running) since <时间>` — since 是刚重启的系统时间 = WSL 刚重启过, 服务已自动恢复。
2. `journalctl --user -u hermes-gateway --since "10 min ago" | grep -c "connected to wss"` — ≥1 即健康; 连接行 `[Lark] connected to wss://msg-frontier.feishu.cn/ws/v2?...` = 在线。⚠️ **systemd 管理后日志走 journald, 不走 gateway.log** — 服务单元 `StandardOutput/StandardError=journal`, `ls -lt ~/.hermes/logs/gateway.log` 时间戳停滞是假象, 别据此判死。
3. `grep -E "^FEISHU" ~/.hermes/.env` — 确认 `FEISHU_GROUP_POLICY=open` / `FEISHU_ALLOW_ALL_USERS=true` 在重启后没丢 (崩溃恢复重建 .env 曾丢过, 见上方 evidence chain)。
4. **良性噪音别当错误**: 日志里 `receive message loop exit, err: sent 1000 (OK); then received 1000 (OK) bye` + `websockets.exceptions.ConnectionClosedOK` traceback = 进程终止时的正常 WS 关闭, 不是故障; 真正的失败 = journal 里压根没有 "connected to wss" 行。
5. systemd 在管时**不要手动再起一个 gateway 实例** (会与 systemd 实例抢 WS 连接) — 自愈交给 Restart=always; `hermes gateway run --replace` 手动补救只在 systemd 单元缺失/disabled 时用。

### 记忆同步: CLI 端更新后, 飞书端要强制刷新 (2026-08-09 实测)

用户说"飞书端记忆要同步"时的处理: CLI 和 gateway 同 profile 时记忆文件**本来就共享** — `~/.hermes/memories/MEMORY.md` + `USER.md` (无 `~/.hermes/profiles/` 目录 = default profile, 两边读写同一份, 无分叉)。`memory` 工具写入即时落盘, 但 **gateway 长驻进程的进行中会话不会热刷新已注入的记忆** — 飞书端静静表现得记忆旧 = 会话缓存, 不是文件不同步。

强制同步 = 重启 gateway (systemd 管): `systemctl --user restart hermes-gateway`, 新会话重新读记忆文件。验证: `systemctl --user is-active hermes-gateway` = active, 且 `~/.hermes/gateway_state.json` 中 `gateway_state=running` + `platforms.feishu.state=connected`。

注意: CLI 会话里可以放心重启 (CLI 不是 gateway 进程); 从飞书会话内部不行 (SIGTERM 传播, 见上文)。

## Known Limitations

### 🚫 Bot cannot access user's personal files

The Feishu bot (tenant_access_token) **cannot** access files, documents, or slides stored in a user's personal Feishu Drive space, even when a direct sharing URL is provided. This includes:

- `/file/` — uploaded files (PDFs, images, documents)
- `/slides/` — Feishu presentations
- `/docs/` — Feishu documents
- `/sheets/` — Feishu spreadsheets
- `/bitable/` — Feishu base tables

**Why**: The bot's token only has drive scope for resources shared with the bot application, resources in the bot's own space, or resources in a shared space the bot is a member of. User-owned personal files require user-level OAuth.

The `drive/v1/metas/batch_query` API returns `code: 0` with empty metas for inaccessible files — it succeeds silently but returns no data, which is confusing.

**Workaround**: Ask the user to post the file/document **in a group chat where the bot is a member**. The bot receives message events from group chats and can process attachments shared via the `im.message.receive_v1` event. Files shared directly to the bot via DM also work.

**Example user-facing response when user shares a Feishu link:**
```
这个文件在你的个人空间里，机器人没有访问权限。
请在飞书群里发一下，我就能收到了。
或者直接把内容贴过来也行。
```

### 🎯 Bot cannot view attendance, calendar, or other sensitive user data

The tenant_access_token also lacks user-level scopes (e.g., `attendance:attendance`, `calendar:calendar`). For any resource requiring `user_access_token`, the gateway needs a Feishu OAuth user authorization flow — which is not currently implemented in the Hermes Feishu adapter.

## Related Skills

- `multi-agent-project-recovery` — post-crash recovery (includes credential restore section)
- `hermes-agent` — configuring CLI, models, and general Hermes setup
- `github-auth` — restoring GitHub tokens alongside Feishu creds
