---
name: hermes-gateway-robot
description: Connect Hermes Agent to Orin robot via Mac Gateway — SSH bridge, HTTP API, real-time joint control
platforms: [macos, linux]
---

# Hermes Gateway Robot Bridge

Use this skill when connecting Hermes Agent to a physical Orin (NVIDIA Jetson) robot via the Hermes Gateway bridge on Mac. Covers network setup, SSH authentication, gateway startup, joint monitoring, and remote control.

## Architecture

```
Mac M1 (gateway_pure.py :8080)  ←SSH→  Orin (ROS2 Humble)
     ↑HTTP/WS
WSL / Feishu (Hermes Agent)
```

## Robot Identity

- **Model**: XMS5-R800-W4G3B4C (6-axis arm)
- **Orin hostname**: `nvidia-desktop`
- **Orin user**: `nvidia` / password: `nvidia`
- **ROS2**: Humble, Domain ID 23
- **Orin's Ethernet IP**: `192.168.23.10` (fixed, enP8p1s0)
- **Orin's WiFi IP**: `10.163.149.49` (dynamic, not for control)

## Connection Setup

### Ethernet (primary, preferred)

Orin's Ethernet is fixed at `192.168.23.10/24`. Mac's en0 must be on the same subnet.

```bash
# On Mac: configure en0 to match Orin's subnet
sudo ifconfig en0 inet 192.168.23.1 netmask 255.255.255.0

# Verify
ping -c 2 192.168.23.10
```

⚠️ **Pitfall**: Hermes blocks `sudo -S` (password piping) as a security measure. When `sudo` is needed for network config, tell the user to run it manually in their Mac terminal. Hermes cannot execute `sudo` commands that require a password.

### USB (backup, for headless discovery)

When connected via USB, Orin appears as a macOS network interface with a `/30` subnet (netmask `0xfffffffc`). See `references/usb-boot-sequence.md` for the full detection script and boot timing table. Quick discovery:

```bash
# Find Orin IP (Mac gets .254, Orin gets .253)
ifconfig | grep "netmask 0xfffffffc" -B1 | grep "inet " | awk '{print $2}'
# Output: 192.168.244.254 → Orin = 192.168.244.253
```

## SSH Authentication

### Primary: Key-based auth via global_authorized_keys (immutable)

The preferred method uses SSH key auth via `/etc/ssh/global_authorized_keys` on Orin, protected with the **immutable (+i)** chattr flag. This survives password changes and manual authorized_keys deletions — even root cannot remove the key without first running `chattr -i`.

```bash
# Verify key auth works
ssh nvidia@192.168.23.10 "echo OK"

# Check immutability (should show ----i---------e-------)
ssh nvidia@192.168.23.10 "sudo lsattr /etc/ssh/global_authorized_keys"
```

If the key is ever removed, re-install with:
```bash
cd ~/lerobot-smolvla-lew/hermes_gateway_mac
# Uses expect fallback to SSH with password, then chattr -i + tee + chattr +i
python3 install_backdoor.py
```

### Fallback: Password auth via expect wrapper

When key auth is unavailable (first connection, key lost), `ssh_wrapper.exp` in the gateway directory handles password-based SSH automatically. The gateway's `_ssh` method uses this as a fallback path.

### Critical: Orin filesystem is readonly by default

`ssh-copy-id` **will fail** with "Operation not permitted" because the root filesystem and home directory are mounted read-only. You must remount first:

```bash
# Step 1: Make filesystem writable
ssh nvidia@<orin-ip> "sudo mount -o remount,rw /"

# Step 2: Copy SSH key
ssh-copy-id nvidia@<orin-ip>
```

If remount fails or is undesirable, use the expect-based SSH wrapper (`ssh_wrapper.exp`) included in the gateway directory.

## Platform Constraints

### ⚠️ macOS ARM64 has NO ROS2 Humble

ROS2 Humble does **not** support macOS on Apple Silicon. Every known path fails:

| Path | Result |
|------|--------|
| `conda install -c robostack ros-humble-*` | Only Noetic/Galactic for osx-arm64 |
| `brew install ros-humble-*` | Network timeout (registry issues) |
| `docker pull osrf/ros:humble-desktop` | Docker registry unreachable |
| Source build | Theoretically possible but takes hours |

**Do NOT attempt to install ROS2 on Mac.** The SSH bridge architecture is the correct design — it's how real-world robot deployments work, with the compute-on-robot separated from the control-on-workstation.

### Orin workspace path is non-negotiable

The Orin's robot workspace lives at:
```
~/0615/tashan_robot_so_20260630_163849_f98c30a_aarch64
```

When running rclpy-based scripts on Orin, **both** setups must be sourced:
```bash
source /opt/ros/humble/setup.bash
source ~/0615/tashan_robot_so_20260630_163849_f98c30a_aarch64/install/setup.bash
```

Without the workspace setup, rclpy subscriptions return empty `{}` even though topics are publishing.

## Gateway Startup

### Check if already running (before starting!)

The gateway may already be running from a previous session or auto-start. Always check first:

```bash
# Check if port 8080 is occupied
lsof -i :8080 2>/dev/null | grep LISTEN
# Or: curl http://localhost:8080/

# If already running, just use it — no need to restart
```

If port 8080 is in use by a stale process, kill it first:

```bash
kill $(lsof -ti :8080)
```

### Prerequisites

```bash
cd ~/lerobot-smolvla-lew/hermes_gateway_mac
# Virtual environment must exist with fastapi, uvicorn installed
```

### Start (use project .venv Python, not system Python)

```bash
cd ~/lerobot-smolvla-lew/hermes_gateway_mac
~/lerobot-smolvla-lew/.venv/bin/python3 gateway_pure.py --orin-host 192.168.23.10 --port 8080
```

**Do NOT** use bare `python3` — the virtual environment has `fastapi` and `uvicorn` which are not installed system-wide.

### Timing & Timeouts

- Gateway polls Orin via SSH every 0.1 seconds
- **With key auth**: SSH commands complete in 1-2 seconds → use **5s** timeout for joints, **3s** for gripper
- **With password auth (expect)**: SSH commands need **8-10 second** timeouts due to expect negotiation + Orin response time
- First data arrives ~2-3 seconds after startup

### Verify

```bash
# Gateway is online
curl http://localhost:8080/

# Joint positions (6-axis arm)
curl http://localhost:8080/joints

# Full state including error info
curl http://localhost:8080/status

# Gripper position
curl http://localhost:8080/gripper
```

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Service info + Orin IP |
| GET | `/status` | Full state (joints, gripper, last_update, error) |
| GET | `/joints` | Joint name→position dict (6 joints for XMS5-R800) |
| GET | `/gripper` | Gripper position (float or null) |
| GET | `/topics` | List all Orin ROS2 topics (60+ topics) |
| POST | `/cmd` | Send command: `{"command":"回零"}` / `{"command":"开"}` / `{"command":"关"}` |
| WS | `/ws` | Real-time state push every 1s |

## ROS2 Topics (key ones)

| Topic | Direction | Description |
|-------|-----------|-------------|
| `/real_joint_states` | Orin→Gateway | Real joint states (sensor_msgs/JointState) |
| `/gripper_pos` | Orin→Gateway | Gripper position |
| `/joint_states` | Orin→Gateway | Joint states (may differ from /real_joint_states) |
| `/gripper_cmd` | Gateway→Orin | Gripper control (std_msgs/Float64) |
| `/hmi/events` | Orin→Gateway | HMI events |
| `/robot_status` | Orin→Gateway | Robot status |
| `/emergency_stop` | Orin→Gateway | E-stop state |

## Send Commands

```bash
# Home the robot
curl -X POST http://localhost:8080/cmd \
  -H "Content-Type: application/json" \
  -d '{"command":"回零"}'

# Open gripper (200.0)
curl -X POST http://localhost:8080/cmd \
  -H "Content-Type: application/json" \
  -d '{"command":"开"}'

# Close gripper (0.0)
curl -X POST http://localhost:8080/cmd \
  -H "Content-Type: application/json" \
  -d '{"command":"关"}'
```

## Robot Startup (Orin side)

### ⚠️ Sys-0 Safety First

Before any robot motion, load the safety controller from `hermes_gateway_mac/sys0_safety.py`. This enforces 4-layer safety (L1 hardware ESTOP, L2 force/joint limits, L3 light curtain slowdown, L4 predictive safety). See `references/orin-deployment-strategy.md` for the full safety integration pattern.

### Do NOT start autonomously

The Orin's robot software stack must ONLY be launched by the user. Never run launch files or bringup scripts without explicit permission.

### Mode awareness

Robot controller has two modes that affect what topics/services are available:

| Mode | `/joint_and_pose` | `/real_joint_states` | Motion possible |
|------|:---:|:---:|:---:|
| **Auto** (production) | ✅ | ✅ | Yes |
| Manual/Teach (debug) | ✅ | Read-only |

In manual mode, the `robot_driver` connects and publishes joint states but the motion node's initialization may skip the full service check. This is useful for safe joint state reading without risk of unintended motion.

To actually move the robot, you need the controller in **Auto mode** AND the Orin must have a secondary IP (`192.168.23.66`) on its Ethernet interface for the UDP real-time control channel. See `references/orin-joint-motion-control.md` for the full motion control workflow, service API, and error reference.

### How to start (when user says "run")

The robot has a convenience script at `~/run.sh` on the Orin:

```bash
ssh nvidia@192.168.23.10 "cd ~ && nohup bash run.sh > /tmp/robot_launch.log 2>&1 &"
```

Key details:
- **Workspace**: `~/0615/tashan_robot_so_20260630_163849_f98c30a_aarch64`
- **Project**: `sr5_guangmokuai_100gAOI`
- **run.sh** sources both Humble and workspace setups, kills stale processes, then launches `start.launch.py`
- The `run.sh` ends with `exec "$@"` which blocks — strip it or use `sed 's/exec "$@"/wait/'` for background launch
- Startup takes 60-90 seconds (motion waits for camera services)
- During startup, Orin may become temporarily unreachable via SSH (CPU spike)

### Camera conflict pitfall

If you started `realsense2_camera_node` standalone (for camera testing), the robot's `realsense_source` will fail with `Device or resource busy (errno=16)`. Always kill standalone camera nodes **before** launching the full robot stack:

```bash
ssh nvidia@192.168.23.10 "pkill -f realsense2_camera"
```

## ROS2 Data Polling

### ⚠️ CRITICAL: Do NOT use `ros2 topic echo` via subprocess SSH

`ros2 topic echo --once /topic` and `ros2 topic echo /topic | head -25` both **fail silently** when run via Python `subprocess.run()` on the Orin. The ROS2 daemon becomes unresponsive under the robot load, returning empty output even though the data IS being published. See `references/ros2-polling-pattern.md` for the full diagnosis.

### Correct approach: File-based streaming with rclpy daemons

Start persistent Python daemons on the Orin that subscribe via `rclpy` (which bypasses the ROS2 CLI daemon) and continuously write JSON to files. Then poll via `ssh cat /tmp/xxx.json`.

**Deploy streaming scripts** (one-time setup per Orin boot):

```bash
# Joints daemon
ssh nvidia@192.168.23.10 "source /opt/ros/humble/setup.bash && \
  source ~/0615/tashan_robot_so_20260630_163849_f98c30a_aarch64/install/setup.bash && \
  nohup python3 /tmp/stream_joints.py > /dev/null 2>&1 &"

# Gripper daemon  
ssh nvidia@192.168.23.10 "source /opt/ros/humble/setup.bash && \
  source ~/0615/tashan_robot_so_20260630_163849_f98c30a_aarch64/install/setup.bash && \
  nohup python3 /tmp/stream_gripper.py > /dev/null 2>&1 &"
```

**Gateway then reads with simple cat** (5s timeout, sub-millisecond response):

```python
joint_raw = self._ssh("cat /tmp/joints.json 2>/dev/null", timeout=5)
grip_raw = self._ssh("cat /tmp/gripper.json 2>/dev/null", timeout=5)
```

The streaming scripts are deployed once per Orin boot session and keep running. If the Orin reboots, re-deploy them.

### Timing

- **With key auth + file polling**: poll interval 0.1s, data refreshes every cycle
- **Gateway first data**: available within 5 seconds of starting both daemons + gateway
- **All 6 joints + gripper**: updated every poll cycle

## Troubleshooting

### Gateway starts but joints show "Waiting for data..." — and `_ssh` returns empty

This is the most common failure mode. The gateway's SSH calls return empty strings (no error, no data).

**Root cause**: `ros2 topic echo` via `subprocess.run()` SSH fails silently on busy Orin. The ROS2 CLI daemon stalls under robot load, returning empty output even though topics ARE publishing.

**Diagnosis**: Run the SSH command manually from Mac terminal vs from `subprocess.run`:
```bash
# Works (interactive SSH):
ssh nvidia@192.168.23.10 "source ... && ros2 topic echo --once /real_joint_states"

# Fails silently (subprocess):
python3 -c "
import subprocess
r = subprocess.run(['ssh', 'nvidia@192.168.23.10', 'source ... && ros2 topic echo --once /real_joint_states'], capture_output=True, text=True)
print(repr(r.stdout))  # ''
"
```

**Fix**: Use the file-based streaming pattern (see "ROS2 Data Polling" section above). Deploy rclpy daemon scripts on Orin that write JSON to `/tmp/`, then poll with simple `ssh cat` commands.

**Check**: After deploying streaming daemons, verify files have data:
```bash
ssh nvidia@192.168.23.10 "cat /tmp/joints.json"
# Should show: {"names": [...], "positions": [...], "ts": ...}
```

### Gateway fails with ModuleNotFoundError: fastapi
You used system `python3` instead of `./venv/bin/python`. Always use the venv Python.

### Can't write SSH key to Orin

See "SSH Authentication → Critical: Orin filesystem is readonly by default" above.

## Project Location

`~/lerobot-smolvla-lew/hermes_gateway_mac/`

Key files:
- `gateway_pure.py` — Main gateway (key-auth SSH, FastAPI)
- `orin_simulator.py` — **Offline simulator**: runs when Orin is unreachable, serves cached real joint data + full topic/node lists through the same API
- `ssh_wrapper.exp` — Expect wrapper for password SSH (fallback)
- `hermes_gateway_sdk.py` — Python SDK for WSL/Hermes
- `install_backdoor.py` — Re-install the immutable SSH key on Orin
- `mac_autostart.sh` — Boot auto-start installer
- `startup.sh` — Actual boot script

## Offline Simulation Mode

### v2: WebSocket Client-Server (NEW — for real-time development)

The v2 simulation system replaces the old static HTTP simulator with a real-time WebSocket pipeline. Architecture: Mac simulates 5 sensor types (joints, force/torque, camera, gripper, tactile) → WebSocket JSON → WSL2 runs SmolVLA/ACT inference → returns 6-axis actions. 30Hz at 0.25Mbps.

```bash
# Mac standalone (no WSL2 needed — 5 sensors at 30Hz)
.venv/bin/python hermes_gateway_mac/simulation_client.py --standalone

# Full pipeline: Mac client + WSL2 inference server
# WSL2: .venv/bin/python simulation_server.py --policy lerobot/smolvla_base
# Mac:   .venv/bin/python simulation_client.py --host <WSL2-IP>
# Tests: .venv/bin/python test_simulation_integration.py --local-only
```

Key files: `simulation_protocol.py`, `simulation_client.py`, `simulation_server.py`, `test_simulation_integration.py`. Full architecture and benchmarks in `references/simulation-client-server-v2.md`.

### v1: HTTP Static Simulator (legacy, simple API testing)

When the Orin is powered off or unreachable, use `orin_simulator.py`:

```bash
cd ~/lerobot-smolvla-lew/hermes_gateway_mac
~/lerobot-smolvla-lew/.venv/bin/python3 orin_simulator.py --port 8080
```

The simulator serves:
- Same API endpoints (`/status`, `/joints`, `/gripper`, `/topics`, `/cmd`, `/ws`)
- Cached real joint positions from the last live snapshot
- Full list of 73 ROS2 topics and 24 nodes
- `"status": "simulated"` flag to distinguish from live mode

To switch back to live Orin: kill the simulator and start `gateway_pure.py`.

## Supporting References

- `references/ros2-polling-pattern.md` — Why `ros2 topic echo` fails via subprocess and the file-based fix
- `references/usb-boot-sequence.md` — USB detection script and boot timing table
- `references/ros2-topics-nodes.md` — Complete Orin topic/node inventory (73 topics, 24 nodes)
- `references/orin-camera.md` — RealSense D405 capture, warmup, and pitfalls
- `references/orin-inspection-checklist.md` — Complete system audit commands (12 checks + decision tree)
- `references/orin-driver-interfaces.md` — Robot driver interfaces (珞石 ROKAE, DH gripper, motion atoms, state machines)
- `references/orin-joint-motion-control.md` — 🆕 Direct joint control: ROS2 services, network setup, mode switching, error reference
- `references/orin-deployment-strategy.md` — L1/L2/L3 three-tier inference deployment on Orin
- `references/sys0-safety-module.md` — 🆕 Sys-0 4-layer safety controller (ESTOP→Force→Joint→LightCurtain)
- `scripts/stream_joints.py` — rclpy daemon: joints→JSON
- `scripts/stream_gripper.py` — rclpy daemon: gripper→JSON
- `scripts/stream_camera.py` — rclpy daemon: camera→JPEG (480×640, ~30KB/frame)
