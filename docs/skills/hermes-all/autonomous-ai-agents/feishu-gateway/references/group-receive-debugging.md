# Debugging "Bot doesn't reply in group" — working command sequence

Two incidents, both 2026-08-01, same symptom (xspace bot replies to DM but never answers
@-mentions in the `dataworld` group). **Incident 2 corrected incident 1's conclusion.**

- Incident 1 initial hypothesis: open-platform subscription broken (`subscribed_callbacks`
  showed only `card.action.trigger`) → user re-added `im.message.receive_v1` + published.
- **Incident 2 (the real root cause): local admission gate.** User confirmed the event was
  already subscribed. The `.env` had lost `FEISHU_GROUP_POLICY` in a crash recovery, so the
  adapter defaulted to `allowlist`; empty `FEISHU_ALLOWED_USERS` → every group message
  rejected in-adapter with only a DEBUG log line. Fix: `FEISHU_GROUP_POLICY=open` in `.env`
  + gateway restart from a separate shell.

Lesson: **when the user says "之前能回复，崩溃恢复后就不行了", suspect local config first**
— crash recovery rebuilds `.env` from templates that omit group-policy vars. Check the
local gate (section 0.5) before the open-platform API chain.

## 0. Get tenant_access_token

```bash
cd ~/.hermes
APP_ID=$(grep FEISHU_APP_ID .env | cut -d= -f2)
APP_SECRET=$(grep FEISHU_APP_SECRET .env | cut -d= -f2)
TOKEN=$(curl -s -X POST "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal" \
  -H "Content-Type: application/json" \
  -d "{\"app_id\":\"$APP_ID\",\"app_secret\":\"$APP_SECRET\"}" \
  | python3 -c "import sys,json;print(json.load(sys.stdin).get('tenant_access_token',''))")
```

## 0.5. LOCAL ADMISSION GATE — check this FIRST

```bash
grep -E "FEISHU_GROUP_POLICY|FEISHU_ALLOWED_USERS|FEISHU_ALLOW_ALL_USERS" ~/.hermes/.env
```

- `FEISHU_GROUP_POLICY` unset → adapter default is **`allowlist`** (adapter.py:
  `group_policy=os.getenv("FEISHU_GROUP_POLICY", "allowlist")`).
- allowlist + empty `FEISHU_ALLOWED_USERS` → `_allow_group_message()` returns False for
  ALL group traffic; `_admit()` returns `group_policy_rejected` **at DEBUG level** —
  invisible in gateway.log, and no "Received raw message" line ever appears.
- DM path bypasses the gate when `FEISHU_ALLOW_ALL_USERS=true` — hence "DM works, group dead".
- Fix: `echo 'FEISHU_GROUP_POLICY=open' >> ~/.hermes/.env`, restart gateway.
- Restart constraint: `hermes gateway restart` inside the gateway process is BLOCKED
  ("cannot restart or stop the gateway from inside the gateway process"). Restart from a
  separate shell: `systemd-run` (needs root), one-shot crontab entry, or ask the user.

## 0.6 「推送没到适配器」 vs 「到了但被门控丢了」

admission 的拒绝有两类，**都只写 DEBUG**，gateway.log 里一个字都没有，看着都像"网关死了"：

| 拒绝原因 | 触发条件 | 修法 |
|---|---|---|
| `group_policy_rejected` | `FEISHU_GROUP_POLICY` 缺失(=allowlist) + `FEISHU_ALLOWED_USERS` 为空 | 设 `FEISHU_GROUP_POLICY=open` |
| `bot_not_mentioned` | 策略已是 `open`，但这条消息没 @ 到本 app（群里默认 `require_mention=True`） | 用户 @ 机器人 / 走私聊 / 给该群配 `platforms.feishu.extra.group_rules` |
| `self_echo` / `self_ids_unknown` / `bots_disabled` | 回环、bot id 未解析出、`allow_bots` 策略 | 按需处理 |

**免日志判据（零配置，先跑这个）**: `~/.hermes/feishu_seen_message_ids.json` = `{"message_ids": {"om_…": <本机 epoch 秒>}}`。
去重发生在 admission **之前**，所以**被拒的消息也记在里面**；落盘发生在 disconnect（正常退出/重启都会写）。

```bash
python3 - <<'EOF'
import json, datetime
d = json.load(open('/home/ubuntu/.hermes/feishu_seen_message_ids.json'))['message_ids']
for k, v in sorted(d.items(), key=lambda x: -x[1])[:5]:
    print(datetime.datetime.fromtimestamp(v).strftime('%m-%d %H:%M:%S'), k)
EOF
```

读法: 让用户发一条 → 重启 gateway（强制落盘）→ 文件里**多了新 id** = 飞书推送链路通、问题在本地门控；
**一条都没多** = 事件根本没推到这台机器（会话不对 / 机器人不在该会话 / 应用未发布 / 长连接被别处占用）。

**看清拒绝原因（临时开 DEBUG，不碰 config.yaml）**:
```bash
sudo mkdir -p /etc/systemd/system/hermes-gateway.service.d
printf '[Service]\nExecStart=\nExecStart=/home/ubuntu/.hermes/hermes-agent/venv/bin/python -m hermes_cli.main gateway run -vv\n' \
  | sudo tee /etc/systemd/system/hermes-gateway.service.d/debug.conf
sudo systemctl daemon-reload && sudo systemctl restart hermes-gateway
sudo journalctl -u hermes-gateway --since '-5 min' --no-pager | grep -a 'dropping inbound event'
# 查完必删: sudo rm /etc/systemd/system/hermes-gateway.service.d/debug.conf
#           sudo systemctl daemon-reload && sudo systemctl restart hermes-gateway
```
同一份 journal 里 `[Lark] connected to wss://msg-frontier.feishu.cn/ws/v2?…` 顺带证明连的是 **feishu** 前沿
（不是 lark）——ESTAB 对端 IP 落在 43.254.x 不代表连错了域。

## 0.7 网关平台层状态（不重启）

```bash
python3 - <<'EOF'
import socket, json
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.settimeout(6)
s.connect('/home/ubuntu/.hermes/gateway.sock')
s.sendall(json.dumps({"verb": "status"}).encode() + b"\n")
print(s.recv(8192).decode()[:800])
EOF
```
键是 `verb`（用 `{"cmd":…}` 会回 `unknown verb: None` 并列出 supported_verbs）。
`platforms.feishu.state=connected` + `needs_attention=false` = 平台层健康；
⚠️ **它不代表入站事件在流动**，仍要用 0.6 的判据复核。

## 0.8 对账 API 容易读错的四点

- 聊天消息列表**包含人类发的消息**，不是只有机器人自己的：`sender.id_type=app_id` = 机器人，`open_id` = 人。
  所以"群最新一条的时间"可以直接当"用户到底发进来没有"的判据。
- `GET /open-apis/bot/v3/info` 取本 app 的 `app_name` / `open_id` —— 群里 @ 是否命中本 app 的比对基准
  （多机器人群里 @ 错机器人 = 本 app 收不到事件）。
- 时间窗查询用 `start_time` / `end_time`（**秒**，不是毫秒）+ `sort_type=ByCreateTimeAsc` 逐页翻；
  `create_time` 回的是**毫秒**，展示前要除 1000。
- 话题(topic)群的消息在 thread 容器里：thread 容器 id 必须从消息详情的 `thread_id` 拿（形如 `omt_…`），
  直接拿 `om_…` 当 `container_id_type=thread` 会回 `230001 invalid container_id`。

## 1. Is the gateway receiving ANY group events?

```bash
grep -iE "Inbound" ~/.hermes/logs/gateway.log | tail -20
```
- Only DM chat_ids → could be the local gate (0.5) OR server-side. Check 0.5 first.
- Note: gateway may have been DOWN at the time the user messaged the group — check
  log timestamps vs. message create_time. Reboot the check with a fresh group message.

## 2. Bot membership in group

```bash
curl -s "https://open.feishu.cn/open-apis/im/v1/chats?page_size=50" -H "Authorization: Bearer $TOKEN" \
  | python3 -m json.tool | grep -E "chat_id|name"
```
Group present → bot is in it. (If absent: add via 群设置 → 机器人 → 添加.)

## 3. Recent messages in the group + human-readable times

```bash
curl -s "https://open.feishu.cn/open-apis/im/v1/messages?container_id_type=chat&container_id=oc_XXX&page_size=10&sort_type=ByCreateTimeDesc" \
  -H "Authorization: Bearer $TOKEN" \
  | python3 -c "
import sys,json,time
d=json.load(sys.stdin)
for it in d.get('data',{}).get('items',[]):
    t=time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(it.get('create_time'))/1000))
    print(t,'|',it.get('message_id'),'|',it.get('sender',{}).get('sender_type'),it.get('sender',{}).get('id'))
"
```
Feishu timestamps are ms since epoch — always convert, don't eyeball.

## 4. Did the user actually @ the bot?

```bash
curl -s "https://open.feishu.cn/open-apis/im/v1/messages/{message_id}" -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```
Check `mentions[]`: `name` must be the BOT name (e.g. `xspace`), `id` = bot's open_id.
Text like "静静 @_user_1" with mentions.name=xspace = real mention. If mentions is empty,
no event fires — the fix is user-side (use proper @).

## 5. What is the app actually subscribed to?

```bash
curl -s "https://open.feishu.cn/open-apis/application/v6/applications/$APP_ID?lang=zh_cn" -H "Authorization: Bearer $TOKEN" \
  | python3 -c "
import sys,json
d=json.load(sys.stdin)['data']['app']
print('subscribed_callbacks:', d['callback_info'].get('subscribed_callbacks'))
for s in d.get('scopes',[]):
    if s['scope'].startswith('im:message') or 'group_at' in s['scope']:
        print(s['scope'],'|',s['description'][:40])
"
```
- `subscribed_callbacks` may show only `['card.action.trigger']` yet group messages still
  arrive (incident 2: subscription was fine; the local gate was the bug). Do NOT conclude
  "subscription broken" from this alone.
- Scopes confirmed present: `im:message.group_at_msg:readonly`, `im:message.group_msg`,
  `im:message:readonly`, `im:message.p2p_msg:readonly` → permissions OK.

## 6. Send-path sanity check

```bash
curl -s -X POST "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"receive_id":"oc_XXX","msg_type":"text","content":"{\"text\":\"静静在线，测试消息\"}"}'
```
code:0 → sending works; combined with step 1 (no inbound group events) this isolates
the failure to receive-side (local gate or subscription).

## Root cause & fix (this incident, corrected)

- **Real root cause: local.** `FEISHU_GROUP_POLICY` missing from `.env` after crash
  recovery → default `allowlist` → empty whitelist → `group_policy_rejected` at DEBUG
  level for every group message. DM unaffected (`FEISHU_ALLOW_ALL_USERS=true`).
- Fix: `echo 'FEISHU_GROUP_POLICY=open' >> ~/.hermes/.env` + restart gateway from a
  separate shell (not from inside the gateway process).
- Verification: user @-mentions bot in group again → `grep Inbound` shows group chat_id.
- If the local gate is open and group events STILL don't arrive, THEN do the open-platform
  fix: open.feishu.cn → 应用 → 事件订阅 → add/re-save `接收消息 im.message.receive_v1`
  → 权限管理 confirm `获取群组中用户@机器人消息` → 创建版本并发布.
