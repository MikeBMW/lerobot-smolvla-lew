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
sys.path.insert(0, os.path.join(REPO, "dds"))   # ★ 单一工程根下的 DDS 类型目录
for _c in (os.path.join(REPO, "dds"), "/home/ubuntu/zmax/dds"):
    if os.path.isdir(_c):
        sys.path.insert(0, _c)
RELAY = "https://datadrive.world/api/relay/upload"
CFG = next((p for p in (os.path.join(REPO, "dds", "cyclonedds_unicast.xml"),
                         os.path.join(REPO, "dds", "cyclonedds_unicast.xml")) if os.path.isfile(p)), "")


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
        if got and len(out) >= 2 and time.time() - t0 > 2.0:
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
            # ★ HardwareState 要**扁平字段**（不是嵌套 gpu/cpu/mem/disk）—— 之前发的是嵌套 → 收到全默认值
            g_ = lh.get("gpu") or {}
            c_ = lh.get("cpu") or {}
            m_ = lh.get("mem") or {}
            d_ = lh.get("disk") or {}
            _flat = {k: v for k, v in {
                "node": lh.get("host") or "4060", "role": "工作端(4060)", "backend": "cuda",
                "device_name": g_.get("name") or "", "ts": time.time(),
                "util_pct": g_.get("util_pct"), "mem_used_mb": g_.get("vram_used_mb"),
                "mem_total_mb": g_.get("vram_total_mb"), "temp_c": g_.get("temp_c"),
                "power_w": g_.get("power_w"), "clk_mhz": g_.get("clk_mhz"),
                "cpu_cores": c_.get("cores"), "cpu_util_pct": c_.get("percent"),
                "load1": c_.get("load1"), "mem_total_gb": m_.get("total_gb"),
                "mem_avail_gb": m_.get("avail_gb"), "disk_total_gb": d_.get("total_gb"),
                "disk_free_gb": d_.get("free_gb"),
            }.items() if k in HardwareState.__dataclass_fields__ and v is not None}
            try:
                pub.send("hw_state", HardwareState(**_flat))
            except Exception as _e:                                             # noqa: BLE001
                print("  ⚠️ DDS 发布失败: %s" % str(_e)[:80])
            # ② 从 DDS 汇聚（本机 + Mac）
            nodes = collect_via_dds(agg, timeout=9.0)   # ★ 留足 DDS 发现时间
            machines = {}
            for name, d in nodes.items():
                be = str(d.get("backend") or "").lower()
                if be == "cuda" or "4060" in name:
                    machines["4060"] = {"host": d.get("device_name") or d.get("host") or "4060",
                                        "gpu": {"backend": "cuda", "name": d.get("device_name"),
                                                "util_pct": d.get("util_pct"),
                                                "vram_used_mb": d.get("mem_used_mb"),
                                                "vram_total_mb": d.get("mem_total_mb"),
                                                "temp_c": d.get("temp_c"), "power_w": d.get("power_w"),
                                                "clk_mhz": d.get("clk_mhz"),
                                                "vram_used_pct": (round(100.0 * d["mem_used_mb"] / d["mem_total_mb"], 1)
                                                                  if d.get("mem_used_mb") and d.get("mem_total_mb") else None)},
                                        "cpu": {"cores": d.get("cpu_cores"), "percent": d.get("cpu_util_pct")},
                                        "mem": {"avail_gb": d.get("mem_avail_gb"), "total_gb": d.get("mem_total_gb")},
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
            # ★ 回归修复: DDS 取回的本机数据若缺关键值(显存/利用率), 用本机直采补齐
            _m4 = machines.get("4060")
            if _m4 is not None:
                _g4 = _m4.get("gpu") or {}
                if not _g4.get("vram_used_mb") or _g4.get("vram_used_mb") in (0, -1.0, -1):
                    _g4.update({"name": _g4.get("name") or (lh.get("gpu") or {}).get("name"),
                                "util_pct": (_g4.get("util_pct") if _g4.get("util_pct") not in (None, -1.0, -1) else (lh.get("gpu") or {}).get("util_pct")),
                                "vram_used_mb": (lh.get("gpu") or {}).get("vram_used_mb"),
                                "vram_total_mb": (lh.get("gpu") or {}).get("vram_total_mb"),
                                "temp_c": (lh.get("gpu") or {}).get("temp_c"),
                                "power_w": (lh.get("gpu") or {}).get("power_w"),
                                "clk_mhz": (lh.get("gpu") or {}).get("clk_mhz"),
                                "vram_used_pct": (lh.get("gpu") or {}).get("vram_used_pct"),
                                "backend": "cuda"})
                _cs = lh.get("cpu") or {}
                _ms = lh.get("mem") or {}
                _ds = lh.get("disk") or {}
                _m4["cpu"] = {"cores": (_m4.get("cpu") or {}).get("cores") or _cs.get("cores"),
                              "percent": (_m4.get("cpu") or {}).get("percent") if (_m4.get("cpu") or {}).get("percent") not in (None, -1.0, -1) else _cs.get("percent")}
                _m4["mem"] = {"used_gb": _ms.get("used_gb"), "total_gb": _ms.get("total_gb")}
                _m4["disk"] = {"free_gb": _ds.get("free_gb"), "total_gb": _ds.get("total_gb")}
                _m4["gpu"] = _g4
                _m4["via"] = "DDS+local"   # 本机项: 实测为准(已同时经 DDS 对外发布)
                _m4["train_steps_per_s"] = train_throughput()
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
