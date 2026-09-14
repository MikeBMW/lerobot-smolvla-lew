---
name: branch-merge-review
description: "Review & safely merge a teammate's pushed branch (no PR)."
version: 1.0.0
author: agent
tags: [git, merge, code-review, collaborator, github]
platforms: [linux, wsl]
---

# Branch Merge Review (Direct-Push Collaboration)

Use when a teammate pushes a branch directly (`git push origin <branch>`) and asks you — lead/reviewer — to check and merge it into main. This is the push-based workflow this team uses instead of PRs (e.g. 小芳 pushes a `mac` branch, 静静 reviews and merges; user instruction "合并远程" = review then merge). Also covers any "code pushed, review it and merge" request.

## Workflow

1. **Confirm the branch exists remotely** — plain `git fetch origin` can SILENTLY skip creating the remote-tracking ref (`git branch -r` stays stale while the branch is live on GitHub). Ground truth first:
   ```bash
   git ls-remote origin                                            # all remote refs
   git fetch origin <branch>:refs/remotes/origin/<branch>          # forced refspec fetch
   git log --oneline origin/main..origin/<branch> | cat            # what the branch adds
   ```
   GitHub API alternative when ls-remote is blocked: `curl -H "Authorization: token $TOKEN" https://api.github.com/repos/<org>/<repo>/branches`.

2. **Review the diff — both directions**:
   ```bash
   git diff origin/main origin/<branch> --stat          # scale of change
   git diff origin/main origin/<branch> --name-status   # A/M/D per file
   git show <branch-commit> --stat                       # per-commit intent
   ```
   Read the commit message first, then check the diff actually matches the claimed intent. A "chore: v2.5" message hiding 1400 deleted lines = red flag.

3. **CRITICAL — deleted-but-still-referenced files.** Branch authors routinely delete modules they believe are dead. Before merging, cross-check deletions against imports:
   ```bash
   git diff origin/main origin/<branch> --name-status | grep '^D'
   # on the merged state: grep the code for imports of each deleted module
   grep -rn "import <deleted_module>\|from <deleted_module>" <code-dir>/
   python3 -m py_compile <changed-main-files>            # syntax sanity
   ```
   If imports remain → restore from main: `git checkout origin/main -- <path>`.
   Known casualties in this project: `docs_sync.py`, `ppt_engine.py`, `update_checker.py` are still imported by `tools/gui/studio.py`; `.github/workflows/build-win-exe.yml` (Windows .exe auto-build CI) deleted by accident.

4. **CI workflow files are sacred.** `.github/workflows/*` deletions are almost never intentional — restore them from main unless the branch message explicitly says the pipeline is being retired.

5. **Garbage files**: Windows `*.Zone.Identifier` files (NTFS ADS markers) get committed by accident. Check `git ls-files | grep -i zone.Identifier` — if they never entered the index (gitignore filtered them during a conflicted merge), nothing to do; if tracked, `git rm` them. Never ship them to main.

6. **Merge**:
   ```bash
   git checkout main && git pull --rebase origin main
   git merge origin/<branch> --no-edit
   git diff --name-only --diff-filter=U      # conflicts to resolve
   ```
   `.gitignore` conflicts: both sides usually added valid rules — merge BOTH sets by hand, strip the `<<<<<<<` / `=======` / `>>>>>>>` markers, `git add`.

7. **Post-merge verification (minimal, no over-verification)**: deleted-file import check passes, `git status` shows no conflict markers, commit with a message stating what was kept/restored, push, and tell the teammate what you changed so they re-sync. Example: `merge: 合并mac分支v2.5 — 保留build-win-exe CI/docs_sync/ppt_engine/update_checker`.

## Pitfalls

| Problem | Cause | Fix |
|---|---|---|
| `git fetch origin` shows no new branch | remote-tracking ref never created | `git ls-remote origin` to confirm, then `git fetch origin <branch>:refs/remotes/origin/<branch>` |
| Push rejected non-fast-forward | remote ahead | `git pull --rebase origin main` first |
| Branch deletes CI workflow | accidental cleanup | Restore `.github/workflows/*` from main unless deletion is the stated intent |
| Imports break after merge (ModuleNotFoundError at runtime) | teammate deleted modules still referenced | `git checkout origin/main -- <file>` for each referenced module |
| `.gitignore` merge conflict | both sides added rules | Keep both rule sets, strip conflict markers, `git add` |
| Deleted PPTX/docs in branch | teammate cleanup | Respect it — user cares about CODE and CI, not stale docs |
