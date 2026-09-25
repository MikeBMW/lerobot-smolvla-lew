#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📤 4060 硬件（含显存占用）→ ECS relay 持续上报（常驻服务用）

老倪 2026-09-25: "手机APP zmax还是没有4060硬件显存数据，必须马上修改，上传数据"

格式与 Mac 端完全对齐（relay 上的既有包）:
  {"meta": {"source":"4060_hw","type":"hw_metrics","project":"zmax_hw","role":"work",
            "machines":[...],"time":<epoch>},
   "data": {"machines": {"4060": {host, cpu:{}, mem:{}, disk:{}, gpu:{...显存...}} , "mac": {...转发...}}}}
★ 只上报真实采集值（采不到 = None，不编造）；同时转发 relay 上最近的 Mac 真实包，
  使单个包内同时含两台机器（避免"最新包覆盖"导致页面看不到 4060）。
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

RELAY = "https://datadrive.world/api/relay/upload"
LATEST = "https://datadrive.world/api/relay/latest"
INTERVAL = 3


def sh(c, t=10):
    try:
        return subprocess.run(c, shell=True, capture_output=True, text=True, timeout=t).stdout.strip()
    except Exception:                                                           # noqa: BLE001
        return ""


def _f(v):
    try:
        return float(v)
    except Exception:                                                           # noqa: BLE001
        return None


def collect_4060():
    """4060 硬件（含**显存占用**）—— 真实采集"""
    d = {}
    o = sh("nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total,"
           "temperature.gpu,power.draw,clocks.sm --format=csv,noheader,nounits")
    gpu = {"backend": "cuda", "name": None, "util_pct": None, "vram_used_mb": None,
           "vram_total_mb": None, "vram_used_pct": None, "temp_c": None, "power_w": None,
           "clk_mhz": None}
    if o and "," in o:
        p = [x.strip() for x in o.split(",")]
        gpu.update(name=p[0], util_pct=_f(p[1]), vram_used_mb=_f(p[2]), vram_total_mb=_f(p[3]),
                   temp_c=_f(p[4]), power_w=_f(p[5]), clk_mhz=_f(p[6]))
        if gpu["vram_used_mb"] is not None and gpu["vram_total_mb"]:
            gpu["vram_used_pct"] = round(100.0 * gpu["vram_used_mb"] / gpu["vram_total_mb"], 1)
    d["gpu"] = gpu

    def snap():
        v = [int(x) for x in open("/proc/stat").readline().split()[1:]]
        return sum(v), v[3]
    try:
        t0, i0 = snap()
        time.sleep(0.12)
        t1, i1 = snap()
        cpu_pct = round(100.0 * (1 - (i1 - i0) / max(1, t1 - t0)), 1)
    except Exception:                                                           # noqa: BLE001
        cpu_pct = None
    la = os.getloadavg() if hasattr(os, "getloadavg") else (0, 0, 0)
    d["cpu"] = {"cores": os.cpu_count(), "load1": round(la[0], 2), "load5": round(la[1], 2),
                "load15": round(la[2], 2), "percent": cpu_pct}
    try:
        mi = {}
        for ln in open("/proc/meminfo"):
            mi[ln.split(":")[0]] = int(ln.split()[1]) / 1048576.0
        tot, av = mi.get("MemTotal"), mi.get("MemAvailable")
        d["mem"] = {"total_gb": round(tot, 1), "used_gb": round(tot - av, 1), "avail_gb": round(av, 1),
                    "percent": round(100.0 * (tot - av) / max(tot, 1), 1)}
    except Exception:                                                           # noqa: BLE001
        d["mem"] = {}
    try:
        st = os.statvfs("/")
        tot = st.f_blocks * st.f_frsize / 1073741824
        free = st.f_bavail * st.f_frsize / 1073741824
        d["disk"] = {"root": "/", "total_gb": round(tot, 1), "free_gb": round(free, 1),
                     "used_gb": round(tot - free, 1), "percent": round(100.0 * (tot - free) / tot, 1)}
    except Exception:                                                           # noqa: BLE001
        d["disk"] = {}
    d["host"] = (sh("hostname") or "4060") + " / RTX 4060 Laptop"
    return d


def fetch_mac_latest():
    """转发 relay 上最近的 Mac 真实包（读不到 = None）"""
    try:
        with urllib.request.urlopen(LATEST, timeout=12) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        for k, v in ((d.get("data") or {}).get("machines") or {}).items():
            g = v.get("gpu") or {}
            if "mac" in str(k).lower() or str(g.get("backend", "")).lower() == "mps":
                return k, v
    except Exception:                                                           # noqa: BLE001
        pass
    return None, None


def upload():
    machines = {"4060": collect_4060()}
    mk, mv = fetch_mac_latest()
    if mk and mv:
        machines[mk] = mv
    payload = {"meta": {"source": "4060_hw", "type": "hw_metrics", "project": "zmax_hw",
                        "role": "work", "machines": list(machines.keys()), "time": time.time()},
               "data": {"machines": machines}}
    body = json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request(RELAY, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=25) as r:
        resp = r.read().decode("utf-8", "replace")[:150]
    g = machines["4060"]["gpu"]
    return resp, list(machines.keys()), g


def main():
    once = "--once" in sys.argv
    while True:
        try:
            resp, mks, g = upload()
            print("[%s] ✅ 已上传(含 %s): 4060 显存 %s/%s MB (%s%%) | GPU %s%% | %s°C | %sW | %s"
                  % (time.strftime("%H:%M:%S"), ",".join(mks), g["vram_used_mb"], g["vram_total_mb"],
                     g["vram_used_pct"], g["util_pct"], g["temp_c"], g["power_w"], resp[:60]),
                  flush=True)
        except Exception as e:                                                  # noqa: BLE001
            print("[%s] ❌ 上传失败: %s: %s" % (time.strftime("%H:%M:%S"), type(e).__name__,
                                             str(e)[:110]), flush=True)
        if once:
            return 0
        time.sleep(INTERVAL)


if __name__ == "__main__":
    raise SystemExit(main())
