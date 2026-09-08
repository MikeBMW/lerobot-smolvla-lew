# Z-MAX Relay Deployment (2026-08)

Session-specific deployment details for the Z-MAX data closed-loop relay.

## Architecture
Orin (采集) → 小芳Mac (转发) → ECS relay → 4060 (训练) / 4090 (推理) → Orin (部署)

## ECS Relay Service
- Location: `/root/zmax-relay/zmax_relay.py` (root@39.102.211.79, sshpass pw Nix19789)
- Binds: `0.0.0.0:39053` (NOT 50053 — nginx proxies 39053)
- Data dir: `/root/zmax-relay/data/` (≤100MB auto-cleanup via enforce_buf_limit, pop-on-GET)
- Start: `bash /root/zmax-relay/start.sh` (setsid nohup + pkill inside)

Public endpoints (via nginx 443):
- `POST https://datadrive.world/api/relay/upload` — JSON (name/meta/frames) or raw binary (streamed 64KB chunks)
- `GET  .../api/relay/latest` — POP (returns+deletes); binary → raw octet-stream
- `GET  .../api/relay/peek` — read-only (binary → metadata only)
- `GET  .../api/relay/status` | `/packages`
- `GET  .../api/relay/orin/status` — Orin runtime state (heartbeat-driven)
- `POST .../api/relay/orin/heartbeat` — Orin infer service reports every 5s
- `POST .../api/relay/ci/validate` — Simulink flow validation (8 checks)

## nginx block (datadrive.world.conf)
```
location /api/relay/ {
    client_max_body_size 200m;
    proxy_pass http://127.0.0.1:39053/;
    proxy_read_timeout 300s;
    proxy_send_timeout 300s;
    proxy_connect_timeout 30s; }
location /api/orin/ {
    client_max_body_size 200m;
    proxy_pass http://127.0.0.1:39053/;
    proxy_read_timeout 300s;
    proxy_send_timeout 300s;
    proxy_connect_timeout 30s; }
```
Also present: `/api/comfy/` → 127.0.0.1:50058 (comfy mock), `/ws` → 127.0.0.1:8765.

**Prefix-stripping note (2026-08-02)**: `proxy_pass ...39053/` (trailing slash) strips the location prefix. `/api/orin/heartbeat` arrives at relay as `/heartbeat` → relay accepts BOTH `/orin/heartbeat` and `/heartbeat` in do_POST. But `GET /api/orin/status` arrives as `/status` (queue info, NOT orin state) — clients MUST use the full `/api/relay/orin/status` path for orin state.

## Why 39053 not 50053
Aliyun security group blocks 50053/39053 from outside even with ufw allow (test from box via public IP times out = security group). 80/443 open → nginx reverse proxy is the only reliable path. ufw rule exists but is useless.

## Client scripts (repo lerobot-smolvla-lew)
- Upload (4060): `tools/upload_model.py` — POST binary, timeout=600
- Pull+deploy (Mac): `hermes_gateway_mac/cicd_pull_deploy.py` — GET /latest → save bytes → scp to Orin → start infer service
- JSON training data pull (4060): `tools/relay_train.py pull` — JSON only, NOT for binaries
- Orin infer: `hermes_gateway_mac/orin_infer_service.py` — loads model, :8766 /infer, 5s heartbeat POST

## Bug history (fixed)
1. Binary upload crashed relay (OOM) → streaming write
2. safetensors head misclassified as JSON → full-json-parse sniff
3. 502 on big upload → nginx proxy timeout 60s→300s
4. Port mismatch 50053 vs 39053 → silent 502
5. `pkill -f` in same cmd as start → killed new process
6. `/latest` pop lost 87MB (consumer didn't save) → added /peek
7. Small-fang heartbeat 404/502 → missing `/api/orin/` nginx location + relay only accepted `/orin/heartbeat` (nginx stripped prefix to `/heartbeat`) → added location + dual-path match
8. do_POST had no else fallback → unknown endpoints gave nginx 502 (no response) → added 404 fallback
9. `/api/orin/status` returned queue info (prefix-stripped to `/status`) — clients must use full `/api/relay/orin/status`
