#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📡 4060 端 DDS 节点 —— 发布硬件实际值 + 训练进度, 订阅部署指令

老倪 2026-09-25: "ecs 4060 mac 消息中间件用DDS技术实现"

用法（用 dds-venv, 因为 cyclonedds 装在那里）:
  /home/ubuntu/dds-venv/bin/python tools/dds_node_4060.py                 # 持续发布(默认 5s 间隔)
  /home/ubuntu/dds-venv/bin/python tools/dds_node_4060.py --once          # 只发一次
  /home/ubuntu/dds-venv/bin/python tools/dds_node_4060.py --cfg dds/cyclonedds_unicast.xml

发布:
  zmax/hw_state    ← 复用 tools/hardware_view.py (nvidia-smi/proc/disk/实测吞吐) 的真实值
  zmax/train_prog  ← 复用 tools/train_progress_view.py (训练进度文件/日志) 的真实值
  zmax/heartbeat   ← 心跳
订阅:
  zmax/deploy_cmd  ← 收到部署指令 → 落审计 + 执行(默认 dry-run, --apply 才真动)
"""
import argparse
import json
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "dds"))
sys.path.insert(0, os.path.join(REPO, "tools"))

from zmax_node import Node                                     # noqa: E402
from zmax_types import DeployCommand, HardwareState, Heartbeat, TrainProgress  # noqa: E402

AUDIT = os.path.join(REPO, "docs", "deploy_audit.jsonl")


def hw_msg(node_name="4060", role="工作端(4060)"):
    """硬件真实值 → DDS 消息（缺测项 = -1.0, 不用 0 冒充）"""
    import hardware_view as hw
    d = hw.collect()
    g, c, m, dk, cp, r = d["gpu"], d["cpu"], d["mem"], d["disk"], d.get("compute", {}), d.get("remote", {})
    mps = r.get("mps") or {}
    return HardwareState(
        node=node_name, role=role, backend="cuda",
        device_name=(g.get("name") or "未知")[:64], ts=time.time(),
        util_pct=float(g.get("util_pct") if g.get("util_pct") is not None else -1),
        mem_used_mb=float(g.get("mem_used_mb") or -1), mem_total_mb=float(g.get("mem_total_mb") or -1),
        temp_c=float(g.get("temp_c") or -1), power_w=float(g.get("power_w") or -1),
        clk_mhz=float(g.get("clk_sm_mhz") or -1),
        cpu_cores=int(c.get("cores") or -1), cpu_util_pct=float(c.get("util_pct") or -1),
        load1=float(c.get("load1") or -1),
        mem_total_gb=float(m.get("total_gb") or -1), mem_avail_gb=float(m.get("avail_gb") or -1),
        disk_total_gb=float(dk.get("total_gb") or -1), disk_free_gb=float(dk.get("free_gb") or -1),
        train_steps_per_s=float(cp.get("sps") or -1),
        note=((g.get("power_limit_note") or "")[:100] +
              (" | 已收到 Mac 上报(MPS=%s)" % mps.get("mps_available") if r.get("ok") else " | 尚无 Mac 上报"))[:190])


def prog_msg(node_name="4060"):
    import train_progress_view as tpv
    d = tpv.collect()
    live = (d.get("live") or [])
    run = next((x for x in live if x.get("running") and not x.get("stale")), None)
    if run:
        sps = float(run.get("sps") or -1)
        return TrainProgress(node=node_name, job=str(run.get("file") or "")[:48], layer="L4",
                             step=int(run.get("step") or -1), total=int(run.get("total") or -1),
                             pct=float(run.get("pct") or -1), loss=float(run.get("loss") or -1),
                             steps_per_s=sps,
                             best_obs=float(run.get("best_obs") if run.get("best_obs") is not None else -1),
                             running=1, ts=time.time())
    jobs = [j for j in (d.get("jobs") or []) if j.get("running")]
    j = jobs[0] if jobs else ((d.get("jobs") or [None])[0])
    if not j:
        return TrainProgress(node=node_name, job="(无训练)", step=-1, total=-1, running=0, ts=time.time())
    return TrainProgress(node=node_name, job=str(j.get("log") or "")[:48], layer="L4",
                         step=int(j.get("step") or -1), total=int(j.get("total") or -1),
                         pct=float(j.get("pct") or -1), loss=float(j.get("loss") or -1),
                         steps_per_s=float(j.get("sps") or -1),
                         best_obs=float(j.get("best_obs") or -1), best_act=float(j.get("best_act") or -1),
                         gain_obs_pct=float(j.get("gain_obs") or -1), gain_act_pct=float(j.get("gain_act") or -1),
                         running=1 if j.get("running") else 0, ts=time.time())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=float, default=5.0)
    ap.add_argument("--cfg", default=os.path.join(REPO, "dds", "cyclonedds_unicast.xml"))
    ap.add_argument("--apply", action="store_true", help="收到部署指令时真执行（默认 dry-run）")
    a = ap.parse_args()

    cfg = a.cfg if os.path.isfile(a.cfg) else None
    n = Node("4060", config_xml=cfg)
    print("=" * 78)
    print("📡 4060 DDS 节点")
    print("=" * 78)
    print("  配置: %s" % (cfg or "默认(多播/localhost)"))
    print("  发布: zmax/hw_state · zmax/train_prog · zmax/heartbeat")
    print("  订阅: zmax/deploy_cmd%s" % ("（--apply 真执行）" if a.apply else "（dry-run）"))

    n.pub("hw_state")
    n.pub("train_prog")
    n.pub("heartbeat")
    n.sub("deploy_cmd")
    print("  等配对… hw_state=%s deploy_cmd=%s" %
          (n.wait_for_match("hw_state", 0, 6), n.wait_for_match("deploy_cmd", 0, 6)))

    i = 0
    while True:
        i += 1
        ts = time.strftime("%H:%M:%S")
        try:
            h = hw_msg()
            n.send("hw_state", h)
            print("  [%s] 📤 hw_state  util=%.0f%% mem=%.0f/%.0fMB %.0f°C %.1fW | CPU %.0f%% | 盘可用 %.0fGB | 吞吐 %.1f步/s"
                  % (ts, h.util_pct, h.mem_used_mb, h.mem_total_mb, h.temp_c, h.power_w,
                     h.cpu_util_pct, h.disk_free_gb, h.train_steps_per_s), flush=True)
        except Exception as e:                                                  # noqa: BLE001
            print("  [%s] ⚠️ hw_state 失败: %s: %s" % (ts, type(e).__name__, str(e)[:70]))
        try:
            p = prog_msg()
            n.send("train_prog", p)
            print("  [%s] 📤 train_prog %s step=%d/%d %.1f%% loss=%.5f best=%.5f running=%d"
                  % (ts, p.job[:22], p.step, p.total, p.pct, p.loss, p.best_obs, p.running), flush=True)
        except Exception as e:                                                  # noqa: BLE001
            print("  [%s] ⚠️ train_prog 失败: %s: %s" % (ts, type(e).__name__, str(e)[:70]))
        n.send("heartbeat", Heartbeat(node="4060", role="工作端", alive=1, ts=time.time(),
                                     extra=["cuda", "cyclone-dds"]))
        # 收部署指令
        for m in n.take("deploy_cmd", 0.5):
            print("  [%s] 📥 deploy_cmd: %s 要 %s %s (%s)" % (ts, m.issuer, m.action, m.layer, m.artifact))
            rec = {"ev": "dds_deploy_cmd", "issuer": m.issuer, "layer": m.layer,
                   "artifact": m.artifact, "action": m.action, "note": m.note,
                   "applied": bool(a.apply), "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
            try:
                os.makedirs(os.path.dirname(AUDIT), exist_ok=True)
                open(AUDIT, "a", encoding="utf-8").write(json.dumps(rec, ensure_ascii=False) + "\n")
            except Exception:                                                   # noqa: BLE001
                pass
        if a.once:
            break
        time.sleep(a.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
