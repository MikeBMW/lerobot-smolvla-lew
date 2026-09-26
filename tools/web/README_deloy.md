# datadrive.world 网页部署说明 (2026-09-26)

站点根 (ECS): `/www/wwwroot/datadrive.world/`  (nginx 反代, 页面首行都 `<script src="/auth.js">`)

## 本轮新增/改动的页面
| 页面 | 作用 | 入口 |
|---|---|---|
| `agent.html` | **🤖 Web 智能体桥 · 状态空间控制台** — 远程提示词 → ECS 中转 → 本机桥节点(只读白名单) → 回执 | 首页新增按钮 |
| `hil.html` | **🙋 HIL 人机在环** — 状态空间状态(分层/阶段/事件预测) + 人给工程的指示 | 首页新增按钮 |
| `index.html` | 首页插入两个入口按钮 (在原「数据闭环链路」按钮之前) | — |

## 部署方法 (本机 → ECS, 用 /tmp/ecs.sh 包装 ssh)
```bash
bash /tmp/ecs.sh "cp /www/wwwroot/datadrive.world/<页>.html /www/wwwroot/datadrive.world/<页>.html.bak_\$(date +%s)"
bash /tmp/ecs.sh "cat > /www/wwwroot/datadrive.world/<页>.html" < tools/web/<页>.html
curl -s -o /dev/null -w '%{http_code}\n' https://datadrive.world/<页>.html      # 期望 200
```

## 通道对应
- 网页 → 本机: `POST /api/relay/agent/prompt`  body `{text, from:"web_agent"|"hil_web", meta}`
- 本机 → 网页: `GET  /api/relay/agent/reply?after=N`  (回执带 `from` 区分来源: `L5 状态空间节点`=桥节点, `hil_bridge`=HIL)
- 状态上行(给 HIL/agent 页读): `POST/GET /api/relay/hil/state`
- 本机守护: `zmax-web-agent-bridge`(桥节点, 5s 轮询) · `zmax-hil-bridge`(HIL, 5s 上报+收指示)
