#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🌉 DDS → JSON 桥 —— 把 DDS 收到的三端状态落到一个 JSON, 供 APP 控制台读

老倪 2026-09-25: "4060 和 mac的硬件资源也要在APP显示 用DDS传数据"

为什么要桥: APP 控制台跑在**系统 python**（零依赖 http.server）; cyclonedds 装在 dds-venv。
           桥在 dds-venv 里订阅 DDS → 写 JSON; 控制台只读 JSON → 两端解耦, 都不互相污染。

订阅: zmax/hw_state · zmax/train_prog · zmax/heartbeat
落盘: <reports>/dds_latest.json  （按节点名索引, 每节点只留最新; 带 recv_ts/age 判新鲜度）
用法: /home/ubuntu/dds-venv/bin/python tools/dds_bridge.py [--cfg dds/cyclonedds_unicast.xml]
"""
import argparse
import json
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "dds"))
OUT = "/home/ubuntu/stable-wm-cache/reports/dds_latest.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cfg", default=os.path.join(REPO, "dds", "cyclonedds_unicast.xml"),
                    help="单播配置 XML（★默认必用: 本机多网卡时多播会选错网卡→发现不到）")
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--stale", type=float, default=15.0, help="超过 N 秒未更新 → 标 stale")
    a = ap.parse_args()

    from zmax_node import Node
    cfg = a.cfg if (a.cfg and os.path.isfile(a.cfg)) else None
    n = Node("bridge", config_xml=cfg)  # ★ 单播=绕开"多网卡选错"的坑
    for t in ("hw_state", "train_prog", "heartbeat"):
        n.sub(t)
    print("=" * 74)
    print("🌉 DDS → JSON 桥")
    print("=" * 74)
    print("  订阅: zmax/hw_state · zmax/train_prog · zmax/heartbeat")
    print("  落盘: %s" % OUT)
    print("  配置: %s" % (a.cfg or "默认(多播/localhost)"))

    nodes = {}          # node → {hw:..., prog:..., hb:..., recv_ts}
    t0 = time.time()
    last_tick = 0.0
    while True:
        for topic in ("hw_state", "train_prog", "heartbeat"):
            for m in n.take(topic, 0.2):
                # ★ 只取 IDL 字段（m.__dict__ 里还含 DDS 的 SampleInfo, 不可 JSON 序列化）
                keys = {"hw_state": ("node", "role", "backend", "device_name", "ts", "util_pct",
                                     "mem_used_mb", "mem_total_mb", "temp_c", "power_w", "clk_mhz",
                                     "cpu_cores", "cpu_util_pct", "load1", "mem_total_gb", "mem_avail_gb",
                                     "disk_total_gb", "disk_free_gb", "train_steps_per_s", "note"),
                        "train_prog": ("node", "job", "layer", "step", "total", "pct", "loss",
                                       "steps_per_s", "best_obs", "best_act", "gain_obs_pct",
                                       "gain_act_pct", "running", "ts"),
                        "heartbeat": ("node", "role", "alive", "ts", "extra")}[topic]
                d = {}
                for k in keys:
                    v = getattr(m, k, None)
                    if isinstance(v, list):
                        v = [str(x) for x in v]
                    d[k] = v
                key = str(d.get("node") or "?").strip()
                if "TEST" in key.upper() or "自测" in key:      # ★ 自测节点绝不进生产视图
                    continue
                slot = nodes.setdefault(key, {})
                slot["hw" if topic == "hw_state" else ("prog" if topic == "train_prog" else "hb")] = d
                slot["recv_ts"] = time.time()
                slot["role"] = d.get("role") or slot.get("role") or ""
        now = time.time()
        if now - last_tick >= max(1.0, a.interval):
            last_tick = now
            out = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "uptime_s": round(now - t0, 1),
                   "nodes": {}}
            for k in [kk for kk, vv in nodes.items() if (now - (vv.get("recv_ts") or 0)) > 120]:
                nodes.pop(k, None)                              # ★ 过期节点移除（防僵尸）
            for k, v in nodes.items():
                age = round(now - (v.get("recv_ts") or 0), 1)
                out["nodes"][k] = {**v, "age_s": age, "stale": age > a.stale}
            os.makedirs(os.path.dirname(OUT), exist_ok=True)
            try:
                json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
            except Exception as e:                                             # noqa: BLE001
                print("  ⚠️ 写 JSON 失败: %s" % str(e)[:70], flush=True)
            if int(now - t0) % 30 < 2:
                names = ", ".join("%s(%s)%s" % (k, v.get("role", "?"), "⚠️stale" if v.get("stale") else "")
                                  for k, v in out["nodes"].items())
                print("  [%s] 节点 %d 个: %s" % (out["ts"], len(out["nodes"]), names or "（暂无）"), flush=True)
        time.sleep(0.2)


if __name__ == "__main__":
    raise SystemExit(main())
