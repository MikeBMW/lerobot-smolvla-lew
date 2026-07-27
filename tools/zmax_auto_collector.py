#!/usr/bin/env python3
"""Z-MAX 自动化数据采集守护 · MAC端 · 持续循环轮询"""
import requests, subprocess, time, os, json

ORIN, ORIN_PW = "tashan@192.168.23.10", "ts123"
BACKEND = "http://106.75.239.80:50053"
MAC_DATA = os.path.expanduser("~/zmax_loop")
os.makedirs(MAC_DATA, exist_ok=True)

def log(msg):
    t = time.strftime("%H:%M:%S")
    print(f"[{t}] {msg}")

def run_ssh(cmd, timeout=60):
    return subprocess.run(["sshpass","-p",ORIN_PW,"ssh","-o","StrictHostKeyChecking=no",
        ORIN, cmd], capture_output=True, text=True, timeout=timeout)

def do_cycle(cycle_num):
    log(f"=== 循环 {cycle_num} ===")
    ts = time.strftime("%Y%m%d_%H%M%S")
    
    # 1. Orin录制30s MCAP
    log("Orin录制30秒MCAP...")
    r = run_ssh(f"source /opt/ros/humble/setup.bash && timeout 30 ros2 bag record -o /tmp/orin_auto_{ts} /realsense/color/image_raw /real_joint_states", timeout=35)
    
    # 2. 拉取MCAP
    log("拉取MCAP到MAC...")
    subprocess.run(["sshpass","-p",ORIN_PW,"scp","-o","StrictHostKeyChecking=no","-r",
        f"{ORIN}:/tmp/orin_auto_{ts}", MAC_DATA], timeout=15)
    
    # 3. 通知4090
    log("通知4090训练...")
    try:
        requests.post(f"{BACKEND}/train", json={"source":"orin","path":f"mac:{MAC_DATA}/orin_auto_{ts}"}, timeout=5)
    except:
        pass

log("Z-MAX 自动采集守护启动")
cycle = 1
while True:
    try:
        # 检查4090指令
        r = requests.get(f"{BACKEND}/command", timeout=3)
        cmd = r.json().get("cmd","collect") if r.ok else "collect"
        
        if cmd == "collect":
            do_cycle(cycle)
            cycle += 1
        time.sleep(5)
    except Exception as e:
        log(f"错误: {e}")
        time.sleep(10)
