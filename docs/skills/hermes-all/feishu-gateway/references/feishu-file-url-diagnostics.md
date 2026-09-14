# Feishu File URL Diagnostics

> How to handle user-shared Feishu file URLs that the bot cannot access.

## URL Patterns

| Pattern | Type | Bot Access? |
|---------|------|-------------|
| `dataworld.feishu.cn/file/<token>` | Uploaded file (PDF, image, docx) | ❌ Requires user-level auth |
| `dataworld.feishu.cn/slides/<token>` | Feishu presentation | ❌ Requires user-level auth |
| `dataworld.feishu.cn/docs/<token>` | Feishu document | ❌ Requires user-level auth |
| `dataworld.feishu.cn/sheets/<token>` | Feishu spreadsheet | ❌ Requires user-level auth |

## API Response Signatures

When the bot's tenant_access_token tries to access a user's personal file:

### drive/v1/metas/batch_query

```json
// File not shared with bot
{"code": 0, "data": {"metas": []}}
// Code is 0 (success) but empty metas — confusing! Means no access.
```

### drive/v1/files/{token}

```
HTTP 404 — File not found from bot's perspective
```

### docx/v1/documents/{token}

```json
{"code": 1770002, "msg": "not found"}
```

### Web request (browser-style)

Redirects to login page:
```
https://accounts.feishu.cn/accounts/page/login?...redirect_uri=...
```

## What DOES work

1. **File shared in a group chat** — If a user uploads a file to a group where the bot is a member, the bot receives the `im.message.receive_v1` event with the file message. The bot can then download the file using the `im/v1/messages/{message_id}/resources/{file_key}` endpoint.

2. **File sent directly to bot via DM** — Same as group chat, the bot receives the message event.

3. **File in a shared space** — If the file is in a Feishu "shared space" that the bot application has been granted access to.

## Standard User-Facing Message

```
这个文件在你的个人空间里，机器人（xspace）没有访问权限。
请把这个文件发到群里面，我就能收到了。
或者直接把内容贴过来也行。
```

## Diagnostic Checklist

When user says "你怎么不回答？" after sharing a file:

1. ✅ Is the gateway running? → `hermes gateway status`
2. ✅ Is Feishu WebSocket connected? → Check `grep "feishu" ~/.hermes/logs/gateway.log`
3. ✅ Is the bot in the target group? → `GET /open-apis/im/v1/chats` with tenant_access_token
4. ✅ Is the file in a group chat or user personal space? → Ask the user where the file lives
5. ⛔ Bot CANNOT access user personal files — this is a design limitation, not a bug
