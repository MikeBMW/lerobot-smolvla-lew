#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hw_monitor.py — 训练硬件体检: 负载 / 存储 / 算力 (跨平台)
================================================================
给 APP 训练控制台显示**真实**硬件状态。

支持三端:
  · macOS (M1/M2/M3):  psutil + ioreg(IOAccelerator GPU 利用率) + torch.mps
  · Linux + NVIDIA   : psutil + pynvml/nvidia-smi (Orin / 4060)
  · 通用兜底         : 只有 psutil 的部分

返回结构 (单次采样):
  {
    "ts": float, "host": str, "platform": str,
    "cpu":  {"cores": int, "load1": f, "load5": f, "load15": f, "percent": f},
    "mem":  {"total_gb": f, "used_gb": f, "avail_gb": f, "percent": f,
             "swap_total_gb": f, "swap_used_gb": f, "swap_percent": f},
    "disk": {"root": str, "total_gb": f, "used_gb": f, "free_gb": f, "percent": f},
    "gpu":  {"backend": "cuda"|"mps"|"none", "name": str, "count": int,
             "util_pct": f|None, "mem_used_gb": f|None, "mem_total_gb": f|None},
    "compute": {"device": str, "tflops_fp32": f|None, "note": str},
    "training": {"active": bool, "procs": [{"pid":int,"name":str,"cpu":f,"mem_mb":f}]},
    "warn": [str]     # 异常/局限说明 (诚实标注, 不编数)
  }
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import time

try:
    import psutil
    # 预热: psutil.cpu_percent() 首次调用恒返回 0.0 (无基准), 这里先起一次基准
    psutil.cpu_percent(interval=None)
except Exception:  # pragma: no cover
    psutil = None

GB = 1024 ** 3

# ── 已知算力表 (FP32, TFLOPS) — 仅作"标称算力"参考, 非实测 ──
_TFLOPS = {
    "Apple M1": 2.6, "Apple M1 Pro": 5.3, "Apple M1 Max": 10.4, "Apple M1 Ultra": 21.0,
    "Apple M2": 3.6, "Apple M2 Pro": 6.8, "Apple M2 Max": 13.6, "Apple M2 Ultra": 27.2,
    "Apple M3": 4.1, "Apple M3 Pro": 7.4, "Apple M3 Max": 14.2, "Apple M3 Ultra": 28.4,
}
# NVIDIA 标称 FP32 TFLOPS (部分常见卡)
_TFLOPS_NV = {"4060": 15.1, "4090": 82.6, "V100": 15.7, "A100": 19.5, "3060": 12.7}
# Jetson Orin NX 16GB (Ampere, 1024 CUDA cores @ ~918MHz) ≈ 1.9 TFLOPS FP32
_TFLOPS_NV["Orin"] = 1.9


def _run(cmd: list[str], timeout: float = 3.0) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout or ""
    except Exception:
        return ""


# ────────────────────────── CPU ──────────────────────────
def probe_cpu() -> dict:
    d: dict = {"cores": os.cpu_count() or 0, "load1": None, "load5": None, "load15": None, "percent": None}
    try:
        la = os.getloadavg()
        d.update(load1=round(la[0], 2), load5=round(la[1], 2), load15=round(la[2], 2))
    except Exception:
        pass
    if psutil:
        try:
            d["percent"] = round(psutil.cpu_percent(interval=None), 1)
        except Exception:
            pass
    return d


# ────────────────────────── 内存 ──────────────────────────
def probe_mem() -> dict:
    d: dict = dict(total_gb=None, used_gb=None, avail_gb=None, percent=None,
                   swap_total_gb=None, swap_used_gb=None, swap_percent=None)
    if not psutil:
        return d
    try:
        vm = psutil.virtual_memory()
        d.update(total_gb=round(vm.total / GB, 1), used_gb=round(vm.used / GB, 1),
                 avail_gb=round(vm.available / GB, 1), percent=round(vm.percent, 1))
        sw = psutil.swap_memory()
        d.update(swap_total_gb=round(sw.total / GB, 2), swap_used_gb=round(sw.used / GB, 2),
                 swap_percent=round(sw.percent, 1))
    except Exception:
        pass
    return d


# ────────────────────────── 磁盘 ──────────────────────────
def probe_disk(path: str | None = None) -> dict:
    root = path or (os.environ.get("ZMAX_DISK_ROOT") or ("/" if os.name != "nt" else "C:\\"))
    d: dict = dict(root=root, total_gb=None, used_gb=None, free_gb=None, percent=None)
    try:
        t, u, f = shutil.disk_usage(root)
        d.update(total_gb=round(t / GB, 1), used_gb=round(u / GB, 1),
                 free_gb=round(f / GB, 1), percent=round(u / t * 100, 1) if t else None)
    except Exception:
        pass
    return d


# ────────────────────────── GPU ──────────────────────────
def _gpu_apple(warn: list) -> dict | None:
    """macOS: 从 ioreg IOAccelerator 读 GPU 利用率/显存占用"""
    out = _run(["ioreg", "-r", "-d", "1", "-w", "0", "-c", "IOAccelerator"])
    if not out:
        return None
    import re
    util = mem_used = None
    m = re.search(r'"Device Utilization %"\s*=\s*(\d+)', out)
    if m:
        util = float(m.group(1))
    m = re.search(r'"In use system memory"\s*=\s*(\d+)', out)
    if m:
        mem_used = int(m.group(1)) / GB
    name = "Apple GPU"
    m = re.search(r'"model"\s*=\s*"([^"]+)"', out)
    if m:
        name = m.group(1)
    if util is None:
        warn.append("macOS 未取到 GPU 利用率 (ioreg 无 Device Utilization 字段)")
    return {"backend": "mps", "name": name, "count": 1,
            "util_pct": util, "mem_used_gb": round(mem_used, 2) if mem_used is not None else None,
            "mem_total_gb": None, "note": "统一内存架构 (显存=系统内存)"}


def _gpu_nvidia(warn: list) -> dict | None:
    """Linux/NVIDIA: pynvml 优先, 兜底 nvidia-smi"""
    try:
        import pynvml  # type: ignore
        pynvml.nvmlInit()
        n = pynvml.nvmlDeviceGetCount()
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        name = pynvml.nvmlDeviceGetName(h)
        if isinstance(name, bytes):
            name = name.decode()
        util = pynvml.nvmlDeviceGetUtilizationRates(h).gpu
        mi = pynvml.nvmlDeviceGetMemoryInfo(h)
        pynvml.nvmlShutdown()
        return {"backend": "cuda", "name": name, "count": n, "util_pct": float(util),
                "mem_used_gb": round(mi.used / GB, 2), "mem_total_gb": round(mi.total / GB, 2)}
    except Exception:
        pass
    out = _run(["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits"])
    if out.strip():
        try:
            p = [x.strip() for x in out.strip().splitlines()[0].split(",")]
            return {"backend": "cuda", "name": p[0], "count": 1, "util_pct": float(p[1]),
                    "mem_used_gb": round(float(p[2]) / 1024, 2), "mem_total_gb": round(float(p[3]) / 1024, 2)}
        except Exception:
            warn.append("nvidia-smi 输出解析失败")
    return None


def probe_gpu(warn: list) -> dict:
    d = _gpu_apple(warn) if sys.platform == "darwin" else _gpu_nvidia(warn)
    if d:
        return d
    # torch 兜底: 判断有没有 MPS/CUDA 可用
    try:
        import torch  # type: ignore
        if torch.cuda.is_available():
            return {"backend": "cuda", "name": "CUDA device", "count": torch.cuda.device_count(),
                    "util_pct": None, "mem_used_gb": None, "mem_total_gb": None,
                    "note": "利用率未取到"}
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return {"backend": "mps", "name": "Apple GPU (via torch)", "count": 1,
                    "util_pct": None, "mem_used_gb": None, "mem_total_gb": None,
                    "note": "利用率未取到"}
    except Exception:
        pass
    return {"backend": "none", "name": "无可用加速器", "count": 0,
            "util_pct": None, "mem_used_gb": None, "mem_total_gb": None}


# ────────────────────────── 算力 ──────────────────────────
def probe_compute(gpu: dict) -> dict:
    chip = ""
    if sys.platform == "darwin":
        chip = _run(["sysctl", "-n", "machdep.cpu.brand_string"]).strip()
    tf = _TFLOPS.get(chip)
    note = ""
    if gpu.get("backend") == "cuda":
        gname = gpu.get("name", "")
        for k, v in _TFLOPS_NV.items():
            if k in gname:
                tf = v
                break
        if tf is None:
            tf = _TFLOPS_NV.get("Orin") if "Orin" in gname or "tegra" in gname.lower() else None
        note = "NVIDIA 标称 FP32"
    elif gpu.get("backend") == "mps":
        note = f"{chip} 标称 FP32 (GPU 核心)" if tf else "Apple Silicon 标称 FP32"
    est = None  # 实测算力需要 benchmark, 这里只给标称 + 实时利用率
    if gpu.get("util_pct") is not None and tf:
        est = round(tf * gpu["util_pct"] / 100.0, 2)
    return {"device": gpu.get("backend", "none"), "tflops_fp32": tf,
            "tflops_effective": est, "note": note, "cpu_brand": chip or platform.processor()}


# ────────────────────────── 训练进程 ──────────────────────────
_TRAIN_PAT = ("lerobot_train", "train_awe", "train_vla", "train_yolo", "distill_expert",
              "train_mani_geo", "joint_train", "yolo_annot_train", "_train_temp")


def probe_training() -> dict:
    procs = []
    if psutil:
        for p in psutil.process_iter(["pid", "name", "cmdline", "cpu_percent", "memory_info"]):
            try:
                cl = " ".join(p.info.get("cmdline") or [])
                if any(k in cl for k in _TRAIN_PAT):
                    mi = p.info.get("memory_info")
                    procs.append({"pid": p.info["pid"], "name": p.info.get("name") or "",
                                  "cpu": round(p.info.get("cpu_percent") or 0.0, 1),
                                  "mem_mb": round((mi.rss if mi else 0) / 1024 / 1024, 1),
                                  "cmd": cl[:120]})
            except Exception:
                continue
    return {"active": bool(procs), "count": len(procs), "procs": procs}


# ────────────────────────── 汇总 ──────────────────────────
def probe(disk_root: str | None = None) -> dict:
    warn: list[str] = []
    cpu = probe_cpu()
    mem = probe_mem()
    disk = probe_disk(disk_root)
    gpu = probe_gpu(warn)
    comp = probe_compute(gpu)
    train = probe_training()
    if mem.get("percent") is not None and mem["percent"] > 85:
        warn.append(f"内存紧张: {mem['percent']}% 已用 (可用 {mem['avail_gb']}GB)")
    if mem.get("swap_percent") and mem["swap_percent"] > 50:
        warn.append(f"Swap 已用 {mem['swap_percent']}% — 有 OOM 风险")
    if disk.get("percent") is not None and disk["percent"] > 90:
        warn.append(f"磁盘紧张: {disk['percent']}% 已用")
    host = ""
    if sys.platform == "darwin":
        host = f"{_run(['sysctl','-n','hw.model']).strip()} / {comp['cpu_brand']}"
    else:
        host = f"{platform.node()} / {comp['cpu_brand']}"
    return {"ts": time.time(), "host": host.strip(" /"), "platform": platform.platform(),
            "cpu": cpu, "mem": mem, "disk": disk, "gpu": gpu, "compute": comp,
            "training": train, "warn": warn}


def fmt(d: dict) -> str:
    """人类可读摘要 (日志/终端用)"""
    c, m, k, g, cp, t = d["cpu"], d["mem"], d["disk"], d["gpu"], d["compute"], d["training"]
    L = [f"🖥 {d['host']}"]
    L.append(f"  CPU  {c['cores']}核 · 负载 {c['load1']}/{c['load5']}/{c['load15']} · {c['percent']}%")
    L.append(f"  内存 {m['used_gb']}/{m['total_gb']}GB ({m['percent']}%) · 可用 {m['avail_gb']}GB"
             f" · swap {m['swap_used_gb']}/{m['swap_total_gb']}GB ({m['swap_percent']}%)")
    L.append(f"  磁盘 {k['used_gb']}/{k['total_gb']}GB ({k['percent']}%) · 可用 {k['free_gb']}GB")
    L.append(f"  GPU  {g['backend'].upper()} {g['name']} · 利用率 {g['util_pct']}% · 显存 {g['mem_used_gb']}GB")
    L.append(f"  算力 标称 {cp['tflops_fp32']} TFLOPS FP32 · 当前有效 ≈ {cp['tflops_effective']} TFLOPS")
    L.append(f"  训练 {'✅ 进行中 ' + str(t['count']) + ' 个进程' if t['active'] else '⏹ 无'}")
    for w in d["warn"]:
        L.append(f"  ⚠️  {w}")
    return "\n".join(L)


if __name__ == "__main__":
    import json
    r = probe()
    print(json.dumps(r, ensure_ascii=False, indent=1) if "--json" in sys.argv else fmt(r))
