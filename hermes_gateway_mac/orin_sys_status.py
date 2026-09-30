#!/usr/bin/env python3
"""Orin 系统性能采集 v2 → 心跳 sys 字段 (cicd.html 显示)
格式规范 (老倪要求): 全部带单位 + 已用/总量
{
  "cpu": {"pct": 97.9},                          # CPU 百分比
  "gpu": {"pct": 45.0, "model": "orin-integrated"},  # GPU 百分比(tegrastats GR3D)
  "mem": {"pct": 69.0, "used_gb": 10.5, "total_gb": 15.3},   # 内存
  "disk": {"pct": 25.3, "used_gb": 46.2, "total_gb": 182.7}, # 磁盘
  "net": {"rx_kbps": 7522.4, "tx_kbps": 7637.8, "rx_total_gb": 12.3, "tx_total_gb": 5.1},  # 带宽
  "temp": {"c": 60.4},                           # 温度
  "load": [16.45, 15.88, 12.9]                   # 负载
}
"""
import os, re, time, subprocess

_last_net = None
_last_ts = 0.0


def _gb(bytes_):
    return round(bytes_ / 1024 / 1024 / 1024, 1)


def get_sys_info():
    global _last_net, _last_ts
    info = {}

    # ── CPU + 负载 ──
    try:
        import psutil
        info["cpu"] = {"pct": round(psutil.cpu_percent(interval=0.2), 1)}
        info["load"] = [round(x, 1) for x in os.getloadavg()]
    except ImportError:
        with open("/proc/loadavg") as f:
            parts = f.read().split()
            info["load"] = [round(float(parts[i]), 1) for i in range(3)]
            info["cpu"] = {"pct": round(float(parts[0]) * 100, 1)}

    # ── GPU 百分比 (tegrastats GR3D_FREQ 优先) ──
    gpu_pct = None
    try:
        r = subprocess.run(["tegrastats", "--interval", "500"],
                           capture_output=True, text=True, timeout=1.5)
        if r.stdout:
            line = r.stdout.strip().splitlines()[-1]
            m = re.search(r"GR3D_FREQ (\d+)%", line)
            if m:
                gpu_pct = int(m.group(1))
    except Exception:
        pass
    if gpu_pct is None:
        try:
            r = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu",
                                "--format=csv,noheader,nounits"],
                               capture_output=True, text=True, timeout=2)
            if r.returncode == 0:
                gpu_pct = int(r.stdout.strip().split("\n")[0])
        except Exception:
            pass
    info["gpu"] = {"pct": gpu_pct if gpu_pct is not None else 0,
                   "model": "orin-integrated"}

    # ── 内存 (已用/总量) ──
    try:
        import psutil
        vm = psutil.virtual_memory()
        info["mem"] = {"pct": vm.percent,
                       "used_gb": _gb(vm.used), "total_gb": _gb(vm.total)}
    except ImportError:
        with open("/proc/meminfo") as f:
            lines = dict(l.split(":", 1) for l in f if ":" in l)
            total = int(lines["MemTotal"].split()[0]) * 1024
            avail = int(lines["MemAvailable"].split()[0]) * 1024
            info["mem"] = {"pct": round((1 - avail / total) * 100, 1),
                           "used_gb": _gb(total - avail), "total_gb": _gb(total)}

    # ── 磁盘 (已用/总量) ──
    try:
        import psutil
        du = psutil.disk_usage("/")
        info["disk"] = {"pct": du.percent,
                        "used_gb": _gb(du.used), "total_gb": _gb(du.total),
                        "free_gb": _gb(du.free)}
    except ImportError:
        st = os.statvfs("/")
        total = st.f_blocks * st.f_frsize
        free = st.f_bavail * st.f_frsize
        info["disk"] = {"pct": round((1 - free / total) * 100, 1),
                        "used_gb": _gb(total - free), "total_gb": _gb(total),
                        "free_gb": _gb(free)}

    # ── 网络带宽 (当前速率 + 累计总量) ──
    try:
        now = time.time()
        with open("/proc/net/dev") as f:
            rx, tx = 0, 0
            for l in f.readlines()[2:]:
                parts = l.split(":")
                if len(parts) > 1:
                    vals = parts[1].split()
                    rx += int(vals[0])
                    tx += int(vals[8])
        if _last_net is not None and now - _last_ts > 0:
            dt = now - _last_ts
            info["net"] = {
                "rx_kbps": round((rx - _last_net[0]) / 1024 / dt, 1),
                "tx_kbps": round((tx - _last_net[1]) / 1024 / dt, 1),
                "rx_total_gb": _gb(rx), "tx_total_gb": _gb(tx),
            }
        else:
            info["net"] = {"rx_kbps": 0, "tx_kbps": 0,
                           "rx_total_gb": _gb(rx), "tx_total_gb": _gb(tx)}
        _last_net, _last_ts = (rx, tx), now
    except Exception:
        info["net"] = {"rx_kbps": 0, "tx_kbps": 0, "rx_total_gb": 0, "tx_total_gb": 0}

    # ── 温度 ──
    try:
        with open("/sys/devices/virtual/thermal/thermal_zone0/temp") as f:
            info["temp"] = {"c": round(int(f.read().strip()) / 1000, 1)}
    except Exception:
        try:
            r = subprocess.run(["cat", "/sys/class/thermal/thermal_zone0/temp"],
                               capture_output=True, text=True, timeout=1)
            info["temp"] = {"c": round(int(r.stdout.strip()) / 1000, 1)}
        except Exception:
            info["temp"] = {"c": 0}

    return info


if __name__ == "__main__":
    import json
    print(json.dumps(get_sys_info(), indent=1))
