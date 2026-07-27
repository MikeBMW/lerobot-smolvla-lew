#!/usr/bin/env python3
"""Orin TCP 关节数据流 — 实时推送到 Mac"""
import socket, json, subprocess, time, os

HOST = "0.0.0.0"
PORT = 9870

def get_joints():
    r = subprocess.run([
        "bash", "-c",
        "source /opt/ros/humble/setup.bash && "
        "source ~/0615/tashan_robot_so_20260630_163849_f98c30a_aarch64/install/setup.bash && "
        "export ROS_DOMAIN_ID=23 && "
        "ros2 topic echo --once /real_joint_states 2>/dev/null"
    ], capture_output=True, text=True, timeout=5)
    import re
    pos = []
    for line in r.stdout.split("\n"):
        m = re.search(r"^\s*-\s*([\d.\-]+)", line)
        if m: pos.append(float(m.group(1)))
    return pos[:6] if len(pos) >= 6 else []

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind((HOST, PORT))
s.listen(1)
print(f"TCP Server: {PORT}")

while True:
    conn, addr = s.accept()
    print(f"Client: {addr}")
    try:
        while True:
            joints = get_joints()
            if joints:
                conn.send((json.dumps({"joints": joints, "t": time.time()}) + "\n").encode())
            time.sleep(0.05)
    except:
        conn.close()
