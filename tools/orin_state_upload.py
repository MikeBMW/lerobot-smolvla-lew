#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""orin_state_upload.py — Orin 侧状态上行 (机器人流 → ECS 中转 → 云端/APP 可见)

为什么需要: 2026-09-26 实测 `/api/relay/orin/status` = **online:false, infer_count:0** ——
  本机只读订阅 Orin ROS 是活的(tap 帧龄 0.1s), 但 **Orin→云 上行缺失** (云端只有 4060_hw + mac_hw 包)
  ⇒ 云端/APP 看不到机器人状态。

契约 (来自 ECS 中转真源 zmax_relay.py):
  POST https://datadrive.world/api/relay/orin/heartbeat
  body: {"online":true,"model":"...","infer_count":N,"last_infer_ms":x,"uptime":s,"role":"orin","note":"..."}
  → GET /api/relay/orin/status 回读同样字段

⚠️ 红线 (老倪): **Orin 零自研零自启** —— 本脚本是**交付现场执行**的, 本机(4060)不擅自部署到 Orin。
用法 (在 Orin 上):
  python3 orin_state_upload.py --dry-run                 # 只打印载荷, 不上传 (先看内容对不对)
  python3 orin_state_upload.py --once                    # 上传 1 次
  python3 orin_state_upload.py --interval 10             # 常驻, 每 10s 上报 (建议 systemd 守护)
  python3 orin_state_upload.py --infer-url http://127.0.0.1:8790/health   # 指定本机推理健康端点
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import urllib.request

RELAY = os.environ.get("ZMAX_RELAY", "https://datadrive.world/api/relay/orin/heartbeat")
STATUS = "https://datadrive.world/api/relay/orin/status"


def _sh(cmd, timeout=8):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception:                                                        # noqa: BLE001
        return ""


def read_infer(url):
    """Orin 本机推理服务健康 (拿不到就返回 None, 不编数字)"""
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return json.loads(r.read().decode() or "{}")
    except Exception:                                                        # noqa: BLE001
        return None


def read_hw():
    """Orin 自身硬件 (Jetson: tegrastats 可用时读, 否则 /proc 兜底)"""
    hw = {}
    tg = _sh("timeout 3 tegrastats --interval 1000 --count 1 2>/dev/null | head -1")
    if tg:
        hw["tegrastats"] = tg[:200]
    mi = _sh("free -m | sed -n 2p")
    if mi:
        p = mi.split()
        hw["mem_used_mb"], hw["mem_total_mb"] = int(p[2]), int(p[1])
    hw["gpu_util_pct"] = -1.0
    hw["temp_c"] = -1.0
    return hw


def build_payload(a, uptime_ref):
    inf = read_infer(a.infer_url) if a.infer_url else None
    st = {}
    if inf:
        st = {"model": inf.get("model") or (inf.get("models") or [None])[0],
              "infer_count": inf.get("infer_count", -1),
              "last_infer_ms": inf.get("last_infer_ms") or inf.get("last_ms")}
    return {
        "online": bool(inf and inf.get("online", True)),
        "role": "orin",
        "model": st.get("model"),
        "infer_count": st.get("infer_count", -1),
        "last_infer_ms": st.get("last_infer_ms"),
        "uptime": round(time.time() - uptime_ref, 0),
        "hw": read_hw(),
        "note": "orin_state_upload · 只读本机状态, 不下发任何动作",
        "ts": time.strftime("%F %T"),
    }


def post(payload):
    req = urllib.request.Request(RELAY, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode() or "{}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只打印载荷不上传")
    ap.add_argument("--once", action="store_true", help="只上报一次")
    ap.add_argument("--interval", type=float, default=10.0, help="常驻上报间隔(秒)")
    ap.add_argument("--infer-url", default=os.environ.get("ZMAX_ORIN_INFER", "http://127.0.0.1:8790/health"),
                    help="本机推理健康端点 (空=不上报推理字段)")
    a = ap.parse_args()
    ref = time.time()
    n = 0
    while True:
        pl = build_payload(a, ref)
        if a.dry_run:
            print(json.dumps(pl, ensure_ascii=False, indent=1))
        else:
            try:
                r = post(pl)
                n += 1
                print("[%s] ⬆ 第 %d 次上报 ok=%s resp=%s" % (time.strftime("%H:%M:%S"), n, r.get("ok", "?"),
                                                              json.dumps(r, ensure_ascii=False)[:120]), flush=True)
            except Exception as e:                                           # noqa: BLE001
                print("[%s] ❌ 上报失败: %s: %s" % (time.strftime("%H:%M:%S"), type(e).__name__, str(e)[:120]), flush=True)
        if a.once or a.dry_run:
            return 0
        time.sleep(max(1.0, a.interval))


if __name__ == "__main__":
    raise SystemExit(main())
