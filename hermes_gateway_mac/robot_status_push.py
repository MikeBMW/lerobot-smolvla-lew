#!/usr/bin/env python3
"""
Z-MAX 机器人状态推送脚本 · 小芳侧 (Mac M1 / Orin)

用法:
  python3 robot_status_push.py          # 发送一次
  python3 robot_status_push.py --loop 5 # 每5秒循环发送

数据协议: POST JSON → http://datadrive.world/robot-status-api.php
"""
import requests, json, time, argparse, random
from datetime import datetime

URL = "http://datadrive.world/robot-status-api.php"

def generate_status(source="orin"):
    """生成仿真状态数据(真机格式)"""
    return {
        "timestamp": datetime.now().isoformat(),
        "robot": "Z700",
        "source": "Orin ROS2" if source == "orin" else "Mac M1 MPS",
        "status": "running",
        "joints": {
            "base": round(random.uniform(-0.5, 0.5), 3),
            "shoulder": round(random.uniform(0.8, 1.5), 3),
            "elbow": round(random.uniform(-2.0, -0.5), 3),
            "wrist1": round(random.uniform(-1.5, 1.5), 3),
            "wrist2": round(random.uniform(-1.5, 1.5), 3),
            "wrist3": round(random.uniform(-1.5, 1.5), 3),
        },
        "force": {
            "fx": round(random.uniform(-0.5, 0.5), 3),
            "fy": round(random.uniform(-0.5, 0.5), 3),
            "fz": round(random.uniform(-2.0, 5.0), 3),
            "tx": round(random.uniform(-0.3, 0.3), 3),
            "ty": round(random.uniform(-0.3, 0.3), 3),
            "tz": round(random.uniform(-0.5, 0.5), 3),
        },
        "gripper": random.randint(100, 255),
        "camera": {"fps": 30, "resolution": "512x512"},
        "temperature": {
            "cpu": round(random.uniform(40, 55), 1),
            "gpu": round(random.uniform(45, 65), 1),
        },
        "errors": [],
    }

def push(data):
    try:
        r = requests.post(URL, json=data, timeout=5)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ {r.json()}")
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", type=int, default=0, help="循环间隔(秒), 0=发送一次")
    parser.add_argument("--source", choices=["orin", "mac"], default="orin")
    args = parser.parse_args()

    print(f"🚀 Z-MAX 状态推送 | 目标: {URL} | 数据源: {args.source}")
    
    if args.loop > 0:
        print(f"   循环模式: 每{args.loop}s")
        while True:
            push(generate_status(args.source))
            time.sleep(args.loop)
    else:
        push(generate_status(args.source))
