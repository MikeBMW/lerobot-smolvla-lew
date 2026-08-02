#!/usr/bin/env python3
"""Z-MAX Orin 全量状态采集 · 上报 ECS (控制台/老倪实时查看)
采集: CPU/GPU/内存/温度/磁盘/进程/ROS2节点/推理服务/关节数据
上报: POST /orin/heartbeat (ECS聚合) · 心跳内嵌 sys 字段
"""
import json, subprocess, time, socket, os, re


def sh(cmd, timeout=5):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""


def collect_system():
    """采集 Orin 系统全量状态"""
    sys_info = {"host": socket.gethostname(), "ts": time.strftime("%H:%M:%S")}

    # CPU
    cpu = sh("top -bn1 | head -5 | grep 'Cpu(s)'")
    m = re.search(r"(\d+\.\d+)\s*id", cpu)
    sys_info["cpu_usage_pct"] = round(100 - float(m.group(1)), 1) if m else None
    sys_info["cpu_load"] = sh("cat /proc/loadavg").split()[:3]

    # 内存
    try:
        with open("/proc/meminfo") as f:
            d = dict(l.strip().split(":", 1) for l in f if ":" in l)
        total = int(d.get("MemTotal", 0)) // 1024
        avail = int(d.get("MemAvailable", 0)) // 1024
        sys_info["mem_total_mb"] = total
        sys_info["mem_used_pct"] = round((total - avail) / total * 100, 1) if total else None
    except Exception:
        pass

    # GPU (Jetson: tegrastats / nvidia-smi)
    gpu = sh("nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu,temperature.gpu --format=csv,noheader 2>/dev/null || tegrastats --interval 1 2>/dev/null | head -1")
    sys_info["gpu"] = gpu[:120] if gpu else "N/A"

    # 温度
    temps = []
    for tpath in ["/sys/devices/virtual/thermal/thermal_zone0/temp",
                  "/sys/devices/virtual/thermal/thermal_zone1/temp"]:
        t = sh(f"cat {tpath} 2>/dev/null")
        if t:
            temps.append(round(int(t) / 1000, 1))
    sys_info["temp_c"] = temps

    # 磁盘
    df = sh("df -h / | tail -1").split()
    sys_info["disk"] = f"{df[4] if len(df) > 4 else '?'} used"

    # ROS2 节点
    ros = sh("source /opt/ros/humble/setup.bash && timeout 3 ros2 node list 2>/dev/null | wc -l", timeout=8)
    sys_info["ros2_nodes"] = int(ros) if ros.isdigit() else 0

    # 关键进程
    procs = sh("ps aux | grep -E 'orin_infer|stream_|ros2' | grep -v grep | wc -l", timeout=5)
    sys_info["active_procs"] = int(procs) if procs.isdigit() else 0

    # 推理服务 (本机 :8766)
    try:
        import requests as _r
        st = _r.get("http://127.0.0.1:8766/status", timeout=3).json()
        sys_info["infer"] = st
    except Exception:
        sys_info["infer"] = {"online": False}

    # 关节数据 (ROS2 topic)
    js = sh("source /opt/ros/humble/setup.bash && timeout 3 ros2 topic echo /real_joint_states --once 2>/dev/null | grep -c position:", timeout=8)
    sys_info["joints"] = int(js) if js.isdigit() else 0

    return sys_info


if __name__ == "__main__":
    info = collect_system()
    print(json.dumps(info, ensure_ascii=False, indent=1))
