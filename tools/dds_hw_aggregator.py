#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📡 DDS 硬件汇聚器（4060 侧）—— 让硬件数据**真正经 DDS 传输**

老倪 2026-09-25: "这些数据是消息中间件DDS上报的么? 要用DDS通讯"

链路（改造后）:
  4060 本机硬件 ──(DDS zmax/hw_state)──┐
  Mac  硬件     ──(DDS zmax/hw_state)──┤→ 【本进程: DDS 订阅汇聚】
                                        └→ relay(HTTP) → 手机/网页（DDS 无法直达浏览器）

诚实说明: 手机 WebView 讲不了 DDS 协议（需原生库+UDP发现），
         所以 **机器之间用 DDS，最后一跳(到手机/网页)用 HTTP**。

用法: python3 tools/dds_hw_aggregator.py [--watch 5] [--once]
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "/home/ubuntu/zmax_dds")   # ★ 稳定路径（不随 git 分支变化）
for _c in (os.path.join(REPO, "dds"), "/home/ubuntu/zmax_dds"):
    if os.path.isdir(_c):
        sys.path.insert(0, _c)
RELAY = "https://datadrive.world/api/relay/upload"
CFG = next((p for p in (os.path.join(REPO, "dds", "cyclonedds_unicast.xml"),
                         "/home/ubuntu/zmax_dds/cyclonedds_unicast.xml") if os.path.isfile(p)), "")


def sh(c, t=8):
    try:
        return subprocess.run(c, shell=True, capture_output=True, text=True, timeout=t).stdout.strip()
    except Exception:                                                           # noqa: BLE001
        return ""


def _f(v):
    try:
        return float(v)
    except Exception:                                                           # noqa: BLE001
        return None


def local_hw():
    """4060 本机硬件（含显存）—— 由本进程采集后**经 DDS 发布**，再从 DDS 取回（真 DDS 闭环）"""
    o = sh("nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total,"
           "temperature.gpu,power.draw,clocks.sm --format=csv,noheader,nounits")
    gpu = {"backend": "cuda", "name": None, "util_pct": None, "vram_used_mb": None,
           "vram_total_mb": None, "vram_used_pct": None, "temp_c": None, "power_w": None, "clk_mhz": None}
    if o and "," in o:
        p = [x.strip() for x in o.split(",")]
        gpu.update(name=p[0], util_pct=_f(p[1]), vram_used_mb=_f(p[2]), vram_total_mb=_f(p[3]),
                   temp_c=_f(p[4]), power_w=_f(p[5]), clk_mhz=_f(p[6]))
        if gpu["vram_used_mb"] is not None and gpu["vram_total_mb"]:
            gpu["vram_used_pct"] = round(100.0 * gpu["vram_used_mb"] / gpu["vram_total_mb"], 1)

    def snap():
        v = [int(x) for x in open("/proc/stat").readline().split()[1:]]
        return sum(v), v[3]
    try:
        t0, i0 = snap()
        time.sleep(0.1)
        t1, i1 = snap()
        cpu_pct = round(100.0 * (1 - (i1 - i0) / max(1, t1 - t0)), 1)
    except Exception:                                                           # noqa: BLE001
        cpu_pct = None
    la = os.getloadavg() if hasattr(os, "getloadavg") else (0, 0, 0)
    mem = {}
    try:
        mi = {}
        for ln in open("/proc/meminfo"):
            mi[ln.split(":")[0]] = int(ln.split()[1]) / 1048576.0
        tot, av = mi.get("MemTotal"), mi.get("MemAvailable")
        mem = {"total_gb": round(tot, 1), "used_gb": round(tot - av, 1), "avail_gb": round(av, 1),
               "percent": round(100.0 * (tot - av) / max(tot, 1), 1)}
    except Exception:                                                           # noqa: BLE001
        pass
    disk = {}
    try:
        st = os.statvfs("/")
        tot = st.f_blocks * st.f_frsize / 1073741824
        free = st.f_bavail * st.f_frsize / 1073741824
        disk = {"root": "/", "total_gb": round(tot, 1), "free_gb": round(free, 1),
                "used_gb": round(tot - free, 1), "percent": round(100.0 * (tot - free) / tot, 1)}
    except Exception:                                                           # noqa: BLE001
        pass
    return {"host": (sh("hostname") or "4060") + " / RTX 4060 Laptop", "gpu": gpu,
            "cpu": {"cores": os.cpu_count(), "load1": round(la[0], 2), "percent": cpu_pct},
            "mem": mem, "disk": disk, "ts": time.time()}


def train_throughput():
    import glob as _g
    for f in sorted(_g.glob("/tmp/train_*.log") + _g.glob("/tmp/web_job_*.log"),
                    key=lambda x: -os.path.getmtime(x)):
        try:
            if time.time() - os.path.getmtime(f) > 900:
                continue
            for ln in reversed(open(f, "r", errors="replace").read()[-3000:].splitlines()):
                if "步/s" in ln:
                    return round(float(ln.split("步/s")[0].strip().split("|")[-1].strip()), 2)
        except Exception:                                                       # noqa: BLE001
            continue
    return None


def collect_via_dds(agg, timeout=6.0):
    """★ 从 DDS 汇聚所有节点的硬件（4060 本机 + Mac）—— 真 DDS 传输"""
    out = {}
    t0 = time.time()
    while time.time() - t0 < timeout:
        got = False
        for m in agg.take("hw_state", 0.4):
            d = {}
            for k in ("node", "role", "backend", "device_name", "host", "gpu", "cpu", "mem", "disk",
                      "vram_used_mb", "vram_total_mb", "util_pct", "mem_used_gb", "mem_total_gb",
                      "disk_free_gb", "cpu_util_pct", "cpu_cores", "ts"):
                if hasattr(m, k):
                    d[k] = getattr(m, k)
            key = str(getattr(m, "node", "") or "?").strip()
            if key and ("TEST" not in key.upper() and "自测" not in key):
                out[key] = d
                got = True
        if got and len(out) >= 1 and time.time() - t0 > 1.5:
            break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", type=int, default=5, help="每 N 秒一轮（0=只跑一次）")
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    try:
        from zmax_node import Node
        from zmax_types import HardwareState
    except Exception as e:                                                      # noqa: BLE001
        print("  ❌ 需要 cyclonedds（在 dds-venv 里跑）: %s" % e)
        return 1
    cfg = CFG if os.path.isfile(CFG) else None
    agg = Node("dds-hw-agg", config_xml=cfg)
    pub = Node("dds-hw-pub", config_xml=cfg)
    pub.pub("hw_state")
    sub = agg.sub("hw_state")
    print("  📡 DDS 汇聚器启动（域 0 · %s）" % ("单播配置" if cfg else "默认"))
    while True:
        try:
            # ① 本机 4060 硬件 → **经 DDS 发布**
            lh = local_hw()
            msg = HardwareState(**{k: v for k, v in lh.items()
                                   if k in HardwareState.__dataclass_fields__ and k != "gpu"})
            try:
                pub.send("hw_state", msg)
            except Exception:                                                   # noqa: BLE001
                pass
            # ② 从 DDS 汇聚（本机 + Mac）
            nodes = collect_via_dds(agg, timeout=5.0)
            machines = {}
            for name, d in nodes.items():
                be = str(d.get("backend") or "").lower()
                if be == "cuda" or "4060" in name:
                    machines["4060"] = {"host": d.get("host") or d.get("device_name") or "4060",
                                        "gpu": {"backend": "cuda", "name": d.get("device_name"),
                                                "util_pct": d.get("util_pct"),
                                                "vram_used_mb": d.get("vram_used_mb"),
                                                "vram_total_mb": d.get("vram_total_mb"),
                                                "vram_used_pct": (round(100.0 * d["vram_used_mb"] / d["vram_total_mb"], 1)
                                                                  if d.get("vram_used_mb") and d.get("vram_total_mb") else None)},
                                        "cpu": {"cores": d.get("cpu_cores"), "percent": d.get("cpu_util_pct")},
                                        "mem": {"used_gb": d.get("mem_used_gb"), "total_gb": d.get("mem_total_gb")},
                                        "disk": {"free_gb": d.get("disk_free_gb")},
                                        "train_steps_per_s": train_throughput(), "via": "DDS"}
                elif be == "mps" or "mac" in name.lower():
                    machines["mac"] = dict(d, via="DDS")
            # Mac 兜底: DDS 里没有 → 从 relay 读（标注为 relay-http，不冒充 DDS）
            if not any("mac" in k.lower() for k in machines):
                try:
                    import urllib.request as _ur
                    with _ur.urlopen("https://datadrive.world/api/relay/latest", timeout=12) as _r:
                        _j = json.loads(_r.read().decode("utf-8", "replace"))
                    for _k, _v in ((_j.get("data") or {}).get("machines") or {}).items():
                        _g = _v.get("gpu") or {}
                        if "mac" in str(_k).lower() or str(_g.get("backend", "")).lower() == "mps":
                            machines[_k] = dict(_v, via="relay-http")
                            break
                except Exception:                                               # noqa: BLE001
                    pass
            if not machines.get("4060"):        # DDS 没取回本机 → 用直采兜底（并标注）
                machines["4060"] = dict(lh, train_steps_per_s=train_throughput(), via="local")
            payload = {"meta": {"source": "dds_aggregator", "type": "hw_metrics", "project": "zmax_hw",
                                "role": "aggregate", "machines": list(machines.keys()),
                                "transport": "DDS→relay", "time": time.time()},
                       "data": {"machines": machines}}
            body = json.dumps(payload, ensure_ascii=False).encode()
            req = urllib.request.Request(RELAY, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=25) as r:
                resp = r.read().decode("utf-8", "replace")[:80]
            g = (machines.get("4060") or {}).get("gpu") or {}
            print("[%s] 📡 DDS 汇聚→relay: 节点=%s | 4060 显存 %s/%s | %s"
                  % (time.strftime("%H:%M:%S"), ",".join(machines.keys()),
                     g.get("vram_used_mb"), g.get("vram_total_mb"), resp[:40]), flush=True)
        except Exception as e:                                                  # noqa: BLE001
            print("[%s] ❌ %s: %s" % (time.strftime("%H:%M:%S"), type(e).__name__, str(e)[:110]), flush=True)
        if a.once or a.watch <= 0:
            return 0
        time.sleep(a.watch)


if __name__ == "__main__":
    raise SystemExit(main())
