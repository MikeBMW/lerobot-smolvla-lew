#!/usr/bin/env python3
"""
Z-MAX 机器人状态推送 v2 · 小芳侧
  --mode light : 增量(轻量, 默认30min定时)
  --mode full  : 全量(所有关节/拓扑/相机缩略图, 手动刷新触发)

用法:
  python3 robot_status_push.py --mode light --source orin
  python3 robot_status_push.py --mode full --source orin   # 全量
  python3 robot_status_push.py --mode light --source orin --loop 1800  # 30min定时
"""
import requests, json, time, argparse, random, base64, os
from datetime import datetime
from io import BytesIO

URL = "http://datadrive.world/robot-status-api.php"

TOPICS = [
    "/joint_states", "/robot_status", "/force_torque", "/gripper/state",
    "/camera/color/image_raw", "/camera/depth/image_raw",
    "/camera/infra1/image_raw", "/tf", "/tf_static",
    "/diagnostics", "/rosout", "/controller/state",
    "/move_group/status", "/planning_scene", "/joint_trajectory",
    "/follow_joint_trajectory/status", "/servo_server/status",
    "/io/status"
]

def generate_full(source="orin"):
    joints = {f"joint_{i}": round(random.uniform(-3.14, 3.14), 3) for i in range(1,7)}
    joint_velocities = {f"joint_{i}": round(random.uniform(-1.0, 1.0), 3) for i in range(1,7)}
    joint_torques = {f"joint_{i}": round(random.uniform(-5.0, 5.0), 2) for i in range(1,7)}

    topics = []
    for t in TOPICS:
        hz = round(random.uniform(0, 100), 1) if random.random()>0.1 else 0
        topics.append({"name":t, "hz":hz, "status":"ok" if hz>0 else "stale"})

    # Realsense mock: generate a small dark image
    try:
        from PIL import Image
        img = Image.new('RGB', (160,120), (10,15,20))
        buf = BytesIO()
        img.save(buf, format='JPEG', quality=30)
        img_b64 = base64.b64encode(buf.getvalue()).decode()
    except:
        img_b64 = ""

    return {
        "timestamp": datetime.now().isoformat(),
        "robot": "Z700",
        "source": "Orin Jetson AGX" if source=="orin" else "Mac M1",
        "status": "running",
        "gripper": random.randint(100,255),
        "joints": joints,
        "joint_velocities": joint_velocities,
        "joint_torques": joint_torques,
        "force": {"fx":round(random.uniform(-0.5,0.5),3),"fy":round(random.uniform(-0.5,0.5),3),
                  "fz":round(random.uniform(-2.0,5.0),3),"tx":round(random.uniform(-0.3,0.3),3),
                  "ty":round(random.uniform(-0.3,0.3),3),"tz":round(random.uniform(-0.5,0.5),3)},
        "topics": topics,
        "camera": {"fps":30,"resolution":"512x512","realsense":"D435i"},
        "realsense_image": img_b64,
        "temperature": {"cpu":round(random.uniform(40,55),1),"gpu":round(random.uniform(45,65),1)},
        "memory": {"total_gb":7.6,"used_gb":round(random.uniform(2,5),1),"free_gb":0},
        "errors": [],
    }

def generate_light(source="orin"):
    return {
        "timestamp": datetime.now().isoformat(),
        "robot": "Z700",
        "source": "Orin Jetson AGX" if source=="orin" else "Mac M1",
        "status": "running",
        "gripper": random.randint(100,255),
        "joints": {f"joint_{i}": round(random.uniform(-3.14,3.14),3) for i in range(1,7)},
        "force": {"fz":round(random.uniform(-2.0,5.0),3)},
        "temperature": {"cpu":round(random.uniform(40,55),1),"gpu":round(random.uniform(45,65),1)},
        "errors": [],
    }

def push(data, mode="light"):
    try:
        r = requests.post(f"{URL}?mode={mode}", json=data, timeout=10)
        resp = r.json()
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ {resp.get('mode',mode)} | {resp.get('time','')}")
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ {e}")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["light","full"], default="light")
    p.add_argument("--source", choices=["orin","mac"], default="orin")
    p.add_argument("--loop", type=int, default=0)
    args = p.parse_args()

    gen = generate_full if args.mode=="full" else generate_light
    print(f"Z-MAX 状态推送 v2 | 模式:{args.mode} | 源:{args.source}")
    if args.loop>0:
        print(f"每{args.loop}s循环")
        while True:
            push(gen(args.source), args.mode)
            time.sleep(args.loop)
    else:
        push(gen(args.source), args.mode)
