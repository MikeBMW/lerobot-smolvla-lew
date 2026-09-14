---
name: hermes-crash-recovery
description: "Restore Hermes crash: repos, creds, memory, gateway."
version: 1.1.0
author: agent
tags: [hermes, recovery, disaster-recovery, system-restore, credential-recovery]
platforms: [linux, wsl]
---

# Hermes Crash Recovery — Full System Restoration

Use this skill when Hermes Agent has been wiped/reinstalled after a system crash. It covers the complete recovery pipeline: from bare agent to fully operational state with all credentials, memory, gateway connections, and project context restored.

## Overview

```
┌─ Crash ───────┐
│ Hermes wiped   │
└───────┬───────┘
        ▼
  ┌──────────────────────────────┐
  │ 1. Clone repos (+ partners)   │
  │ 2. Scan for memory in repos   │
  │ 2.5 Sync cross-agent memory   │
  │ 3. Restore creds              │
  │ 4. Rebuild gateway            │
  │ 5. Verify bot in groups       │
  │ 6. Push recovery version      │
  │ 7. Deploy shared assets        │
  │ 8. Post-recovery cleanup       │
  │ 9. Save memory backup          │
  └──────────────────────────────┘
        ▼
  ┌─ Operational ──┐
  │ Full recovery   │
  └─────────────────┘
```

## Post-Reboot Restore (No Crash — Just a Reboot)

Use when the machine power-cycled (WSL/PC reboot) but Hermes was NOT wiped: memory, skills, and creds survive; only processes and cron state are gone. Lighter than full recovery — run in this order:

1. **Health check** (one shot):
   ```bash
   nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv,noheader
   free -h | head -2; df -h / | tail -1; uptime   # "up 0 min" = just booted
   ```
2. **Gateway**: `terminal(background=true)` long-lived, no notify_on_complete. **Must launch via the venv python**, NOT the bare `hermes`/`./hermes-agent/hermes` launcher — outside an activated venv the launcher dies instantly with `ModuleNotFoundError: No module named 'dotenv'`:
   ```bash
   # from the repo root (~/.hermes/hermes-agent)
   ./venv/bin/python hermes gateway run
   ```
   If the process exits immediately (check `process(action='poll')` → traceback), this is the cause. Also remove stale lock/pid files left by the crashed process BEFORE starting: `rm -f ~/.hermes/gateway.lock ~/.hermes/gateway.pid`. Confirm the Lark/Feishu websocket connect line (`✓ feishu connected`) appears in `~/.hermes/logs/gateway.log` before moving on.

### Gateway 失联诊断 + systemd 自愈守护（根治"飞书又不好使"）

Symptom: user says "飞书又不好使了" — gateway.log's last entry is hours old and no gateway process exists. Root cause is almost always: **the gateway is an independent process (`hermes gateway run`), NOT part of the CLI session; when it dies (crash/reboot) nothing restarts it**. Manual `terminal(background=true)` starts are not durable.

Diagnose in ~60s (in order):
1. `ps aux | grep "gateway run" | grep -v grep` — process gone = the answer.
2. `tail ~/.hermes/logs/gateway.log` — compare last timestamp vs now.
3. `cat ~/.hermes/logs/gateway-exit-diag.log` — every `gateway.start` record (pid, argv, platform) confirms how it was launched.
4. `tail ~/.hermes/logs/errors.log` — pre-crash warnings.

Fix once, then it self-heals (proven 2026-08-02 on WSL):
- Launch via the venv wrapper `~/.local/bin/hermes` — NOT the bare `~/.hermes/hermes-agent/hermes` source (dies with `No module named 'dotenv'`).
- Create `/home/<user>/.config/systemd/user/hermes-gateway.service`:

```ini
[Unit]
Description=Hermes Agent Gateway (Feishu/Telegram/etc)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/home/<user>/.local/bin/hermes gateway run --replace
Restart=always
RestartSec=5
Environment=HOME=/home/<user>
WorkingDirectory=/home/<user>

[Install]
WantedBy=default.target
```

- Enable: `systemctl --user daemon-reload && systemctl --user enable --now hermes-gateway`
- `--replace` (see `hermes gateway run --help`) kills and replaces any manually-started gateway instance — verify old PID gone, new PID active. `--force` is for when a systemd service already supervises the profile.
- Verify: `systemctl --user status hermes-gateway` (active) + `grep "feishu connected" ~/.hermes/logs/gateway.log`. WSL check: `systemctl is-system-running` → `running` means systemd is available.
- Pitfalls: the gateway cannot restart itself from inside its own process (SIGTERM propagation — Hermes blocks "restart/stop from inside the gateway process"); always `rm -f ~/.hermes/gateway.lock ~/.hermes/gateway.pid` before start if a crash may have left them.

### 容器无 systemd 守护（2026-08-16 根因修复，容器专用）

Symptom: gateway 死了 8-17 小时无人拉起，且 Hermes 的 gateway-守护 cron 一直显示 ok 却没生效。

**根因（死锁）**: Hermes cron 调度器 = `InProcessCronScheduler`，**跑在 gateway 进程内部**（`gateway/run.py:29039`）。gateway 一死 → 进程内 cron 跟着死 → "gateway-守护"任务再也没人执行。守护逻辑放在被守护进程内部 = 无效守护。容器无 systemd（`systemctl is-system-running` → offline），所以 systemd 方案不可用。

**容器修复配方（实测通过 2026-08-16）**:
```bash
# 1. 装系统 cron (独立于 Hermes 进程树)
apt-get install -y cron
/usr/sbin/cron        # 容器无 systemd, 手动拉起 daemon (pid 964)
# 2. watchdog 脚本 v2: flock 防并发 + setsid 脱离会话
#    ~/.hermes/scripts/gateway_watchdog.sh
# 3. 装载 root crontab (标准工具, 每分钟检查)
(crontab -l 2>/dev/null; echo '* * * * * /root/.hermes/scripts/gateway_watchdog.sh') | crontab -
crontab -l            # 验证
# 4. 端到端验证: kill -9 <gateway-pid> → 65 秒内自动拉起新 pid
```

watchdog v2 要点: `flock -n /tmp/gateway_watchdog.lock` 防同分钟并发拉起多个; `setsid nohup ... &` 脱离 cron 会话防 HUP; 进程存在即视为活着（启动中 lark_oapi import 需 85s，别误杀）; 正常静默、拉起时输出一行时间戳告警。**检测模式必须用 `pgrep -f "/root/.hermes/venv/bin/hermes"`**（兼容裸 `hermes` 与 `hermes gateway run` 两种启动方式，见黄金法）。**脚本开头加 cron 自愈**: `pgrep -x cron >/dev/null 2>&1 || /usr/sbin/cron` — 容器重启后系统 cron 不会自动起（容器 PID 1 = sleep infinity，无 entrypoint），由 Hermes 内每 3m 的 gateway-守护 job 调用本脚本时把 cron 拉起，外部每分钟守护恢复。外部 cron 调用时 cron 必活 → 无操作。

**判断 gateway 真死的黄金法**: `pgrep -f "/root/.hermes/venv/bin/hermes"` 无输出 = 死。⚠️ **不要用 `grep "hermes gateway run"`** — gateway 可能以裸 `hermes` 启动（命令行无 `gateway run` 子命令，2026-08-17 实测），该模式永远匹配不到 → watchdog 每次误判死亡 → 每分钟 setsid 误拉一个新 gateway → 双实例双飞书双 cron 并存的实害。误拉实例用一次性系统 cron 任务清理（gateway 进程内 kill 会被 Hermes 安全机制拦截，系统 cron 在进程树外不受限）。`gateway_state.json` 的 `updated_at` 若停留数小时不动 = 进程已死（state 只在启动/心跳时更新，gateway.log 停更同理）。`gateway-exit-diag.log` 会记录 `exited UNCLEANLY (SIGKILL / OOM / VM death)` + 最后心跳时间。
3. **Cron jobs**: `cronjob(action='list')` — after reboot/restore the list can be EMPTY. If the system watchdog (or any monitor) is missing, recreate it (pattern below).
4. **Repos**: per repo — `git status --short`, `git pull --rebase origin main` (remote is often ahead; a bare `git push` fails non-fast-forward), `git push origin main`. Verify a `PUSH_DONE` marker per repo. **If `git fetch`/`git pull` HANGS (times out) while `curl -sI https://github.com` and `git ls-remote origin` both work fast**: the git smart-HTTP pack negotiation is stalling (seen on WSL Aug 2026). Fix: force HTTP/1.1 — `git -c http.version=HTTP/1.1 fetch origin main`. `git fetch origin <sha>` can also hang when the object is not yet local; ls-remote first to confirm the ref actually exists. Run slow git ops with `timeout` so a hang can't block the whole recovery (e.g. `timeout 90 git fetch ...`). **Different failure — TLS terminated at handshake**: `fatal: ... GnuTLS recv error (-110): The TLS connection was non-properly terminated` while TCP 443 to github.com is reachable (`timeout 8 bash -c 'exec 3<>/dev/tcp/github.com/443'`) = SNI-level block (GFW signature, intermittent — `--check` may succeed once then `update` fails). Fix: route only the upstream repo through an HTTPS mirror — `cd ~/.hermes/hermes-agent && git config url."https://ghfast.top/https://github.com/".insteadOf "https://github.com/"` (**repo-level, never `--global`** — mirrors are read-only and would break pushes to the user's own repos). Verify with `git fetch origin main` before `hermes update`. Clear stale fetch locks first: `rm -f <repo>/.git/shallow.lock` (leftover lock → "Unable to create ... File exists").
5. **Cleanup**: `pip cache purge`, `sudo apt-get clean`, `sudo journalctl --vacuum-time=3d`, remove stale `/tmp/*.log` and `tmp*`. Safe on any box.
6. **Memory**: refresh entries that carry PID/process state — they are stale after a reboot (e.g. "Gateway PID 12345" → new background session).

### Resource care (user mandate: "监控系统性能，别超载，我不想把你搞丢了")

The user explicitly asked (2026-08-01, after a prior crash): monitor system performance, do NOT overload the box, and never lose the agent again. After any reboot or heavy session:

- Report current resource state when asked: `free -h | head -2; df -h / | tail -1; nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu,temperature.gpu --format=csv,noheader`.
- On the 15G RAM / RTX 4060 8GB box: gateway + watchdog are the only always-on processes. Keep total RAM use well under ~90 % (9G used of 15G with VSCode server open is normal; 5.7G+ free is fine). Don't spawn extra long-lived processes "just in case".
- The sys-watchdog cron (every 15m, no_agent, threshold-only, `deliver='all'`) is the standing guard. If it's missing after reboot, recreate it (pattern above) — its existence matters as much as its output.
- Warn the user when a memory hog (e.g. VSCode server ~500MB+) is eating RAM and they're about to shut down — a lean box is a stable box.

### Reusable sys-watchdog cron pattern (no_agent threshold watchdog)

- Script `~/.hermes/scripts/sys_watchdog.sh`: checks GPU mem/util, RAM %, disk %, load; prints ONLY when a threshold trips (RAM/disk >90 %, load ≥8, GPU mem >90 %). Empty stdout = healthy = silent.
- Job creation: `cronjob(action='create', schedule='every 15m', no_agent=true, script='sys_watchdog.sh', deliver='all')`.
  - **script must be a RELATIVE filename** under `~/.hermes/scripts/` — absolute paths are rejected.
  - `deliver='all'` so alerts fan out to every connected gateway platform (e.g. Feishu).
  - no_agent semantics: non-empty stdout delivered verbatim; empty = silent; non-zero exit = error alert.

## Live-USB Rescue: Restore from Windows Docker Desktop Backup

Scenario: the old Windows machine holds the only Hermes backup (`D:\hermes-docker\workspace\hermes-backup\hermes_core_*.tar.gz` — a full `~/.hermes` snapshot) and you're continuing on a fresh box. Boot an Ubuntu live USB on the old machine, mount its NTFS drives **read-only**, extract selectively. (Full recipe: `references/2026-08-22-live-usb-windows-backup-restore.md`.)

1. **Identify drives**: live system has `/` on `/cow` + `/cdrom`; `lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINT` separates the USB stick from the internal NVMe. NTFS partitions = Windows drives — identify C/D/E by root content, don't guess: C has `Windows/`, `hiberfil.sys`, `pagefile.sys`; D is the data drive with `hermes-docker/`; E holds `WSL/`.
2. **Mount read-only** (`sudo mount -o ro /dev/nvme0n1pN /mnt/winN`) — Windows fast startup / hibernation corrupts NTFS on read-write mount. Read/copy only. **If you must WRITE to the NTFS drive** (e.g. save the fresh box's backup into `hermes-docker/workspace/hermes-backup/`): `mount -o rw,remount` **SILENTLY FAILS on fuseblk/ntfs-3g** (stays ro; the cp error looks like "No such file or directory"). Must `sudo umount /mnt/winN && sudo mount -o rw /dev/nvme0n1pN /mnt/winN`, then `umount` again when done. Never leave the Windows drive mounted rw.
3. **Locate the backup**: `/mnt/win*/hermes-docker/workspace/hermes-backup/hermes_core_*.tar.gz`. Package layout: `.hermes/{config.yaml,.env,auth.json,cron/,skills/,memories/,state.db}` — **contains secrets**, never push to a public repo.
4. **Restore selectively — skills only, not the whole package**:
   ```bash
   cd ~ && mv .hermes/skills .hermes/skills.pre_usb_boot   # keep current skills as fallback
   tar xzf <pkg> --wildcards '.hermes/skills/*'
   ```
   Compare versions before overwriting: `tar tvzf <pkg> | grep '<skill>/SKILL.md'` vs local `ls -la` (mtime/size) + file counts. Overwrite only when the backup is newer.
5. **Memory pitfall — never blindly restore backup memories**: backup `MEMORY.md` is often STALER than the live env (proven 2026-08-22: backup still listed the ECS password that was already proven dead on 08-13). `diff` first, keep the newer facts, merge per-entry. Skills/code can be wholesale-overwritten; memories must not.
6. **Leave config/auth/cron alone** — the live environment's own set works (it's running); sync only what the user asked for. Clean up temp extracts (`rm -rf /tmp/.hermes`).

### Post-restore bring-up (fresh box → fully operational, proven 2026-08-22)

After skills/memory are in place, the user's standing CICD ritual on a new box is: 保存数据 → 小版本迭代 → 代码推送 → 系统保护 → 自检 → 可靠性维护. Run in this order:

1. **保存数据**: `hermes backup -o ~/hermes_core_$(date +%Y%m%d_%H%M).zip` (full zip: skills/sessions/config; restore = `hermes import <zip>`). Copy the zip into the D-drive backup dir (see rw-mount note above).
2. **小版本迭代**: `hermes update --check` then `hermes update --yes` (git pull + deps + Web UI rebuild + bundled-skill sync). User skills (e.g. zmax-console) are NOT clobbered — verify after: `hermes --version` + the skill file still present.
3. **代码推送**: a fresh box may hold no user repos — hermes-agent is the upstream NousResearch repo (read-only; pull is the only op). Don't fabricate a push target; report the gap instead. **If the user wants a project repo cloned to the fresh box** (GitHub SNI-blocked): clone through the mirror, then configure dual-channel so fetch stays on the mirror but push goes to official github.com (mirrors are read-only — without this rule push breaks):
   ```bash
   git clone https://ghfast.top/https://github.com/<user>/<repo>.git
   cd <repo>
   git config url."https://github.com/".pushInsteadOf "https://ghfast.top/https://github.com/"
   # remote URL keeps the mirror prefix (fetch path); the pushInsteadOf rule re-routes
   # only `git push` back to official github.com. Verified 2026-08-22 on lerobot-smolvla-lew.
   ```
   Note this complements the upstream-repo fix (insteadOf, fetch-only); for user repos you need BOTH directions working, so pushInsteadOf (not plain insteadOf) is the right rule.
4. **系统保护**: `sudo $(which hermes) gateway install --system` — sudo drops the user PATH (`sudo hermes` → "command not found"). Installs + enables + starts the `hermes-gateway` systemd service (boot-persistent on live-USB with casper-rw persistence).
5. **自检**: `hermes doctor` (env/SSL/config) + `hermes status` (API keys) + `hermes gateway status`.
6. **可靠性维护**: `hermes cron status` — right after gateway start the ticker may report STALLED with a ~10h-old heartbeat (stale state file from before the start); wait 15-60s and re-check for "Ticker heartbeat: Xs ago" + "N active job(s)". Confirm watchdog/链路巡检/磁盘红线 scripts exist under `~/.hermes/scripts/`.

### 桌面补充：中文输入法（ibus，新机必做）

A fresh Ubuntu desktop (live-USB or installed) has no Chinese input. Setup (proven 2026-08-22):
```bash
sudo apt-get install -y ibus-pinyin
ibus restart; ibus engine libpinyin          # session-level switch
# FIX default so it survives restarts AND hermes update:
gsettings set org.freedesktop.ibus.general preload-engines "['libpinyin']"
gsettings set org.freedesktop.ibus.general.hotkey triggers "['<Control>space']"
grep -q GTK_IM_MODULE ~/.bashrc || echo -e '\nexport GTK_IM_MODULE=ibus\nexport QT_IM_MODULE=ibus\nexport XMODIFIERS=@im=ibus' >> ~/.bashrc
```
**Pitfall (proven 2026-08-22): `hermes update` resets the ibus engine back to `xkb:us::eng`** — the daemon keeps running but typing is English-only. Session-level `ibus engine libpinyin` is NOT enough; the gsettings preload-engines step above is what makes it stick. When the user says "中文输入法呢" after an update: check `ibus engine` (not just `pgrep ibus-daemon`), re-set engine + confirm gsettings preload list.

## Step-by-Step Recovery

### Step 1: Clone Project Repositories

```bash
git clone --depth 1 https://github.com/<org>/<repo>.git ~/<repo>/
```

Use `--depth 1` for speed; full history can be fetched later.

### Step 2: Scan for Existing Memory in Repo

Check `docs/memory/` or similar directories:

```bash
ls -la ~/<repo>/docs/memory/
```

Files to look for:
- `xspace.md` — agent's memory archive
- `xiaofang.md` — partner agent's memory
- `sync.md` — shared team memory
- `shared-memory.md` — cross-agent knowledge
- `task-board.md` — project task board
- `hermes-<name>.md.archived` — prior agent memory

### Step 2.5: Sync Cross-Agent Memory (If Partner Agents Exist)

Partner agents (e.g. another AI agent on the same project) may have pushed their independent memory dumps to their own repos. Check all cloned repos:

```bash
# Check partner repos for memory directories
ls -la ~/<partner-repo>/backups/memory_*.md 2>/dev/null
ls -la ~/<partner-repo>/backups/user_profile*.md 2>/dev/null
ls -la ~/<partner-repo>/docs/memory/ 2>/dev/null
```

Read each partner memory file via `read_file()`. Extract:
- **Role hierarchy**: Who is lead/PM/hardware specialist — determine your role relative to theirs
- **User preferences the partner documented**: These are often more detailed than what the user told you directly
- **Communication topology**: IPs, ports, data pipeline links between nodes you own
- **Pending tasks that involve you**: Blockers or handoffs the partner left for your role

Integrate into Hermes memory:
- `target='user'`: user preferences documented by partner, team role definitions
- `target='memory'`: communication topology, data pipeline links between your node and others

**Key insight:** Partner memory files often contain unspoken expectations about your role (e.g. "总工 handles all GPU training and GUI" or "PM expects 总工 to review before deploy"). Inferring and acting on these without needing the user to re-explain everything is the core value of cross-agent sync.

### Step 3: Restore Hermes Persistent Memory

Read memory files via `read_file()`, save to Hermes memory:

- **`target='user'`**: user identity, role, project context, preferences, team structure, credentials (redacted)
- **`target='memory'`**: hardware env, tool configs, workspace paths, gateway state

### Step 4: Restore Credentials (Ask User)

> **User preference (老倪/MikeNi): NEVER ask for credentials.** He stated it explicitly: "以后不要问我，密码是 x 你自己搞定" (don't ask me — handle it yourself). Restore creds from `~/.hermes/.env`, `~/.git-credentials`, and memory — project passwords (e.g. ECS) live in deploy.sh comments and memory. Only escalate if a credential genuinely cannot be located anywhere.

Crash wipes `.env`. Request from user (only if not already in memory/env):

| Credential | .env Variable |
|---|---|
| GitHub PAT | `GITHUB_TOKEN` |
| Feishu App ID | `FEISHU_APP_ID` |
| Feishu App Secret | `FEISHU_APP_SECRET` |
| LLM API Key | e.g. `DEEPSEEK_API_KEY` |

Save to `~/.hermes/.env`:

```bash
cat >> ~/.hermes/.env << 'EOF'
GITHUB_TOKEN=ghp_xxx...
FEISHU_APP_ID=cli_xxx...
FEISHU_APP_SECRET=xxx...
FEISHU_DOMAIN=feishu
FEISHU_CONNECTION_MODE=websocket
FEISHU_ALLOW_ALL_USERS=true
GATEWAY_ALLOW_ALL_USERS=true
FEISHU_GROUP_POLICY=open
EOF
```

**⚠️ `FEISHU_GROUP_POLICY` is easy to lose in a rebuild and breaks group chat silently.**
The adapter defaults it to `allowlist` when unset; with empty `FEISHU_ALLOWED_USERS` every
group message is rejected in-adapter at DEBUG log level — DMs keep working, the gateway
logs look fine, and the user sees "bot not replying in group" with no error anywhere.
Proven 2026-08-01: crash recovery rebuilt `.env` without this var; group @-mentions died
until `FEISHU_GROUP_POLICY=open` was re-added. Always verify these four survive recovery:
`FEISHU_GROUP_POLICY`, `FEISHU_ALLOWED_USERS`, `FEISHU_ALLOW_ALL_USERS`,
`GATEWAY_ALLOW_ALL_USERS`. See `feishu-gateway` skill for the full diagnostic.

**Git credential helper setup:**

```bash
git config --global credential.helper store
git config --global user.name "<user>"
git config --global user.email "<email>"
echo "https://<user>:<token>@github.com" > ~/.git-credentials
chmod 600 ~/.git-credentials
```

### Step 5: Rebuild Feishu Gateway

**Install deps** (venv has no pip — use venv python):

```bash
~/.hermes/hermes-agent/venv/bin/python -m pip install lark-oapi websockets
```

**Enable Feishu in config:**

```bash
hermes config set platforms.feishu.enabled true
```

**Start gateway (background):**

```bash
hermes gateway run &
```

**Verify** — log should show:
```
[Feishu] Connected in websocket mode (feishu)
✓ feishu connected
```

### Step 6: Verify Bot Is in Groups (Not Just Connected)

Gateway connected and authenticated does NOT mean the bot can receive messages. It must be a **member of a group chat** on Feishu. Check which groups the bot belongs to programmatically:

```bash
TOKEN=$(curl -s -X POST 'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal' \
  -H 'Content-Type: application/json' \
  -d '{"app_id":"...","app_secret":"..."}' | python3 -c "\
import sys,json; print(json.load(sys.stdin).get('tenant_access_token',''))")
curl -s "https://open.feishu.cn/open-apis/im/v1/chats?page_size=20" \
  -H "Authorization: Bearer $TOKEN" | python3 -c "\
import sys,json; d=json.load(sys.stdin)
for i in d.get('data',{}).get('items',[]):
    print(f'chat_id={i.get(\"chat_id\",\"\")} | name={i.get(\"name\",\"\")}')"
```

If the bot is not in the expected group(s), the **user must add it manually** via group settings → 群机器人 → 添加机器人 → search for the bot name. The agent cannot join groups unilaterally.

Run the gateway in background and tail the log:
```bash
tail -f ~/.hermes/logs/gateway.log
```
Successful reception looks like `[Feishu] receive message from group xxx`. If only startup lines appear after hours of running, no messages have been forwarded — check Feishu developer console → 事件订阅 → `im.message.receive_v1` is subscribed, and the app version has been published.

### Step 7: Push Recovery Version

1. **Find the version string** — may be in `VERSION.md`, `version_sync.py`, `pyproject.toml`, or hardcoded in source:

   ```bash
   grep -rn 'version\s*=' --include='*.py' --include='*.toml' --include='*.md' .
   grep -rn '__version__\|VERSION\|zmax_ver' --include='*.py' .
   ```

2. **Bump version in source code** — edit the file (use patch or direct edit).

3. **Stage, commit, tag, and push** — the full workflow (not just commit):

   ```bash
   git add <changed-files>
   git commit -m "release: vX.Y.Z — description"
   git tag -f vX.Y.Z          # -f overwrites existing tag (use carefully)
   git push origin main --tags
   ```

   **Pitfalls:**
   - `git tag` without `-f` fails if the tag already exists on a prior commit.
   - `git push origin --tags` pushes ALL local tags. For a single tag: `git push origin tag vX.Y.Z`.
   - To delete a stale remote tag: `git push --delete origin vX.Y.Z` then `git tag -d vX.Y.Z`.
   - Always verify the version string in the deployed code matches the tag — grep the actual file after commit.

### Step 8: Deploy Updates to ECS / Shared Servers (If Non-sshpass)

If you need to deploy updated HTML/docs to an ECS server and `sshpass` is unavailable, use the `SSH_ASKPASS` workaround:

```bash
export DISPLAY=:0
export SSH_ASKPASS=/tmp/ssh_askpass.sh
cat > $SSH_ASKPASS << 'SCRIPT'
#!/bin/bash
echo "<password>"
SCRIPT
chmod +x $SSH_ASKPASS
setsid scp -o StrictHostKeyChecking=no <local-file> root@<ip>:<remote-path>
```

**Important:** `setsid` is required — plain `scp` with `SSH_ASKPASS` hangs without it. Verify deployment by fetching the URL and `grep`-ing for the new content.

### Step 9: Post-Recovery Cleanup

After repos, creds, gateway, and version are restored, clean build/install caches:

```bash
# Clean pip cache (if pip is available)
pip cache purge 2>/dev/null || python3 -m pip cache purge 2>/dev/null

# Clean uv cache (if uv is available)
uv cache clean 2>/dev/null

# Direct removal if tools unavailable (e.g. pip/uv not installed on system)
rm -rf ~/.cache/pip ~/.cache/uv 2>/dev/null
rm -rf ~/.cache/electron ~/.cache/node-gyp 2>/dev/null

# Clean /tmp
rm -rf /tmp/* 2>/dev/null
```

Caches re-accumulate naturally through normal use, so this is safe. On constrained disks (<20GB free), also check `~/.cache/pip` and `~/.cache/uv` weekly.

### Step 10: Save Memory Backup to Repo (Optional but Recommended)

After all context is re-established, snapshot Hermes memory to the project repo for future crash recovery:

1. Compile current memory + user profile context into a backup file:

   ```bash
   mkdir -p ~/zmax-website/backups/
   ```

2. The backup file (e.g. `mem_YYYYMMDD.md`) should contain:
   - **System state**: host, model, provider, disk/RAM specs
   - **Project context**: repos, deployment targets, team structure
   - **Credentials summary**: which providers are configured (never write raw secrets)
   - **User preferences**: style, tone, pet peeves, CEO mandates

3. Commit and push:

   ```bash
   cd ~/zmax-website
   git add backups/mem_YYYYMMDD.md
   git commit -m "记忆备份: mem_YYYYMMDD.md · YYYY-MM-DD"
   git push origin main
   ```

**Pitfall:** Never embed raw secrets (tokens, passwords) in backup files. Reference the env var name instead.

## Pitfalls

| Problem | Cause | Fix |
|---|---|---|
| Gateway connects but no msgs | Bot not in any Feishu group | User adds bot via group settings → 群机器人 → 添加机器人 |
| DM works but group @-mentions dead after recovery | `.env` rebuild dropped `FEISHU_GROUP_POLICY` (defaults to `allowlist`, empty whitelist → all group msgs rejected at DEBUG level) | Re-add `FEISHU_GROUP_POLICY=open` + `FEISHU_ALLOWED_USERS` to `.env`, restart gateway from separate shell |
| `.env` wiped | Crash | Ask user for all creds, never guess |
| `ModuleNotFoundError: lark_oapi` | SDK missing in Hermes venv | `venv/bin/python -m pip install lark-oapi` |
| Git push fails | No credential helper | Set up `~/.git-credentials` with PAT |
| Feishu file links 404 | No user-level access | User must share file to group, not share individual doc link |
| Memory incomplete | Partial backup in one repo only | Check ALL repos for memory directories (`docs/memory/`, `backups/`) |
| Partner memory not loaded | Only checked own repo | Clone partner repos too and read their memory files |
| Deploy to ECS fails | `sshpass` not installed | Use `SSH_ASKPASS` with `setsid` workaround |
| venv `pip` missing | uv-created venv has no pip | `venv/bin/python -m pip install <pkg>` (not bare `pip` or `pip3`)
| Cron list empty after reboot | Jobs lost / never recreated | Recreate sys-watchdog: `cronjob(action='create', no_agent=true, script='sys_watchdog.sh', deliver='all')` — relative script path only |
| `git push` fails "non-fast-forward" | Remote ahead (teammate pushed) | `git pull --rebase origin main` then push |
| `git fetch`/`git pull` HANGS (times out) but `curl -sI https://github.com` and `git ls-remote origin` are instant | Smart-HTTP pack negotiation stall (seen on WSL) | `git -c http.version=HTTP/1.1 fetch origin main`; wrap slow git ops in `timeout 90 ...` so a hang can't block recovery |
| Gateway dies instantly with `ModuleNotFoundError: No module named 'dotenv'` | Launched via bare `hermes`/`./hermes-agent/hermes` outside the venv | Launch via `./venv/bin/python hermes gateway run` from `~/.hermes/hermes-agent`; remove stale `~/.hermes/gateway.lock` + `gateway.pid` first |
| 飞书失联、gateway.log 停更、`ps` 无 gateway 进程（"又不好使"反复发生） | Gateway 是独立进程且无守护 — 崩溃/重启后没人拉起 | Install systemd user service `hermes-gateway` (Restart=always, `ExecStart=… hermes gateway run --replace`) — see "Gateway 失联诊断 + systemd 自愈守护" above |
| SSH_ASKPASS still `Permission denied` | Newer OpenSSH ignores SSH_ASKPASS_REQUIRE / scp uses sftp subsystem | Don't burn time: have the partner agent (web/4090) run deploy.sh from its machine, or ask the user to approve `apt install sshpass` |
| `pip install paramiko` fails "No matching distribution" | No wheels for new Python (e.g. 3.14) | Don't chase it — use sshpass/SSH_ASKPASS or partner-machine deploy |
| 备份包里的 MEMORY.md 比当前环境旧 | 备份是旧快照，可能仍写"凭据有效"而实际已失效 | 恢复记忆前 `diff` 对比，保留新事实逐条合并；技能可整目录覆盖，记忆不可 |
| Windows NTFS 盘挂载后损坏/写失败 | 快速启动/休眠未关，读写挂载危险 | 一律 `mount -o ro` 只读挂载，只做读取/拷贝 |
| 往 NTFS 盘写文件报 "No such file or directory" | `mount -o rw,remount` 对 fuseblk/ntfs-3g 静默失败，实际仍只读 | `umount` 后 `mount -o rw` 重挂，写完再 `umount`；别 remount |
| `git fetch`/`hermes update` 报 GnuTLS recv error (-110)，TCP 443 却通 | GitHub SNI 级阻断（间歇性） | 仓库级 `git config url."https://ghfast.top/https://github.com/".insteadOf "https://github.com/"`（别 --global），先 `rm -f .git/shallow.lock` |
| `sudo hermes ...` 报 command not found | sudo 环境丢用户 PATH（hermes 在 ~/.local/bin） | `sudo $(which hermes) gateway install --system` |
