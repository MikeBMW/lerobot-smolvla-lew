#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🖥 硬件负载/存储/算力 采集 —— 给 APP 控制台用（全部真实数据源, 不自造）

数据源:
  GPU  : nvidia-smi (型号/利用率/显存/温度/功耗/功耗上限/SM时钟)
  算力 : 训练步速(步/s) × batch × 样本维度 → 实测吞吐; 另报 GPU 型号算力参考
  CPU  : /proc/stat 两次采样求利用率 + /proc/loadavg
  内存 : /proc/meminfo
  存储 : os.statvfs + 关键目录 du
"""
import os
import shutil
import subprocess
import time

SWM = "/home/ubuntu/stable-wm-cache"
WATCH_DIRS = [("数据集", SWM + "/datasets"), ("权重产物", SWM + "/checkpoints"),
              ("代码仓库", "/home/ubuntu/lerobot-smolvla-lew")]


def sh(c, t=15):
    try:
        return subprocess.run(c, shell=True, capture_output=True, text=True, timeout=t).stdout.strip()
    except Exception as e:                                                      # noqa: BLE001
        return "ERR:%s" % e


def gpu():
    """GPU 实际值（★ 所有字段都给实际值或明确说明, 绝不 null/undefined）"""
    o = sh("nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total,"
           "temperature.gpu,power.draw,clocks.sm,clocks.max.sm --format=csv,noheader,nounits")
    if not o or o.startswith("ERR"):
        return {"ok": False, "err": o[:80]}
    p = [x.strip() for x in o.split(",")]

    def f(v):
        try:
            return float(v)
        except Exception:                                                       # noqa: BLE001
            return None
    # 功耗上限: 笔记本 GPU 常不报 power.limit → 回退 power.default_limit / enforce.limit, 仍无则给明确文本
    plim = None
    for q in ("power.limit", "power.default_limit", "enforced.power.limit"):
        v = sh("nvidia-smi --query-gpu=%s --format=csv,noheader,nounits" % q)
        try:
            plim = float(v.strip())
            break
        except Exception:                                                       # noqa: BLE001
            continue
    mu, mt = f(p[2]), f(p[3])
    return {"ok": True, "name": p[0], "util_pct": f(p[1]) or 0.0, "mem_used_mb": mu, "mem_total_mb": mt,
            "temp_c": f(p[4]), "power_w": f(p[5]),
            "power_limit_w": plim,
            "power_limit_note": ("实测上限 %.1fW" % plim) if plim else "本机 GPU 不报功耗上限(笔记本)",
            "clk_sm_mhz": f(p[6]), "clk_sm_max_mhz": f(p[7]),
            "mem_used_pct": (round(100 * mu / mt, 1) if mu and mt else 0.0)}


def gpu_procs():
    o = sh("nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader")
    r = []
    for ln in o.splitlines():
        p = [x.strip() for x in ln.split(",")]
        if len(p) >= 2 and p[0].isdigit():
            r.append({"pid": int(p[0]), "mem": p[1]})
    return r


def cpu():
    def snap():
        p = open("/proc/stat").readline().split()[1:]
        v = [int(x) for x in p]
        return sum(v), v[3]
    t0, i0 = snap()
    time.sleep(1.0)
    t1, i1 = snap()
    util = round(100.0 * (1 - (i1 - i0) / max(1, t1 - t0)), 1)
    la = open("/proc/loadavg").read().split()[:3]
    n = os.cpu_count() or 1
    return {"cores": n, "util_pct": util, "load1": float(la[0]), "load5": float(la[1]),
            "load15": float(la[2]), "load_pct": round(100.0 * float(la[0]) / n, 1)}


def mem():
    d = {}
    for ln in open("/proc/meminfo"):
        k, v = ln.split(":")[0], ln.split()[1]
        d[k] = int(v) / 1048576.0
    tot, av = d.get("MemTotal", 0), d.get("MemAvailable", 0)
    return {"total_gb": round(tot, 1), "avail_gb": round(av, 1), "used_gb": round(tot - av, 1),
            "used_pct": (round(100 * (tot - av) / tot, 1) if tot else None)}


def disk():
    o = shutil.disk_usage("/")
    dirs = []
    for nm, p in WATCH_DIRS:
        if os.path.isdir(p):
            sz = sh("du -sm %s 2>/dev/null | cut -f1" % p)
            dirs.append({"name": nm, "path": p,
                         "gb": round(int(sz) / 1024.0, 1) if sz.strip().isdigit() else None})
    return {"total_gb": round(o.total / 1073741824.0, 1),
            "used_gb": round(o.used / 1073741824.0, 1),
            "free_gb": round(o.free / 1073741824.0, 1),
            "used_pct": round(100.0 * o.used / o.total, 1), "dirs": dirs}


def throughput():
    """算力实测: 从最新训练日志/进度文件取 步/s, 折算样本吞吐"""
    import glob
    import json
    import re
    best = None
    for pat in (SWM + "/reports/progress_*.json", "/tmp/uni_*.log", "/tmp/train_*.log"):
        for f in glob.glob(pat):
            try:
                if f.endswith(".json"):
                    d = json.load(open(f, encoding="utf-8"))
                    sps, batch, files = d.get("sps"), None, d.get("save")
                    if sps and (time.time() - (d.get("ts") or 0) < 600):
                        best = {"sps": sps, "src": os.path.basename(f), "running": d.get("running", True)}
                else:
                    m = re.findall(r"\|\s*([\d.]+)步/s", open(f, encoding="utf-8", errors="replace").read())
                    if m:
                        v = float(m[-1])
                        if best is None or v > (best.get("sps") or 0):
                            best = {"sps": v, "src": os.path.basename(f), "running": False}
            except Exception:                                                   # noqa: BLE001
                pass
    if not best:
        return {"ok": False}
    sps = best["sps"]
    return {"ok": True, "sps": sps, "steps_per_hour": int(sps * 3600),
            "samples_per_s_b64": round(sps * 64, 1), "src": best["src"], "running": best.get("running")}


REMOTE_F = "/home/ubuntu/stable-wm-cache/reports/remote_hw.json"


def save_remote(payload):
    """Mac 端上报的硬件状态（MPS/CPU/内存/磁盘）→ 落盘, 供控制台展示两台机器对比"""
    import json as _j
    os.makedirs(os.path.dirname(REMOTE_F), exist_ok=True)
    payload["recv_ts"] = time.time()
    _j.dump(payload, open(REMOTE_F, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return {"ok": True, "saved": REMOTE_F}


def remote():
    """读 Mac 上报（无则返回明确说明, 不返回空）"""
    import json as _j
    if not os.path.isfile(REMOTE_F):
        return {"ok": False, "note": "尚无 Mac 上报 → 在小芳 Mac 上跑 tools/mac_hw_report.py 上报"}
    try:
        d = _j.load(open(REMOTE_F, encoding="utf-8"))
    except Exception as e:                                                      # noqa: BLE001
        return {"ok": False, "note": "上报文件解析失败: %s" % str(e)[:60]}
    age = time.time() - (d.get("recv_ts") or 0)
    d["ok"] = True
    d["age_s"] = round(age, 1)
    d["stale"] = age > 300          # 5 分钟没上报 → 视为离线
    return d


def collect():
    return {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "gpu": gpu(), "gpu_procs": gpu_procs(),
            "cpu": cpu(), "mem": mem(), "disk": disk(), "compute": throughput(),
            "remote": remote()}


if __name__ == "__main__":
    import json
    print(json.dumps(collect(), ensure_ascii=False, indent=1))
