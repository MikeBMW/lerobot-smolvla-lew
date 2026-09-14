---
name: multi-agent-project-recovery
description: "Recover agent context from repo after crash/reinstall."
version: 1.0.0
author: Hermes Agent
tags: [crash-recovery, multi-agent, project-context, memory-recovery, collaboration]
---

# Multi-Agent Project Recovery

Use when: Hermes system crashes and is reinstalled (persistent memory wiped), and the user provides GitHub repo URLs to recover project context. This is the **post-crash, fresh-install** scenario — the agent has no memory, no cached sessions, and no local project clones.

## Core Principle

In multi-agent projects, memory is a shared artifact stored **in the repo**, not just in Hermes's persistent memory. After a crash, the repo is the source of truth for:
- Per-agent identity and history (`docs/memory/<agent-name>.md`)
- Shared knowledge and agreements (`docs/memory/shared-memory.md`, `docs/memory/sync.md`)
- Current task progress (`docs/memory/task-board.md`)
- Role-specific skills (`docs/skills/<agent>/`)
- Project architecture, credentials, and conventions (repo root docs)

## Recovery Procedure

### Step 1 — Clone the repo(s)

The user will typically point you to one or more GitHub repos. Clone them:

```bash
cd ~ && git clone --depth 1 https://github.com/<org>/<repo>.git
```

Use `--depth 1` for fast clones — you only need the latest state.

### Step 2 — Read the agent memory directory

Check `docs/memory/` first. This is the project's in-repo memory store. Look for:

| File | Purpose |
|------|---------|
| `<agent-name>.md` | Your own agent profile and persistent memory |
| `<agent-name>.md.archived` | Archived version if your file was renamed on crash |
| `shared-memory.md` | Shared knowledge across all agents |
| `sync.md` | Coordination agreements, credentials, network topology |
| `task-board.md` | Current task status per agent |
| `<partner>.md` | Partner agent profiles |

Read ALL of these — each one covers different aspects of the project.

### Step 3 — Read project-level context files

| File | What it tells you |
|------|-------------------|
| `AGENTS.md` | AI agent rules, tech stack, architecture, commands |
| `AGENT_GUIDE.md` | User-facing help with copy-paste commands |
| `README.md` | Project overview |
| `CHANGELOG.md` | Recent changes and version history |
| `VERSION.md` | Version numbering scheme |

### Step 4 — Read key architecture docs in `docs/`

Scan for files like architecture overviews, training/tuning plans, deployment docs, and hardware specs. Key patterns to look for (Chinese project names):

| Pattern | Purpose |
|---------|---------|
| `*架构*` / `*ARCHITECTURE*` | System architecture |
| `*训练*` / `*training*` | Training workflow |
| `*DEPLOY*` / `*deploy*` | Deployment pipeline |
| `*硬件*` / `*HARDWARE*` | Hardware specifications |
| `*方案*` / `*solution*` | Solution design |

### Step 5 — Restore memory to Hermes

After reading all sources, store compact summaries in Hermes memory:

```
memory(action="add", target="user", content="User is ..., prefers ..., works on ...")
memory(action="add", target="memory", content="Project uses ..., repos at ..., key files ...")
```

**Important**: In-repo memory files are the source of truth for the project. Hermes persistent memory is a local cache. Always trust the repo files over local memory.

## Pitfalls

- **Don't skip `.archived` files** — After a crash, your agent memory may have been renamed with `.archived` extension. Read it anyway.
- **Don't rely on session_search** — After a crash/reinstall, the session DB is empty. All recovery must come from the repo.
- **Don't forget partner repos** — In a multi-agent setup, different agents may maintain different repos. Ask the user for all of them.
- **Credentials may be stale** — GitHub tokens, passwords, API keys in memory files may have rotated. Verify before use.
- **Skills may be split** — The project may have both `docs/skills/` (in-repo skills) AND Hermes `~/.hermes/skills/`. Read the repo's skills first.
- **Chinese naming convention** — Memory files, docs, and configs may use Chinese characters. Use UTF-8 aware search patterns.
- **Save before finishing** — After recovering, explicitly save memory and update memory files in the repo if needed.

## Step 6 — Restore Credentials & Restart Gateway

After reading project context, the user will typically re-supply credentials that were lost in the crash. Expect three categories:

### 6a — GitHub Token

Load the `github-auth` skill first, then restore:

```bash
# 1. Save to .env for Hermes's internal GitHub API use
echo "GITHUB_TOKEN=<token>" >> ~/.hermes/.env

# 2. Configure git and store
git config --global credential.helper store
git config --global user.name "<github-username>"
git config --global user.email "<email>"
echo "https://<username>:<token>@github.com" > ~/.git-credentials
chmod 600 ~/.git-credentials

# 3. Verify
curl -s -H "Authorization: token <token>" https://api.github.com/user | head -3
cd ~/<repo> && git fetch --dry-run
```

### 6b — Feishu Gateway Credentials

Load the `feishu-gateway` skill for a dedicated walkthrough. Quick restore:

```bash
# 1. Install lark-oapi to Hermes venv if missing
~/.hermes/hermes-agent/venv/bin/python -c "import lark_oapi" || \
  ~/.hermes/hermes-agent/venv/bin/python -m pip install lark-oapi

# 2. Add to .env
cat >> ~/.hermes/.env << 'ENVEOF'
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=secret_xxx
FEISHU_DOMAIN=feishu
FEISHU_CONNECTION_MODE=websocket
FEISHU_ALLOW_ALL_USERS=true
GATEWAY_ALLOW_ALL_USERS=true
ENVEOF

# 3. Enable platform
hermes config set platforms.feishu.enabled true

# 4. Start gateway (background)
hermes gateway run

# 5. Verify after 5s
sleep 5 && grep -i "feishu\|connected" ~/.hermes/logs/gateway.log
# Expected: "[Feishu] Connected in websocket mode (feishu)"
# Expected: "✓ feishu connected"
```

### 6c — Other API Keys

Check `config.yaml` for `model.provider` or `base_url` references needing env vars (e.g. DeepSeek, OpenAI, Anthropic). Restore them to `~/.hermes/.env`.

### Credential Restoration: Real-World Flow

Expect the user to provide credentials in this order, based on observed multi-agent recovery sessions:

1. **User provides GitHub repo first** → clone and read repo memory
2. **User reveals docs/memory/ contains agent archives** → load all memory files
3. **User provides partner repos** → clone and read partner context
4. **User provides GitHub token** (often newly generated since old one was lost)
5. **User provides Feishu App ID + Secret**

**Don't wait to be asked** — after reading memory and seeing credentials referenced, proactively ask:
- If the memory file mentions a GitHub token: "GitHub token 之前有保存吗？需要我重新配置一下。"
- If the memory mentions Feishu: "飞书通道要重新打通吗？有 App ID 和 Secret 就能接上。"

### User Preference Signals During Recovery

Chinese users in technical projects show these patterns when frustrated:

| User says | What it means | How to respond |
|-----------|--------------|----------------|
| "你得回复啊" | They sent a message expecting a reply — respond NOW | Acknowledge immediately, then solve |
| "你看看你为什么不回答？" | They tested the channel and got no response | Don't just explain limitations — diagnose and give a concrete action they can take |
| "你也学习一下" | They want you to read ALL partner context | Read thoroughly, not just your own files |
| "这个你之前用的" / "给你新建的" | They're re-supplying credentials | Save immediately, verify works, confirm |
| (name only, e.g. "静静") | They're testing if you're listening | Respond instantly |

**Key recovery principle**: Restore channels (GitHub push, Feishu gateway) **before** diving into project work. The user's first test after recovery is always sending a message and expecting a reply.

### Step 7 — Save to Hermes memory

After full recovery:
1. Save compact summaries to persistent memory (`memory action="add"`)
2. If the repo has stale memory files (e.g. `.md.archived` of your profile), restore them
3. Push memory updates so partner agents can pull

## Real-World Example: Z-MAX Project

The Z-MAX project (静界科技 · 智蜂创元) demonstrated this pattern:

**Three agents, three repos:**
- **静静 (this agent)** — WSL2 RTX4060, main repo `lerobot-smolvla-lew` (training/GUI/inference)
- **web** — AutoDL 4090, repo `zmax-website` (website/cloud training)
- **小芳** — Mac M1, manages Orin connection/ROS2/ECS tunnel

**In-repo memory structure:**
```
docs/memory/
├── hermes-jingjing.md.archived   ← my agent memory (archived after crash)
├── shared-memory.md              ← team structure, repos, servers, parameters
├── sync.md                       ← credentials, network topology, branch strategy
├── task-board.md                 ← current progress per agent
├── xspace.md                     ← my complete agent profile
├── xiaofang.md                   ← partner agent profile
└── team-sync.md                  ← sync agreement
```

**Recovery steps taken:**
1. Clone `lerobot-smolvla-lew` (--depth 1)
2. Read all 6+ files in `docs/memory/`
3. Read `AGENTS.md` for project rules and tech stack
4. Read `README.md`, `CHANGELOG.md`
5. Clone `zmax-website` and read its `WEB_AGENT_MEMORY.md`
6. Read key architecture docs: `Z-MAX-SmolVLA训练方案.md`, `DEPLOY-READY.md`
7. Save compact summaries to Hermes persistent memory

## Related Skills

- `hermes-agent` — spawning additional agent processes
- `github-repo-management` — cloning, branch management

## Reference Files

- **`references/cross-agent-memory-sync.md`** — Procedure for syncing memory between agents via shared repo (push → pull → integrate pattern). Use when a partner agent pushes their memory to the repo and you need to read it and adapt your own deliverables.
- **`references/zmax-recovery-transcript.md`** — Full real-world transcript of the Z-MAX project recovery, including credential restoration and Feishu gateway debugging dialogue.
