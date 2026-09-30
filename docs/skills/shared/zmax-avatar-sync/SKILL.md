---
name: zmax-avatar-sync
description: "Sync identity and memory files between 小芳 (Mac M1) and xspace/静静 (WSL2) avatars via shared git repo with branching strategy and PR workflow."
version: 2.0.0
author: 小芳
tags: [zmax, avatar, sync, git, multi-agent, feishu, branching, pr-workflow]
---

# Z-MAX Avatar Sync Protocol (v2)

Two Hermes Agent instances (小芳 + xspace/静静) collaborate on the Z-MAX project through a shared git repo (`MikeBMW/lerobot-smolvla-lew`). They use `docs/memory/` to maintain identity and memory files that each avatar reads to understand the others' state.

**v2 Key Changes from v1:**
- 2 avatars: xspace/静静 (same entity, WSL2) and 小芳 (Mac M1)
- Branching strategy: xspace guards `main`, 小芳 works on `mac` branch
- PR workflow: all merges to main go through xspace review
- New file: `shared-memory.md` for cross-avatar shared knowledge
- Archiving convention: merged/redundant profiles get `.archived` suffix, not deleted

## Trigger

Use this skill when:
- Creating or updating an avatar profile (`docs/memory/hermes-*.md`)
- Syncing state between any combination of avatars
- Setting up the sync protocol for a new avatar
- Working with git branches for avatar collaboration
- Submitting a PR from a feature branch to main (xspace review)
- Resolving git conflicts from concurrent edits

## Avatar Roles & Branching Strategy

```
main (xspace 守护)
  ↑ PR 审核 + 合并
  ├── mac (小芳: Mac端侧 + Orin远程操作)
  ├── ... (其他开发分支, e.g. 静静)
```

| Avatar | open_id | Environment | Git Role | Branch |
|--------|---------|-------------|----------|--------|
| xspace/静静 | ou_9998dca01cc8cc6b3b54a5d818ba1e32 | WSL2 Ubuntu (RTX 4060, 32GB) | main guardian | main |
| 小芳 | ou_d82fe4c9f90c4e9337235d04b2241070 | Mac M1 (8GB, macOS 26.5) | mac developer | mac |

**Note:** xspace and 静静 are the same entity (飞书群昵称: xspace, 别名: 静静). Do not treat them as separate avatars.

**Critical rule:** Nobody pushes directly to `main`. All changes go through PR → xspace review → merge.

## Profile Format

Three profile files + one shared file in `docs/memory/`:

| File | Owner | Purpose |
|------|-------|---------|
| `hermes-xiaofang.md` | 小芳 | Mac + Orin avatar profile |
| `hermes-xspace.md` | xspace/静静 | WSL2 + main guardian profile |
| `shared-memory.md` | All | Cross-avatar shared knowledge (user, hardware, network, decisions) |
| `hermes-jingjing.md.archived` | — | 旧档案（已归档，xspace/静静已合并） |

### Template

See `references/profile-template.md` for the canonical template. Required sections:

1. **分身身份** — name, role, user, model, framework
2. **硬件环境** — CPU, GPU, RAM, OS, Python stack
3. **核心记忆** — user preferences, project tech stack, key paths, constraints
4. **核心技能** — skill table with names and purposes
5. **最近项目进度** — completed and in-progress phases
6. **协作协议** — division of labor, sync methods, handshake rules

Keep profiles compact and actionable. Update the "最后更新" footer on every edit.

## Sync Workflow

### Branch Setup (小芳 — one time)

```bash
cd ~/lerobot-smolvla-lew
git checkout -b mac           # Create feature branch
# git push origin mac          # Push once SSH is configured
```

小芳 always works on `mac` branch. Never on `main`.

### Daily Workflow (小芳)

```bash
# 1. Pull latest main (to stay in sync)
git checkout main
git pull --rebase origin main

# 2. Rebase mac onto latest main
git checkout mac
git rebase main

# 3. Make changes, commit
git add docs/memory/
git commit -m "docs: [description]"

# 4. Push mac branch
git push origin mac
```

### PR Submission (小芳 → xspace)

After pushing `mac` branch:
1. Go to https://github.com/MikeBMW/lerobot-smolvla-lew
2. Open Pull Request: `mac` → `main`
3. @mention xspace for review
4. xspace reviews and merges

### PR Review (xspace)

```bash
cd ~/lerobot-smolvla-lew
git fetch origin
git checkout -b review-mac origin/mac
# Review changes
git diff main...review-mac
# If approved:
git checkout main
git merge review-mac
git push origin main
```

### Pull (receive others' updates)

```bash
cd ~/lerobot-smolvla-lew
git pull --rebase origin main
```

If conflicts arise (common on `tools/gui/studio.py`):

```bash
# Identify conflicted files
git diff --name-only --diff-filter=U

# For studio.py: keep our changes (ours = current branch's side)
git checkout --ours tools/gui/studio.py
git add tools/gui/studio.py

# Continue rebase (GIT_EDITOR=true avoids interactive editor hang)
GIT_EDITOR=true git rebase --continue
```

### Cross-avatar notification

After pushing or merging, notify the relevant avatars via Feishu (`dataworld` group) that updates are available. They will `git pull` to receive them.

### Three-file memory update checklist

When any avatar updates memory files, update ALL relevant files:
1. Their own profile (`hermes-{name}.md`) — latest state
2. `shared-memory.md` — if affecting cross-avatar info (roles, decisions, hardware)
3. Other avatars' profiles — only if role/relationship info changed

## Pitfalls

### Wrong branch — pushed to main directly

**Symptom:** Made changes on `main` branch instead of `mac`.

```bash
# Check current branch
git branch --show-current

# If on main with uncommitted changes:
git stash
git checkout mac
git stash pop
# Now commit on mac branch

# If already committed on main:
# Move commit to mac branch
git checkout mac
git cherry-pick <commit-hash>
git checkout main
git reset --hard HEAD~1  # Remove from main
```

### Forgot to create PR after push

After `git push origin mac`, ALWAYS create the PR on GitHub. xspace won't know to review without it.

### SSH authentication failure

**Symptom:** `git@github.com: Permission denied (publickey)`

GitHub remote uses SSH (`git@github.com:MikeBMW/...`). If SSH key is not configured:

1. Generate key: `ssh-keygen -t ed25519 -C "mikeni@mac" -f ~/.ssh/id_github`
2. Add to GitHub: https://github.com/settings/keys
3. Configure `~/.ssh/config`:
   ```
   Host github.com
     IdentityFile ~/.ssh/id_github
   ```
4. Test: `ssh -T git@github.com`

Do NOT switch the remote to HTTPS unless credentials are cached — it will fail with "could not read Username."

**Workaround while SSH is down:** Commit locally, note the commit hash, and notify user to push manually when SSH is configured. Local commits are safe.

### Merge conflicts on studio.py

Both avatars edit `tools/gui/studio.py`. When conflicts arise during rebase:

- **Default:** keep `--ours` (HEAD = current branch's side) for studio.py
- **Exception:** if the other avatar's changes are new features (not just commented-out code), inspect and merge manually
- Always verify the file loads after conflict resolution (the file is PyQt5 — syntax errors crash the GUI)

### Rebase with too many sequential conflicts

When `git pull --rebase` hits 3+ consecutive conflicts (common after large merges from the other avatar), the rebase becomes impractical because each conflict requires manual intervention and `GIT_EDITOR=true git rebase --continue`. **Abort and use merge instead:**

```bash
# Abort the failing rebase
git rebase --abort

# Reset to remote's state (accept their version wholesale)
git reset --hard origin/main

# Merge your branch into main, favoring your changes on conflict
git merge mac --strategy-option theirs

# Push the merged result
git push origin main
```

**When to use:** Rebase has already failed 2+ conflicts. The merge approach side-steps every individual commit conflict by accepting one side's version whole-cloth and merging. After the merge succeeds, switch back to the development branch and rebase normally from the updated main.

### Large push timeout

When pushing 15+ commits with large binaries (PDFs, .docx), `git push` can take over 60 seconds due to HTTP transfer of multi-megabyte files. Terminal timeouts will abort the push mid-transfer:

```bash
# Use verbose mode to see progress
git push -v origin mac

# If timed out: retry — Git objects are idempotent and the second push
# skips already-transferred data, typically completing in seconds
git push origin mac
```

The second push is usually fast because the server already received 90%+ of the objects from the first (timed-out) attempt.

### Stale profiles

If `docs/memory/` exists but is empty or missing files after a pull, the remote may not have pushed yet. Check `git log origin/main --oneline -5` to verify.

### Archiving redundant profiles

When two profiles are merged (e.g., jingjing absorbed into xspace), rename the old file with `.archived` suffix rather than deleting:

```bash
git mv docs/memory/hermes-jingjing.md docs/memory/hermes-jingjing.md.archived
git commit -m "docs: 归档 hermes-jingjing.md → xspace/静静 已合并"
```

This preserves history while clearly marking the file as inactive. Never `git rm` profile files — use `.archived` rename.

## Verification

### Document generation (patents, reports)

See `references/patent-disclosure-template.md` for the patent disclosure (.docx) generation workflow — including python-docx setup, required sections, claim formatting, and the generation script path.

### Profile sync verification

After sync:
```bash
# Confirm all active profiles are present (3 active files expected: xiaofang, xspace, shared)
ls -la docs/memory/
# Expected: hermes-xiaofang.md, hermes-xspace.md, shared-memory.md (+ possibly .archived files)

# Confirm current branch
git branch --show-current
# 小芳: should be 'mac'; xspace: should be 'main'

# Check recent commits include avatar updates
git log --oneline -10 | grep -i "avatar\|分身\|jingjing\|xiaofang\|xspace\|shared"

# Verify local vs remote status
git status
# 小芳 on mac: may show "ahead of origin/main" (PR pending)
# xspace on main: should show "up to date with origin/main"

# Check for unpushed branches
git branch -v | grep -v "\[origin"
```

If push fails due to SSH, save the commit locally and notify the user — the commit is safe and can be pushed once SSH is configured. On `mac` branch, the PR to main can be deferred until SSH is ready.
