#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🍎 Mac 硬件上报（给小芳）—— 检测 MPS 并上报到 4060 控制台

老倪 2026-09-25: "4060 呢? mps呢? app要显示实际值"

在小芳的 Mac 上跑（无需额外依赖, 标准库 + 可选 torch）:
  python3 mac_hw_report.py --server http://<4060的IP>:8799
  python3 mac_hw_report.py --server http://192.168.23.1:8799 --watch 60   # 每 60s 持续上报

会采集并上报**实际值**:
  · MPS  : torch.backends.mps.is_available() / is_built() + 设备名 + 内存
           （未装 torch 时明确报 "未安装 torch → MPS 不可测", 不编造）
  · CPU  : 型号/核数 + 负载(loadavg)
  · 内存 : 总量/可用（vm_stat 或 psutil）
  · 磁盘 : 总量/可用 + 关键目录占用
"""
import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.request


def sh(c, t=15):
    try:
        return subprocess.run(c, shell=True, capture_output=True, text=True, timeout=t).stdout.strip()
    except Exception as e:                                                      # noqa: BLE001
        return "ERR:%s" % e


def mps():
    """MPS 实际状态（Apple Metal GPU 后端）"""
    d = {"backend": "mps", "platform": platform.platform(), "machine": platform.machine(),
         "macos": platform.mac_ver()[0]}
    try:
        import torch
        d["torch"] = torch.__version__
        d["mps_built"] = bool(torch.backends.mps.is_built())
        d["mps_available"] = bool(torch.backends.mps.is_available())
        if d["mps_available"]:
            try:
                x = torch.ones(1024, 1024, device="mps")
                y = (x @ x).sum().item()          # 真跑一次矩阵乘 → 证明可用
                d["probe"] = "1024x1024 matmul OK, sum=%.1f" % y
                d["device_name"] = torch.backends.mps.get_device_name() if hasattr(
                    torch.backends.mps, "get_device_name") else "Apple MPS (Metal)"
                del x, y
            except Exception as e:                                              # noqa: BLE001
                d["probe"] = "实跑失败: %s: %s" % (type(e).__name__, str(e)[:60])
        else:
            d["probe"] = "MPS 不可用（未构建或本机不支持）"
    except ImportError:
        d["torch"] = None
        d["mps_available"] = None
        d["probe"] = "未安装 torch → MPS 不可测（装了 torch 才有 MPS 后端）"
    # Apple Silicon 芯片名
    d["chip"] = sh("sysctl -n machdep.cpu.brand_string") or (sh("sysctl -n hw.model") or "未知")
    return d


def cpu_mem_disk():
    n = os.cpu_count() or 1
    la = os.getloadavg() if hasattr(os, "getloadavg") else (0, 0, 0)
    mem = {}
    try:
        page = int(sh("sysctl -n hw.pagesize") or 4096)
        vm = sh("vm_stat")
        g = lambda k: int([ln for ln in vm.splitlines() if k in ln][0].split(":")[1].strip().rstrip("."))  # noqa: E731
        free_p = g("Pages free") + g("Pages inactive")
        tot = int(sh("sysctl -n hw.memsize") or 0)
        mem = {"total_gb": round(tot / 1073741824, 1),
               "avail_gb": round(free_p * page / 1073741824, 1)}
        if mem["total_gb"]:
            mem["used_pct"] = round(100 * (1 - mem["avail_gb"] / mem["total_gb"]), 1)
    except Exception as e:                                                      # noqa: BLE001
        mem = {"note": "%s: %s" % (type(e).__name__, str(e)[:50])}
    du = shutil.disk_usage(os.path.expanduser("~"))
    return {"cores": n, "load1": round(la[0], 2), "load5": round(la[1], 2), "load15": round(la[2], 2),
            "load_pct": round(100.0 * la[0] / n, 1), "mem": mem,
            "disk": {"total_gb": round(du.total / 1073741824, 1), "free_gb": round(du.free / 1073741824, 1),
                     "used_pct": round(100.0 * du.used / du.total, 1)}}


def dds_publish(payload, cfg=None):
    """DDS 方式上报（老倪: 三端消息中间件用 DDS）—— 需在 dds-venv 里跑"""
    try:
        import sys as _s
        _s.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dds"))
        from zmax_node import Node
        from zmax_types import HardwareState
        m = payload["mps"]
        mem = payload.get("mem") or {}
        dk = payload.get("disk") or {}
        msg = HardwareState(
            node=payload["host"][:48], role="备份端(Mac)", backend="mps",
            device_name=(m.get("chip") or m.get("device_name") or "Apple")[:64], ts=time.time(),
            util_pct=-1.0,                                     # Mac 无统一利用率接口 → 明确 -1
            mem_used_mb=-1.0,
            mem_total_mb=float((mem.get("total_gb") or 0) * 1024 or -1),
            temp_c=-1.0, power_w=-1.0, clk_mhz=-1.0,
            cpu_cores=int(payload.get("cores") or -1),
            load1=float(payload.get("load1") or -1),
            mem_total_gb=float(mem.get("total_gb") or -1),
            mem_avail_gb=float(mem.get("avail_gb") or -1),
            disk_total_gb=float(dk.get("total_gb") or -1),
            disk_free_gb=float(dk.get("free_gb") or -1),
            note=("MPS available=%s · torch=%s · %s" % (m.get("mps_available"), m.get("torch"),
                                                        m.get("probe")))[:190])
        n = Node("Mac", config_xml=cfg)
        n.pub("hw_state")
        n.pub("heartbeat")
        n.wait_for_match("hw_state", 0, 8)
        n.send("hw_state", msg)
        print("  ✅ DDS 已发布: zmax/hw_state (MPS available=%s)" % m.get("mps_available"))
        return True
    except ImportError as e:
        print("  ❌ DDS 发布失败(需 cyclonedds): %s" % e)
        print("     安装: python3 -m venv ~/dds-venv && ~/dds-venv/bin/pip install cyclonedds")
        return False
    except Exception as e:                                                      # noqa: BLE001
        print("  ❌ DDS 发布失败: %s: %s" % (type(e).__name__, str(e)[:90]))
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="", help="4060 控制台地址(HTTP 方式), 如 http://192.168.23.1:8799")
    ap.add_argument("--dds", action="store_true", help="★ 用 DDS 发布(Cyclone DDS, 需 dds-venv)")
    ap.add_argument("--cfg", default="", help="DDS 跨网配置 XML")
    ap.add_argument("--watch", type=int, default=0, help=">0 = 每 N 秒持续上报; 0 = 只报一次")
    ap.add_argument("--out", default="", help="同时写本地文件（可选）")
    a = ap.parse_args()

    def payload():
        return {"role": "小芳(Mac 备份端)", "host": platform.node(),
                "ts": time.time(), "mps": mps(), **cpu_mem_disk()}

    while True:
        p = payload()
        txt = json.dumps(p, ensure_ascii=False)
        m = p["mps"]
        print("=" * 74)
        print("🍎 Mac 硬件实际值 — %s (%s)" % (p["host"], m.get("chip")))
        print("=" * 74)
        print("  MPS : available=%s · built=%s · torch=%s" %
              (m.get("mps_available"), m.get("mps_built"), m.get("torch")))
        print("        %s" % m.get("probe"))
        print("  CPU : %s 核 · load %s/%s/%s (%.0f%%)" %
              (p["cores"], p["load1"], p["load5"], p["load15"], p["load_pct"]))
        print("  内存: %s" % p["mem"])
        print("  磁盘: %s" % p["disk"])
        if a.out:
            open(a.out, "w", encoding="utf-8").write(txt)
        if a.dds:
            dds_publish(p, a.cfg or None)
        elif a.server:
            try:
                req = urllib.request.Request(a.server.rstrip("/") + "/api/hardware/report",
                                             data=txt.encode(), headers={"Content-Type": "application/json"})
                r = json.load(urllib.request.urlopen(req, timeout=20))
                print("  ✅ 已上报 → %s : %s" % (a.server, r.get("ok")))
            except Exception as e:                                              # noqa: BLE001
                print("  ❌ 上报失败: %s: %s" % (type(e).__name__, str(e)[:80]))
        else:
            print("  （未指定 --dds / --server, 仅本地打印）")
        if a.watch <= 0:
            return 0
        time.sleep(a.watch)


if __name__ == "__main__":
    sys.exit(main())
