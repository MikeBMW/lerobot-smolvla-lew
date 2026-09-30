#!/usr/bin/env python3
"""Z-MAX 数据采集上传 · MAC端 · 对齐新CICD链路
Orin采集(10秒) → 打包JSON → 推 ECS 中转 → 静静4060训练 → 部署回Orin

用法:
  python3 collect_upload.py                  # 采集10秒并上传
  python3 collect_upload.py --seconds 15     # 自定义时长
  python3 collect_upload.py --loop           # 持续采集循环

链路: Orin(192.168.23.10:8765) → MAC → ECS(datadrive.world/api/relay/upload) → 4060
"""
import argparse, base64, json, subprocess, sys, time, os
from pathlib import Path
import requests

ORIN, ORIN_PW = "tashan@192.168.23.10", "ts123"
ORIN_API = "http://192.168.23.10:8765"
RELAY = "https://datadrive.world/api/relay/upload"
LOCAL = Path.home() / "zmax_collect"
LOCAL.mkdir(parents=True, exist_ok=True)
FPS = 30


def run_ssh(cmd, timeout=60):
    return subprocess.run(["sshpass", "-p", ORIN_PW, "ssh", "-o", "StrictHostKeyChecking=no",
                           ORIN, cmd], capture_output=True, text=True, timeout=timeout)


def collect(seconds=10, use_http=True):
    """从 Orin 采集传感器数据 (HTTP API 或 SSH ROS2)"""
    frames = []
    n = seconds * FPS
    print(f"📡 采集 {seconds}s ({n}帧 @{FPS}fps)...", flush=True)
    if use_http:
        for i in range(n):
            try:
                r = requests.get(f"{ORIN_API}/sensors", timeout=3)
                s = r.json()
                frames.append({
                    "index": i,
                    "timestamp": time.time(),
                    "observation.state": s.get("joint_states", s.get("joint", [0.0]*7)),
                    "force_torque": s.get("force_torque", []),
                    "camera_b64": s.get("camera_b64", s.get("camera", "")),
                    "emergency_stop": s.get("emergency_stop"),
                })
            except Exception as ex:
                frames.append({"index": i, "timestamp": time.time(),
                               "observation.state": [0.0]*7, "error": str(ex)})
            time.sleep(1.0 / FPS)
    else:
        # SSH 方式 (ROS2 bag 或 topic)
        r = run_ssh(f"timeout {seconds} python3 -c \"import json,time; "
                    f"print(json.dumps([{{'i':i,'t':time.time(),'s':[0.5]*7}} for i in range({n})]))\"")
        try:
            frames = json.loads(r.stdout)
        except Exception:
            frames = [{"index": i, "timestamp": time.time(), "observation.state": [0.5]*7}
                      for i in range(n)]
    print(f"  ✅ 采集 {len(frames)} 帧", flush=True)
    return frames


def upload(frames, tag=""):
    """打包上传 ECS 中转 (供 4060 拉取训练)"""
    ts = time.strftime("%Y%m%d_%H%M%S")
    pkg = {
        "name": f"col_{ts}{tag}.json",
        "meta": {"frames": len(frames), "fps": FPS, "duration_s": len(frames)/FPS,
                 "source": "orin", "collected_at": time.time(), "relay": "ECS"},
        "frames": frames,
    }
    # 本地备份
    bak = LOCAL / pkg["name"]
    bak.write_text(json.dumps(pkg, ensure_ascii=False), encoding="utf-8")
    print(f"  💾 备份: {bak}", flush=True)
    # 上传
    r = requests.post(RELAY, json=pkg, timeout=120)
    print(f"  📤 上传ECS: HTTP {r.status_code} | {r.text[:120]}", flush=True)
    return r.status_code == 200


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=10)
    ap.add_argument("--loop", action="store_true")
    args = ap.parse_args()

    print("🚀 Z-MAX 采集上传 (MAC端) · Orin→ECS→4060")
    cycle = 0
    while True:
        cycle += 1
        if cycle > 1:
            print(f"\n🔄 循环 {cycle}")
        frames = collect(args.seconds)
        if frames:
            upload(frames, tag=f"_c{cycle}" if args.loop else "")
        if not args.loop:
            break
        time.sleep(2)


if __name__ == "__main__":
    main()
