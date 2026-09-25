#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hw_upload.py — 硬件数据上云 (Mac 本机 + DDS 各机 → ECS relay → 手机 APP)
=========================================================================
链路:  hw_monitor.probe()  本机真实硬件
       hw_dds.HwSubscriber  DDS 收到的其他机器 (4060/Orin/4090)
                ↓  合并
       POST http://datadrive.world/api/relay/upload   (type=hw_metrics)
                ↓
       手机 APP / web 控制平台 读 /api/relay/latest 显示

用法:
    python3 hw_upload.py --once                 # 上传一次
    python3 hw_upload.py --loop --interval 10   # 常驻, 每 10s 上传
环境变量:
    ZMAX_RELAY_URL   默认 http://datadrive.world/api/relay/upload
    ZMAX_HW_ROLE     本机角色, 默认 mac
"""
import argparse
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

RELAY = os.environ.get("ZMAX_RELAY_URL", "http://datadrive.world/api/relay/upload")
ROLE = os.environ.get("ZMAX_HW_ROLE", "mac")


def collect(measure_tflops: bool = False) -> dict:
    """采集: 本机 + DDS 收到的其他机器"""
    out = {"machines": {}, "collected_at": time.time(), "collector": ROLE}

    # 1) 本机真实硬件
    try:
        from hw_monitor import probe
        d = probe(measure=measure_tflops)
        out["machines"][ROLE] = {
            "host": d["host"],
            "cpu": d["cpu"], "mem": d["mem"], "disk": d["disk"],
            "gpu": d["gpu"], "compute": d["compute"],
            "training": d["training"], "warnings": d.get("warn", []),
            "platform": d.get("platform"), "ts": d.get("ts"),
            "source": "local_probe", "age_s": 0.0,
        }
    except Exception as e:
        out["machines"][ROLE] = {"error": f"{type(e).__name__}: {str(e)[:120]}",
                                 "source": "local_probe"}

    # 2) DDS 收到的其他机器 (需要 cyclonedds; 没装则跳过)
    try:
        from hw_dds import HwSubscriber
        sub = HwSubscriber(stale_s=30.0)
        sub.poll()
        for r, m in sub.online().items():
            if r == ROLE:
                continue
            out["machines"][r] = {
                "host": m.get("host"),
                "cpu": m["cpu"], "mem": m["mem"], "disk": m["disk"],
                "gpu": m["gpu"], "compute": m["compute"],
                "training": m["training"],
                "source": "dds", "age_s": m.get("age_s"),
            }
    except Exception as e:
        out["dds_note"] = f"{type(e).__name__}: {str(e)[:90]}"

    return out


def upload(payload: dict, relay: str = RELAY, timeout: float = 15.0) -> dict:
    pkg = {
        "meta": {
            "source": f"{ROLE}_hw",
            "type": "hw_metrics",
            "project": "zmax_hw",
            "role": ROLE,
            "machines": list(payload["machines"].keys()),
            "time": payload["collected_at"],
        },
        "data": payload,
    }
    body = json.dumps(pkg).encode()
    req = urllib.request.Request(relay, data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode() or "{}")


def brief(payload: dict) -> str:
    rows = []
    for r, m in payload["machines"].items():
        if "error" in m:
            rows.append(f"{r}: ERR {m['error'][:40]}")
            continue
        c, me, dk, g, cp = m["cpu"], m["mem"], m["disk"], m["gpu"], m["compute"]
        rows.append(
            f"{r}: CPU {c.get('percent')}% 内存 {me.get('percent')}% "
            f"磁盘 {dk.get('percent')}% GPU {g.get('util_pct')}% "
            f"显存 {g.get('mem_used_gb')}GB 算力 {cp.get('tflops_measured') or cp.get('tflops_fp32')}"
        )
    return " | ".join(rows) if rows else "(无机器)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="上传一次")
    ap.add_argument("--loop", action="store_true", help="常驻循环")
    ap.add_argument("--interval", type=float, default=10.0, help="循环间隔秒 (默认10)")
    ap.add_argument("--measure-tflops", action="store_true", help="包含算力实测 (较慢)")
    ap.add_argument("--dry", action="store_true", help="只打印不上传")
    a = ap.parse_args()

    interval = 0 if a.once or not a.loop else max(2.0, a.interval)
    while True:
        try:
            payload = collect(measure_tflops=a.measure_tflops)
            if a.dry:
                print(f"[dry] {brief(payload)}")
            else:
                r = upload(payload)
                print(f"[{time.strftime('%H:%M:%S')}] 上传 ok={r.get('ok')} "
                      f"name={r.get('name')} | {brief(payload)}", flush=True)
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] ❌ 上传失败: {type(e).__name__}: {str(e)[:120]}",
                  flush=True)
        if not interval:
            break
        time.sleep(interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())
