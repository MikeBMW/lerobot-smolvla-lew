# Cross-Agent Memory Synchronization

> How agents in a multi-agent project sync their memory via a shared repo after recovery or during normal operation.

## Scenario

In multi-agent projects (like Z-MAX with 静静/web/小芳), each agent maintains its own context and memory. After a crash recovery or during normal coordination, agents need to synchronize their understanding of:

- Project status and recent changes
- User preferences and corrections
- Partner agent's current focus
- Shared credentials and configuration

## The Sync Pattern

### Push Phase (sending agent)

The sending agent (e.g., web/PM) saves their memory to the shared repo:

```
backups/
├── memory_web.md        ← Web agent's full context dump
└── user_profile.md      ← User profile (CEO preferences, project rules)
```

Commit message format:
```
记忆备份，N 个 commits 已全部推送。你去共享 web的记忆，你要同步的控制GUI
```

### Pull Phase (receiving agent)

The receiving agent (e.g., 静静/chief engineer) pulls and reads:

```bash
git pull origin main
# Read the new files
cat backups/memory_web.md
cat backups/user_profile.md
```

### Key info to extract from partner's memory

| What to look for | Why it matters |
|---|---|
| Partner's current version/commit | Know if you're synced |
| User preferences and pet peeves | Don't repeat mistakes |
| Technical constraints found | Avoid known pitfalls |
| Workflow rules and protocols | Follow agreed processes |
| Credential/API info | Shared infrastructure |
| Blockers and dependencies | Know what the partner is waiting for |

### Integration Phase

After reading the partner's memory, the receiving agent should:

1. **Save key facts to persistent memory** — user preferences, project rules, partner status
2. **Sync their own deliverables** — e.g., update the control GUI (studio.py) with new understanding
3. **Report back** — confirm sync is complete so the partner knows

## Real-World Example: Z-MAX v1.0.5 Sync

After crash recovery, web agent pushed to `zmax-website`:

```
Commit: ecacf3f — 记忆备份，85 个 commits 已全部推送
Files created:
  backups/memory_web.md    (27 lines, 26 §-separated rules)
  backups/user_profile.md  (12 lines, 13 §-separated rules)
```

### Memory Format

Both files use `§` as a record separator (not newlines — each line is a complete, self-contained fact):

**memory_web.md example:**
```
工艺文档铁律: 绝对禁止编造数据...
§
dds-skill-master中D435已修复为D405...
§
CEO偏好(07-27最终): Z700品牌·首页禁技术参数·链接纯文本...
```

**user_profile.md example:**
```
用户信息分两类: (1)需执行的指令 (2)知识共享...
§
ComfyUI铁律v7: 回退78f0c92→Python统一改...
```

### Extracted Rules from web's Memory

| Rule | Applies to | Priority |
|---|---|---|
| "绝对禁止编造数据" — never fabricate specs/data | All docs | 🔴 Critical |
| "完成协议" — reply "完成" only, no explanation | All communication | 🟡 High |
| "不说'试试''应该'" | All communication | 🟡 High |
| "迭代不超过2轮" | All development | 🟡 High |
| "链接纯文本禁**" | Website/GUI | 🟢 Normal |
| "功能坏了直接说根因" | Bug reports | 🟡 High |
| "首页禁技术参数" | Website | 🟢 Normal |

### Sync Result

After reading web's memory, the receiving agent (静静/chief engineer):
1. Updated the GUI (studio.py) version to align
2. Applied the "完成协议" — reported only "完成" after sync
3. Noted the `notify.php` bug (getenv as string literal) to fix later
4. Updated Hermes persistent memory with all web-derived rules

## Pitfalls

| Pitfall | Consequence | Prevention |
|---|---|---|
| Assuming partner's memory is complete | Miss critical constraints | Ask user if there are more repos/agents |
| Only reading your own agent's directory | Miss the big picture | Read ALL `backups/` files from partner repos |
| Not saving partner's rules to Hermes memory | Forget next session | Explicitly `memory(action="add")` after reading |
| Overwriting partner's pushed changes | Version conflicts | Always `git pull` before `git push` |
| Ignoring §-separated format | Parse partner's memory as single blob | Split on `§` to get individual facts |
