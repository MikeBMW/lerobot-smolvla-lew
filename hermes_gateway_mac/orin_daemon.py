#!/usr/bin/env python3
"""Orin数据流守护 — 可靠轮询ROS2写入/tmp/joints.json"""
import subprocess, time, json, re, os

CMD = "source /opt/ros/humble/setup.bash && source ~/0615/tashan_robot_so_20260630_163849_f98c30a_aarch64/install/setup.bash && export ROS_DOMAIN_ID=23 && ros2 topic echo --once /real_joint_states 2>/dev/null"

def poll():
    while True:
        try:
            r = subprocess.run(["bash", "-c", CMD], capture_output=True, text=True, timeout=8)
            pos = []
            for line in r.stdout.split("\n"):
                m = re.search(r"^\s*-\s*([\d.\-]+)", line)
                if m: pos.append(str(round(float(m.group(1)), 4)))
            if len(pos) >= 6:
                with open("/tmp/joints.json", "w") as f:
                    f.write(",".join(pos[:6]))
        except:
            pass
        time.sleep(0.2)

