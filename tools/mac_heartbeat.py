#!/usr/bin/env python3
"""MAC 心跳 — 每5秒上报Orin状态(含recording)"""
import requests, time, os, glob

ORIN = "http://192.168.23.66:8765"
HB = "http://datadrive.world/api/comfy/api/mac/heartbeat"

while True:
    try:
        rs = requests.get(f"{ORIN}/record/status", timeout=3).json()
        recording = rs.get("recording", False)
        # 统计MAC本地已转发的数据
        forwarded = 0
        for f in glob.glob("/tmp/cycle_*.tar.gz") + glob.glob("/Users/mikeni/Desktop/zmax_*.tar.gz"):
            try: forwarded += os.path.getsize(f)
            except: pass
        forwarded_mb = round(forwarded / 1048576, 1)
        payload = {"mac_online": True, "orin": {"online": True, "recording": recording, "forwarded_mb": forwarded_mb}, "ts": time.time()}
        requests.post(HB, json=payload, timeout=10)
    except:
        pass
    time.sleep(5)
