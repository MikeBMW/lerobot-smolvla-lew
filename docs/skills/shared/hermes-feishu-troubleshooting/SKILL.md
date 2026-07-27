---
name: hermes-feishu-troubleshooting
description: "Diagnose and fix Hermes Gateway Feishu/Lark connection failures — WebSocket and Webhook modes."
version: 1.0.0
author: agent
tags: [hermes, feishu, lark, gateway, websocket, troubleshooting]
platforms: [linux, macos]
---

# Hermes Feishu / Lark 连接故障排查

飞书/飞书国际版连接 Hermes 网关失败时的系统诊断和修复流程。涵盖 WebSocket（长连接）和 Webhook 两种模式。

## 触发条件

- 用户报告飞书/Lark 机器人连不上
- WebSocket 长连接失败
- 网关启动后飞书没反应
- 飞书工具 `check_fn` 返回 False

## 诊断流程（按顺序）

### 第一步：检查网关是否在运行

```bash
hermes gateway status
```

如果没运行，先跳到第五步启动。

### 第二步：检查依赖是否安装

飞书适配器需要 `lark-oapi` SDK。WebSocket 模式还需要 `websockets`。

```bash
# 找到 hermes 使用的 Python
head -5 ~/.local/bin/hermes
# 输出类似: exec "/Users/xxx/.hermes/hermes-agent/venv/bin/hermes"

# 用对应 venv 的 Python 检查
~/.hermes/hermes-agent/venv/bin/python -c "import lark_oapi; print('OK')"
~/.hermes/hermes-agent/venv/bin/python -c "import websockets; print('OK')"
```

**关键陷阱：Hermes 的 venv 里没有 pip**（venv 由 uv 创建）。安装依赖必须用 uv：

```bash
uv pip install --python ~/.hermes/hermes-agent/venv/bin/python lark-oapi
uv pip install --python ~/.hermes/hermes-agent/venv/bin/python websockets
```

不能用 `pip3 install`（装到全局 Python，hermes 用不到）也不能用 venv 里的 pip（不存在）。

### 第三步：检查 .env 凭证

```bash
grep "FEISHU" ~/.hermes/.env
```

必须有以下变量：

| 变量 | 说明 | 示例 |
|------|------|------|
| `FEISHU_APP_ID` | 飞书应用 App ID | `cli_xxx` |
| `FEISHU_APP_SECRET` | 飞书应用 App Secret | `secret_xxx` |
| `FEISHU_DOMAIN` | `feishu`（中国版）或 `lark`（国际版） | `feishu` |
| `FEISHU_CONNECTION_MODE` | `websocket` 或 `webhook` | `websocket` |

### 第四步：检查 config.yaml 是否启用了飞书平台

```bash
grep -A3 "platforms:" ~/.hermes/config.yaml | grep -A2 feishu
```

或查看飞书是否在可用平台列表中：

```bash
hermes gateway status
```

如果 config.yaml 中没有 `platforms.feishu.enabled: true`，需要添加：

```bash
hermes config set platforms.feishu.enabled true
```

没有这一步，飞书适配器不会被加载，`check_fn` 会一直返回 False，日志里能看到：

```
WARNING tools.registry: check_fn _check_feishu returned False
```

### 第五步：启动网关

```bash
# 前台运行（调试用，能直接看日志）
hermes gateway run

# 或后台运行
hermes gateway run &  # 不推荐，关终端就停

# 长期运行：安装为系统服务
hermes gateway install
```

启动成功后，日志中应该看到类似：

```
[Lark] [INFO] connected to wss://msg-frontier.feishu.cn/ws/v2?...
```

这条日志表示 WebSocket 长连接已成功建立。

### 第六步：查看错误日志

```bash
grep -i "feishu\|lark" ~/.hermes/logs/errors.log | tail -20
grep -i "feishu\|lark" ~/.hermes/logs/agent.log | tail -20
```

## 飞书开放平台端检查

如果 Hermes 这端都正常还连不上，检查飞书开放平台：

1. **机器人能力**：应用功能 → 机器人 → 开关打开
2. **权限**：权限管理 → 至少添加这 5 个：
   - `im:message`
   - `im:message:send_as_bot`
   - `im:resource`
   - `im:chat`
   - `im:chat:readonly`
3. **事件订阅**：选「使用长连接（WebSocket）」→ 订阅 `im.message.receive_v1`
4. **发布应用**：版本管理 → 创建版本 → 发布（权限在发布后才生效）

## 常见错误模式

| 错误现象 | 可能原因 | 修复 |
|----------|---------|------|
| `check_fn _check_feishu returned False` | config.yaml 未启用飞书平台 | `hermes config set platforms.feishu.enabled true` |
| `ModuleNotFoundError: No module named 'lark_oapi'` | SDK 未安装 | `uv pip install --python <venv_python> lark-oapi` |
| 网关启动了但没有任何飞书日志 | platform 未启用 + 依赖缺失 | 按诊断流程 2→4→5 逐步检查 |
| WebSocket 连不上 | 凭证错误 / 应用未发布 | 检查 .env 中的 App ID/Secret，确认应用已发布 |
| 消息收不到 | 权限不足 / 事件未订阅 | 检查飞书后台权限和事件配置 |
| 收到消息但机器人不回复 | 白名单拒绝了发送者 | 添加 `FEISHU_ALLOWED_USERS` 或 `GATEWAY_ALLOW_ALL_USERS=true` |
| 点击审批卡片被拒绝 | `FEISHU_ALLOWED_USERS` 不包含点击者 | 命令审批卡片点击走独立授权，必须把 open_id 加入 `FEISHU_ALLOWED_USERS` |
| `[Feishu] Unauthorized approval click` | 审批卡片点击者不在白名单 | `GATEWAY_ALLOW_ALL_USERS=true` 只放行消息接收，不覆盖卡片审批授权 |

## 白名单与授权陷阱

两个变量控制不同的授权路径，不能互相替代：

| 变量 | 控制范围 | 说明 |
|------|---------|------|
| `GATEWAY_ALLOW_ALL_USERS=true` | 消息接收 | 允许所有人发消息给机器人 |
| `FEISHU_ALLOWED_USERS=ou_xxx` | 消息接收 + 卡片审批 | 允许指定用户发消息 **且** 能点击审批卡片（Allow Once/Always/Deny） |

**关键发现**：`GATEWAY_ALLOW_ALL_USERS=true` 只放开消息接收，但命令审批卡片（command approval card）的点击事件走的是独立授权路径，仍然需要 `FEISHU_ALLOWED_USERS`。用户在飞书里看到审批卡片、点击「Allow Once」后报 `[Feishu] Unauthorized approval click by ou_xxx` 就是这个原因。

从错误日志中可以获取用户的 `open_id`（`ou_` 前缀），然后添加到白名单：

```bash
echo "FEISHU_ALLOWED_USERS=ou_d82fe4c9f90c4e9337235d04b2241070" >> ~/.hermes/.env
# 多个用户用逗号分隔
# 修改后需要重启网关: hermes gateway restart
```

## 网关生命周期

```bash
# 重启网关（会断掉当前连接再重新连）
hermes gateway restart   # 前台命令，会阻塞。建议放后台或用 &。

# 如果 restart 卡住（timeout），先杀掉再手动启：
hermes gateway stop
hermes gateway run &     # 后台运行

# 查日志确认飞书 WebSocket 是否连上
# 成功标志: [Lark] [INFO] connected to wss://msg-frontier.feishu.cn/ws/v2?...
# 如果连上但很久没有消息事件 → 问题在飞书平台端（事件订阅/发布）
```

## 相关文件

- Hermes 飞书适配器：`~/.hermes/hermes-agent/plugins/platforms/feishu/adapter.py`
- 飞书配置文档：`~/.hermes/hermes-agent/website/docs/user-guide/messaging/feishu.md`
- 环境变量：`~/.hermes/.env`
- 主配置：`~/.hermes/config.yaml`
