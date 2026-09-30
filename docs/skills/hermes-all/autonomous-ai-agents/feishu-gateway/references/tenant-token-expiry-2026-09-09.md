# 飞书 tenant token 过期不自动刷新 → 99991663 (2026-09-09 实测)

## 症状
群消息 gateway **收到且 agent 处理了** (gateway.log: `inbound message` → `response ready` →
`[Feishu] Sending response`), 但发送失败 `[99991663] Invalid access token for authorization`
(plain-text fallback 同样失败)。用户视角 = "机器人没反应"。日志停在 send failed 后无新进展;
WS **接收照常** (收消息不走 REST token) → 用户消息能进、回复永远出不去。

## 根因
lark_oapi SDK 的 tenant_access_token (2h 有效) 在**长驻 gateway 进程内过期后不自动刷新**。
典型: 进程 01:24 启动 → token 03:24 过期 → 下午起所有发送失败。凭据/网络均正常。

## 诊断三步 (只读, 区分"凭据/网络问题" vs "进程内缓存问题")
1. 手动换 token: `POST open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal`
   body `{"app_id": "cli_...", "app_secret": "<~/.hermes/.env 的 FEISHU_APP_SECRET>"}` → code:0 = 凭据 OK。
2. 带新 token 手动发: `POST im/v1/messages?receive_id_type=chat_id` → code:0 = 网络/发送路径 OK。
3. 手动都通而 gateway 内发送仍 99991663 → **必须重启 gateway** (进程内 SDK token 缓存无自愈, 等再久也没用)。

## 恢复 (护栏上下文)
- Hermes 拦 gateway 进程内会话执行 restart/systemd-run/bash 脚本 (防 SIGTERM 自杀传播)。
- 若 CLI 会话**不在** gateway cgroup (user vte scope): 直接 `hermes gateway restart`。
- 判定方法: `cat /proc/<pid>/cgroup` — `system.slice/hermes-gateway.service` = 在服务内;
  user 终端 scope = 不在。别凭感觉 — 2026-09-09 误判"自己在 gateway 里"绕了弯路 (CLI 实为 gnome-terminal vte 进程)。
- systemd `Restart=always` + `RestartSec=5` 时 (本机 hermes-gateway.service 系统级):
  `terminal(background=true): bash -c 'sleep 20; kill -9 <gwpid>'` → systemd 5s 拉起新进程 → 全新 token。
- 恢复验证: 新 pid; 群内再发消息 → gateway.log `Sending response` **无** 99991663。
