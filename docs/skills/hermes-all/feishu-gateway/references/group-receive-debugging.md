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
