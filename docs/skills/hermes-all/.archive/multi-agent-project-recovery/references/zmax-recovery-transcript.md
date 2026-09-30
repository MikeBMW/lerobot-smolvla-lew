# Z-MAX Crash Recovery Transcript

> Real-world recovery session from 2026-07-28. Use as a template for future multi-agent project recoveries.

## Scenario

Hermes Agent crashed (system failure), all persistent memory wiped, agent reinstalled fresh. User ("老倪", Z-MAX product owner) provided the GitHub repo and said "系统崩了，我刚把你安装回来".

## Recovery Dialogue Flow

```
User: 静静，刚才你的系统崩了，我刚把你安装回来。
      https://github.com/MikeBMW/lerobot-smolvla-lew.git 这是你之前推送的项目，你来恢复一下记忆

Agent: [Cloned repo, started reading]

User: docs/memory 这里有你的记忆

Agent: [Found docs/memory/, read all memory files]

User: https://github.com/MikeBMW/zmax-website.git 这个是另一个智能体web维护的项目
      你也学习一下。之前你跟她配合搞项目的

Agent: [Cloned web repo, read WEB_AGENT_MEMORY.md, CHANGELOG.md]
```

## Files Read (in order)

### From lerobot-smolvla-lew/

1. `docs/memory/hermes-jingjing.md.archived` — Agent profile (name, role, user, project, hardware, style, key commands)
2. `docs/memory/shared-memory.md` — Team structure (3 agents), repos, servers, product architecture (5-layer engine), model params, naming conventions, web pages, ops notes
3. `docs/memory/sync.md` — Full shared knowledge: warehouse names, product system, version management, network topology, credentials, key file paths, design specs, collaboration protocols, supply chain, branch strategy
4. `docs/memory/task-board.md` — Current progress: 小芳 12/14 done, xspace 5/9 done, web 0/5 done
5. `docs/memory/xspace.md` — Complete agent profile: hardware (RTX4060 8G, i9-13900H, WSL2), training config, inference system, Feishu config, Mac partner details, website ops, design specs, 132 skill inventory
6. `docs/memory/xiaofang.md` — Partner agent (Mac M1) profile: Gateway setup, Orin connection, ECS tunnel
7. `docs/Z-MAX-SmolVLA训练方案.md` — VTLA training plan with 4 phases and hardware constraints
8. `docs/DEPLOY-READY.md` — Mac deployment pipeline status

### From zmax-website/

1. `WEB_AGENT_MEMORY.md` — Web agent full state: version v2.5.4, core pages, factory-3d coordinate system, Feishu bridge, todo items
2. `CHANGELOG.md` — Unified changelog v3.9 showing cross-agent work
3. `README.md` — Website structure, deploy instructions, ECS connection info
4. `deploy/deploy.sh` — Deployment script with credentials, nginx reload, WP version bump

## Key Context Recovered

### Three Agents
| Agent | Role | Host | Repo |
|-------|------|------|------|
| 静静 | Training/GUI/Inference/Website | WSL2 RTX4060 | lerobot-smolvla-lew |
| web | Cloud training/Frontend | AutoDL RTX4090 | zmax-website |
| 小芳 | Orin connection/ROS2/Tunnel | Mac Mini M1 | (mac branch) |

### Product Stack
- **Z-MAX** = Intelligent Model Engine (software)
- **Z700** = L4 autonomous robot (optical module factory)
- **SmolVLA-LEW** = SmolVLM2-500M + DiT-B + LeWorldModel (628M params)
- **5-layer engine**: Sys-0(L2 rules) → Sys-1(L3 ACT) → Sys-11/12(L4 smolvla) → Sys-2(cloud 4090)

### Phase Progress
- Phase 0 ✅ SmolVLA training, gRPC inference, GUI panel, Mac Gateway
- Phase 1 ✅ Orin integration, benchmarks, knowledge base
- Phase 2 🔄 GUI optimization, website animations, training stabilization

### Current Status
- Last commit: `a7788733` on main (both main and mac branches synced)
- Awaiting: GPU training from web agent, Orin data pipeline from 小芳

## Credential Restoration (Same Session)

After context recovery, the user re-supplied credentials:

### GitHub Token
```
User: github token,你还记得么？
Agent: [Checked .env, git-credentials — nothing found]
User: [REDACTED:github_token]  给你新建的
Agent: [Saved to .env, configured git credential helper, verified API call returns MikeBMW]
```

### Feishu Gateway
```
User: cli_a87851ffe46b500d   t7cCB8TV8kShW7D0hN3Txg3fMuEuu8jt  飞书凭证
Agent: [Installed lark-oapi, set env vars, enabled platform, started gateway, verified WebSocket connected]
```

## Memory Saved to Hermes

Two memory entries created after recovery:
- **User profile**: User is 老倪, ZFCY product lead, calls me 静静, prefers autonomous decisions
- **Agent memory**: Project recovery from crash, repos at two GitHub URLs, three-agent setup

## Feishu Gateway Debugging (Same Session)

After credential restoration, Feishu gateway connected but user reported no replies:

### Gateway Log Signals
```
[Feishu] Bot removed from chat: oc_c0b4048546145c5c581ddd1a9e8f565d
[Feishu] Bot added to chat: oc_c0b4048546145c5c581ddd1a9e8f565d
```
The bot was only in one group (`dataworld`). The target group `静界` was not accessible.

### Diagnostic Findings
- **API `GET /im/v1/chats` confirmed**: bot only in `dataworld` group
- **No `platform=feishu` sessions**: zero incoming messages received from Feishu
- **Root cause**: Bot had NOT been added to the target group via Group Settings → Robots → Add Robot. The user sent app invite links (`applink.feishu.cn/client/chat/chatter/add_by_link`) which invite PEOPLE, not bots.
- **Feishu file URLs** (`/file/` and `/slides/`) consistently returned empty metas or 404 — bot cannot access user personal files

### User Frustration Signals
| Signal | Context | Lesson |
|--------|---------|--------|
| "你得回复啊" | After connecting gateway, user expected immediate reply | Verify bot is IN the target group, not just connected |
| "你看看你为什么不回答？" | User tested group, got no response | Don't explain limitations alone — give user a concrete action: "请在群设置里添加机器人" |
