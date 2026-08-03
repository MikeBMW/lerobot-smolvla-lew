#!/usr/bin/env python3
"""Orin 系统性能采集 → 心跳 sys 字段 (供 cicd.html 显示)
小芳在 Orin 侧运行: orin_infer_service.py 心跳里调用本函数
返回: {"cpu":%, "gpu":%, "mem":%, "disk":%, "net":KB/s, "temp":°C}
"""
import os, subprocess, time

_last_net = None
_last_ts = 0.0


def get_sys_info():
    global _last_net, _last_ts
    info = {}

    # CPU
    try:
        import psutil
        info["cpu"] = round(psutil.cpu_percent(interval=0.2), 1)
        info["mem"] = psutil.virtual_memory().percent
        info["disk"] = psutil.disk_usage("/").percent
    except ImportError:
        with open("/proc/loadavg") as f:
            info["cpu"] = round(float(f.read().split()[0]) * 100, 1)
        with open("/proc/meminfo") as f:
            lines = dict(l.split(":", 1) for l in f if ":" in l)
            total = int(lines["MemTotal"].split()[0])
            avail = int(lines["MemAvailable"].split()[0])
            info["mem"] = round((1 - avail / total) * 100, 1)
        try:
            st = os.statvfs("/")
            info["disk"] = round((1 - st.f_bavail / st.f_blocks) * 100, 1)
        except Exception:
            info["disk"] = 0

    # GPU (Jetson tegrastats 或 nvidia-smi)
    try:
        r = subprocess.run(["tegrastats", "--interval", "500"],
                           capture_output=True, text=True, timeout=1.5)
        if r.stdout:
            line = r.stdout.strip().splitlines()[-1]
            import re
            m = re.search(r"GR3D_FREQ (\d+)%", line)
            info["gpu"] = int(m.group(1)) if m else 0
    except Exception:
        try:
            r = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu",
                                "--format=csv,noheader,nounits"],
                               capture_output=True, text=True, timeout=2)
            info["gpu"] = int(r.stdout.strip().split("\n")[0])
        except Exception:
            info["gpu"] = 0

    # 温度
    try:
        with open("/sys/devices/virtual/thermal/thermal_zone0/temp") as f:
            info["temp"] = round(int(f.read().strip()) / 1000, 1)
    except Exception:
        try:
            r = subprocess.run(["cat", "/sys/class/thermal/thermal_zone0/temp"],
                               capture_output=True, text=True, timeout=1)
            info["temp"] = round(int(r.stdout.strip()) / 1000, 1)
        except Exception:
            info["temp"] = 0

    # 网络带宽 (KB/s, 基于 /proc/net/dev 差分)
    try:
        now = time.time()
        with open("/proc/net/dev") as f:
            total_bytes = 0
            for l in f.readlines()[2:]:
                parts = l.split(":")
                if len(parts) > 1:
                    vals = parts[1].split()
                    total_bytes += int(vals[0]) + int(vals[8])  # rx + tx
        if _last_net is not None and now - _last_ts > 0:
            info["net"] = round((total_bytes - _last_net) / 1024 / (now - _last_ts), 1)
        else:
            info["net"] = 0
        _last_net, _last_ts = total_bytes, now
    except Exception:
        info["net"] = 0

    return info


if __name__ == "__main__":
    import json
    print(json.dumps(get_sys_info()))
