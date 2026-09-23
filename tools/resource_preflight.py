#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🖥 资源预检 + 档位建议 —— 备份端(小芳/Mac)先跑这个再接收系统

老倪 2026-09-23: "小芳你的系统资源有限, 你要仔细分析, 保证接受的系统性能不减,
               但是不能崩溃, 资源要先评估"

设计: 纯标准库(不依赖 torch/numpy), 收包**之前**就能跑 → 先评估再决定收多少。
输出: 硬件画像 + 三档配置建议(保守/标准/激进) + **崩溃红线校验** + 收包建议(T1/T2/T3)
内存模型锚点来自 4060 实测 (batch128 推理 1.3GB / batch128 训练 2.0GB / 权重 0.35GB)
"""
import json
import os
import platform
import shutil
import subprocess
import sys

# ── 实测锚点 (4060 8GB, 统一主干 88.9M 参数) ──
W_FP32 = 0.35          # 权重 fp32 (GB)
MEM_INFER_B1 = 0.50    # batch1 推理峰值 (GB)
MEM_INFER_B128 = 1.30  # batch128 推理峰值
MEM_TRAIN_B24 = 1.32   # batch24 LoRA 训练峰值
MEM_TRAIN_B128 = 2.00  # batch128 LoRA 训练峰值
SAFETY = 0.70          # 崩溃红线: 峰值 ≤ 可用内存 × 0.70


def hw():
    d = {}
    d["platform"] = platform.platform()
    d["machine"] = platform.machine()
    d["cpu"] = os.cpu_count()
    try:
        with open("/proc/meminfo") as f:
            for ln in f:
                if ln.startswith("MemTotal"):
                    d["mem_gb"] = round(int(ln.split()[1]) / 1048576.0, 1)
    except Exception:
        d["mem_gb"] = None
    if d["mem_gb"] is None:            # macOS
        try:
            o = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True)
            d["mem_gb"] = round(int(o.stdout.strip()) / 1073741824.0, 1)
        except Exception:
            d["mem_gb"] = None
    try:
        d["disk_avail_gb"] = round(shutil.disk_usage(os.path.expanduser("~")).free / 1073741824.0, 1)
    except Exception:
        d["disk_avail_gb"] = None
    # GPU: CUDA(nvidia) / MPS(apple) / 皆无(CPU)
    d["accelerator"] = "cpu"
    try:
        o = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                           capture_output=True, text=True, timeout=5)
        if o.returncode == 0 and o.stdout.strip():
            d["accelerator"] = "cuda: " + o.stdout.strip().split("\n")[0]
    except Exception:
        pass
    if d["accelerator"] == "cpu" and d["machine"] in ("arm64", "aarch64") and sys.platform == "darwin":
        d["accelerator"] = "mps (Apple Silicon 统一内存)"
    d["python"] = platform.python_version()
    d["has_torch"] = _try("torch")
    d["has_transformers"] = _try("transformers")
    d["has_h5py"] = _try("h5py")
    d["has_mujoco"] = _try("mujoco")
    return d


def _try(mod):
    try:
        __import__(mod)
        return True
    except Exception:
        return False


def tiers(mem):
    """按可用内存给出三档 (峰值 ≤ mem×0.70 才算不崩)"""
    cap = (mem or 8.0) * SAFETY
    out = []
    for name, inf_b, tr_b, need in (
        ("保守 (仅推理/演示)", 32, 0, 0.9),
        ("标准 (推理+LoRA微调)", 64, 24, 1.6),
        ("激进 (大 batch 训练)", 128, 128, 2.4),
    ):
        ok = need <= cap
        out.append({"tier": name, "infer_batch": inf_b, "train_batch": tr_b,
                    "peak_gb": round(need, 2), "cap_gb": round(cap, 2), "ok": ok})
    return out


def main():
    d = hw()
    print("=" * 78)
    print("🖥  资源预检 (备份端收包前必跑) — %s" % d["platform"])
    print("=" * 78)
    print("  CPU 核心     : %s" % d["cpu"])
    print("  内存         : %s GB" % d["mem_gb"])
    print("  磁盘可用     : %s GB" % d["disk_avail_gb"])
    print("  加速器       : %s" % d["accelerator"])
    print("  Python       : %s" % d["python"])
    print("  关键依赖     : torch=%s transformers=%s h5py=%s mujoco=%s"
          % (d["has_torch"], d["has_transformers"], d["has_h5py"], d["has_mujoco"]))

    ts = tiers(d["mem_gb"])
    print("\n── 档位建议 (崩溃红线: 峰值 ≤ 内存×%.0f%%) ──" % (SAFETY * 100))
    for t in ts:
        print("  %-24s 推理 batch %-4s 训练 batch %-4s 峰值 %.2f/%.2f GB  %s"
              % (t["tier"], t["infer_batch"], t["train_batch"], t["peak_gb"], t["cap_gb"],
                 "✅ 可跑" if t["ok"] else "❌ 超红线"))

    # 收包建议 (按磁盘与内存)
    print("\n── 收包建议 ──")
    dav = d["disk_avail_gb"] or 0
    plan = []
    if dav >= 3:
        plan.append(("T1 核心 847MB (代码+4权重+配置+流程拓扑)", True))
    else:
        plan.append(("T1 核心 847MB", False))
    if dav >= 30:
        plan.append(("T2 重要 12.2GB (报告/记忆/注册表)", True))
    else:
        plan.append(("T2 重要 12.2GB → **建议精简: 只取 reports/*.json + data/*.json ≈ 200MB**", False))
    plan.append(("T3 大数据 442GB → **不带, 按需拉 1 个小样本切片 (≤500MB)**", False))
    plan.append(("venv → **在 Mac 重建** (arm64 wheel 不通用), 用 tools/resource_preflight.py 之后跑 bootstrap", False))
    for s, ok in plan:
        print("   %s %s" % ("✅" if ok else "⚠️ ", s))

    # 结论
    ok_std = any(t["ok"] for t in ts if "标准" in t["tier"])
    ok_min = any(t["ok"] for t in ts if "保守" in t["tier"])
    print("\n" + "=" * 78)
    if ok_std:
        print("✅ 结论: 本机**可跑标准档**(推理 + LoRA 微调), 性能不减, 不崩")
    elif ok_min:
        print("⚠️  结论: 本机**只能跑保守档**(仅推理/演示) — 训练请回工作端(4060)做, 端侧只推理")
    else:
        print("❌ 结论: 内存不足 (需 ≥ %.1fGB 可用), 建议只收 T1 代码做**只读分析**, 不跑模型"
              % (0.9 / SAFETY))
    print("=" * 78)
    json.dump({"hw": d, "tiers": ts}, open("/tmp/resource_preflight.json", "w"), ensure_ascii=False, indent=1)
    print("明细已存 /tmp/resource_preflight.json (发回工作端备案)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
