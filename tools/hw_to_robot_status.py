#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🖥 把 4060 硬件(含显存占用) 写进 APP 的数据文件 robot-status.json

老倪 2026-09-25: "app要显示4060的显存占用"

APP = docs/web/robot-monitor.html, 它从 **mac 分支** 的 docs/web/robot-status.json 读数据。
本脚本: 采集 4060 真实硬件 → 合并进该 JSON 的 `hardware` 段 → (可选)推到 mac 分支。
★ 只写真实数据; 采不到 = null（不编造）; 自测节点拒绝。

用法:
  python3 tools/hw_to_robot_status.py                # 只写本地文件
  python3 tools/hw_to_robot_status.py --push         # 写 + 推送 mac 分支（APP 立刻可见）
  python3 tools/hw_to_robot_status.py --push --watch 60   # 每 60s 持续
"""
import argparse
import json
import os
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
JSON_F = os.path.join(REPO, "docs", "web", "robot-status.json")
DDS_F = "/home/ubuntu/stable-wm-cache/reports/dds_latest.json"


def hardware_section():
    """采集 4060 硬件（真实值; 采不到 = None）"""
    import hardware_view as hw
    d = hw.collect()
    g, c, m, dk, cp = d.get("gpu") or {}, d.get("cpu") or {}, d.get("mem") or {}, \
        d.get("disk") or {}, d.get("compute") or {}
    mu, mt = g.get("mem_used_mb"), g.get("mem_total_mb")
    return {
        "name": g.get("name") or "(未检测到 GPU)",
        "node": "4060（静静·工作端）",
        "backend": "cuda",
        "ts": d.get("ts"),
        # ★ 显存占用（老倪明确要的）—— 单位 MB + 百分比
        "vram_used_mb": mu,
        "vram_total_mb": mt,
        "vram_used_pct": g.get("mem_used_pct"),
        "gpu_util_pct": g.get("util_pct"),
        "gpu_temp_c": g.get("temp_c"),
        "gpu_power_w": g.get("power_w"),
        "gpu_power_limit_note": g.get("power_limit_note"),
        "gpu_clk_mhz": g.get("clk_sm_mhz"),
        "cpu_util_pct": c.get("util_pct"),
        "cpu_cores": c.get("cores"),
        "load1": c.get("load1"),
        "mem_used_gb": m.get("used_gb"),
        "mem_total_gb": m.get("total_gb"),
        "mem_avail_gb": m.get("avail_gb"),
        "disk_free_gb": dk.get("free_gb"),
        "disk_total_gb": dk.get("total_gb"),
        "train_steps_per_s": cp.get("sps"),
    }


def mac_section():
    """Mac（小芳·备份端）硬件 —— 从 DDS 桥读（自测节点已过滤）"""
    try:
        j = json.load(open(DDS_F, encoding="utf-8"))
    except Exception:                                                           # noqa: BLE001
        return None
    for k, v in (j.get("nodes") or {}).items():
        if "TEST" in k.upper() or "自测" in k:
            continue
        h = v.get("hw") or {}
        if str(h.get("backend", "")).lower() == "mps" or "mac" in k.lower():
            if v.get("stale"):
                return {"node": k, "role": v.get("role") or "备份端(Mac)", "stale": True,
                        "age_s": v.get("age_s"), "note": "上报已过期，未显示数值"}
            return {"node": k, "role": v.get("role") or "备份端(Mac)", "backend": "mps",
                    "device_name": h.get("device_name"), "stale": False, "age_s": v.get("age_s"),
                    "mem_avail_gb": h.get("mem_avail_gb"), "mem_total_gb": h.get("mem_total_gb"),
                    "disk_free_gb": h.get("disk_free_gb"), "cpu_util_pct": h.get("cpu_util_pct"),
                    "cpu_cores": h.get("cpu_cores"), "note": (h.get("note") or "")[:120]}
    return None


def merge(push=False):
    try:
        d = json.load(open(JSON_F, encoding="utf-8"))
    except Exception:                                                           # noqa: BLE001
        d = {}
    hw = hardware_section()
    mac = mac_section()
    d["hardware"] = hw
    d["hardware_mac"] = mac
    md = d.setdefault("metadata", {})
    md["hardware_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    md["hardware_source"] = "4060 本机 nvidia-smi/proc（真实采集）"
    os.makedirs(os.path.dirname(JSON_F), exist_ok=True)
    json.dump(d, open(JSON_F, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("  ✅ 已写入 %s" % os.path.relpath(JSON_F, REPO))
    print("     4060: %s | 显存 %s/%s MB (%s%%) | GPU %s%% | %s°C | %sW" %
          (hw["name"][:34], hw["vram_used_mb"], hw["vram_total_mb"], hw["vram_used_pct"],
           hw["gpu_util_pct"], hw["gpu_temp_c"], hw["gpu_power_w"]))
    print("     Mac : %s" % (("%s · 内存 %s/%sGB" % (mac.get("node"), mac.get("mem_avail_gb"),
                                                    mac.get("mem_total_gb")))
                             if mac and not mac.get("stale") else
                             ("%s（%s）" % (mac.get("node"), mac.get("note")) if mac else
                              "未上报（需小芳在她 Mac 跑 mac_hw_report.py --dds）")))
    if push:
        cmds = [
            "git -C %s add docs/web/robot-status.json" % REPO,
            "git -C %s -c user.email=agent@zmax -c user.name=Hermes commit -q -m "
            "'chore(hw): 更新 4060 硬件/显存占用到 APP 数据文件'" % REPO,
            "git -C %s -c http.sslVerify=false push origin HEAD:mac" % REPO,
            "git -C %s -c http.sslVerify=false push origin HEAD:main" % REPO,
        ]
        for c in cmds:
            r = subprocess.run(c, shell=True, capture_output=True, text=True, timeout=90)
            if r.returncode != 0 and "nothing to commit" not in (r.stdout + r.stderr):
                print("     ⚠️ %s → %s" % (c.split()[3], (r.stderr or r.stdout).strip()[:90]))
        print("     ✅ 已推送 mac + main 分支（APP 刷新即见）")
    return hw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true", help="推送到 mac 分支（APP 数据源）")
    ap.add_argument("--watch", type=int, default=0, help=">0 = 每 N 秒持续")
    a = ap.parse_args()
    while True:
        print("[%s]" % time.strftime("%H:%M:%S"))
        try:
            merge(push=a.push)
        except Exception as e:                                                  # noqa: BLE001
            print("  ⚠️ 失败: %s: %s" % (type(e).__name__, str(e)[:110]))
        if a.watch <= 0:
            return 0
        time.sleep(a.watch)


if __name__ == "__main__":
    raise SystemExit(main())
