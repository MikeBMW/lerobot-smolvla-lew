#!/usr/bin/env python3
"""Z-MAX 状态空间3D 实况守护 (方案A 核心)
轮询 ECS ss3d_cmd.json → 发现新 run 请求 → 本机真实执行 sim.run()
→ 生成 ss_traj_full.json (轨迹) + ss3d_live.json (实况状态) → 上传 ECS
→ 网页/App 轮询 ss3d_live.json 看到 run_id 变化 → 自动装载播放
"""
import json, os, sys, time, subprocess, hashlib

GUI_DIR = "/home/ubuntu/lerobot-smolvla-lew/tools/gui"
PY = "/home/ubuntu/lerobot-smolvla-lew/gui-venv311/bin/python"
ECS_WEB = "/www/wwwroot/datadrive.world"
# ECS 凭据从环境变量读 (不入库): export ECS_PASS=xxx
import os as _os
_ECS_PASS = _os.environ.get("ECS_PASS", "")
SSH = ["sshpass", "-p", _ECS_PASS, "ssh", "-o", "StrictHostKeyChecking=no", "root@datadrive.world"]
SCP = ["sshpass", "-p", _ECS_PASS, "scp", "-o", "StrictHostKeyChecking=no"]
RUNNER = os.path.join(GUI_DIR, "run_ss_once.py")
POLL = 2.0          # 轮询间隔 (秒)
HEARTBEAT = 1.0     # live 心跳间隔

def ecs_run(args):
    r = subprocess.run(SSH + args, capture_output=True, text=True, timeout=30)
    return r.stdout.strip()

def ecs_get(url_path):
    """经公网 HTTP 读 ECS 文件 (比 ssh 快)"""
    import urllib.request
    try:
        with urllib.request.urlopen(f"https://datadrive.world/{url_path}", timeout=8) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None

def ecs_upload(local, remote):
    r = subprocess.run(SCP + [local, f"root@datadrive.world:{remote}"],
                       capture_output=True, text=True, timeout=60)
    return r.returncode == 0

def run_sim(seed):
    """真实执行引擎仿真 → 返回 (轨迹dict, live dict)"""
    print(f"[daemon] ▶ 执行仿真 seed={seed} ...")
    r = subprocess.run([PY, RUNNER, str(seed)], capture_output=True, text=True,
                       timeout=300, cwd=GUI_DIR)
    if r.returncode != 0:
        print(f"[daemon] ❌ 仿真失败: {r.stderr[-500:]}")
        return None
    out_path = "/tmp/ss_run_out.json"
    with open(out_path) as f:
        data = json.load(f)
    print(f"[daemon] ✅ 仿真完成: {data.get('n')} 帧 done={data.get('done')} dist={data.get('dist_final')}")
    return data

def upload_live(live, traj):
    """上传 live + 轨迹; 网页 250ms 轮询到 run_id 变化即装载"""
    with open("/tmp/ss3d_live.json", "w") as f:
        json.dump(live, f, ensure_ascii=False)
    with open("/tmp/ss_traj_live.json", "w") as f:
        json.dump(traj, f, ensure_ascii=False)
    ok1 = ecs_upload("/tmp/ss3d_live.json", f"{ECS_WEB}/ss3d_live.json")
    ok2 = ecs_upload("/tmp/ss_traj_live.json", f"{ECS_WEB}/ss_traj_full.json")
    print(f"[daemon] 上传: live={ok1} traj={ok2}")
    return ok1 and ok2

def main():
    print("[daemon] Z-MAX 3D 实况守护启动, 轮询 ECS 命令...")
    last_ts = None
    run_id_counter = int(time.time())
    while True:
        try:
            # 1. 读命令
            cmd = ecs_get("ss3d_cmd.json")
            if cmd and cmd.get("ts") and cmd["ts"] != last_ts:
                last_ts = cmd["ts"]
                seed = cmd.get("seed", 100)
                print(f"[daemon] 收到命令 ts={last_ts} seed={seed}")
                data = run_sim(seed)
                if data:
                    run_id = f"run{run_id_counter}"; run_id_counter += 1
                    live = {
                        "run_id": run_id, "playing": False,
                        "i": data["n"] - 1, "n": data["n"],
                        "done": data["done"], "dist": data["dist_final"],
                        "beat": time.time(),
                    }
                    upload_live(live, data)
                    print(f"[daemon] 已发布 run_id={run_id}")
                # 清命令标记 (防止重复执行)
                ecs_run([f"rm -f {ECS_WEB}/ss3d_cmd.json"])
            else:
                time.sleep(POLL)
        except KeyboardInterrupt:
            print("[daemon] 停止")
            break
        except Exception as e:
            print(f"[daemon] 错误: {e}")
            time.sleep(POLL * 2)

if __name__ == "__main__":
    main()
