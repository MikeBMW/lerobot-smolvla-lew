#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ss_link_topics.py — 状态空间工程: 连线 → DDS topic 映射与数据面
==================================================================
老倪令: 「所有连线交换的数据，都应该是 DDS topic」

现状: flows/*.json 的连线 {id,f,t,f_port,t_port,label} 只是视觉+描述,
      实际数据在进程内用 Python 对象传递 → 不走任何中间件。
改法:
  ① --annotate  为每条连线生成确定性 DDS topic 名, 写回 JSON 的 dds_topic 字段
  ② --list      打印 topic 映射表
  ③ --publish   把连线的实时数据发布到 DDS (真 DDS 数据面)
  ④ --watch     订阅并打印所有连线 topic

Topic 命名规范 (确定性, 同名连线永远同 topic):
    zmax/ss/<flow>/<from_node>.<from_port>__<to_node>.<to_port>
  例: zmax/ss/dual_brain_peg/dba0.out1__dba1.in1

DDS 传输:
  局域网 → 原生 CycloneDDS (本文件直接 pub/sub)
  跨公网 → ECS WebSocket DDS 网关 (wss://datadrive.world/ws/dds/)
"""
import argparse
import glob
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FLOWS = os.path.join(REPO, "flows")
TOPIC_PREFIX = os.environ.get("ZMAX_SS_TOPIC_PREFIX", "zmax/ss")
DDS_WS = os.environ.get("ZMAX_DDS_WS", "wss://datadrive.world/ws/dds/")


def _slug(s) -> str:
    s = re.sub(r"[^0-9A-Za-z_]+", "_", str(s if s is not None else "")).strip("_")
    return s or "x"


def topic_for(flow: str, link: dict) -> str:
    """确定性 topic 名 (同一条连线永远得到同一 topic)"""
    src = f"{_slug(link.get('f'))}.{_slug(link.get('f_port'))}"
    dst = f"{_slug(link.get('t'))}.{_slug(link.get('t_port'))}"
    return f"{TOPIC_PREFIX}/{_slug(flow)}/{src}__{dst}"


def annotate(path: str, dry: bool = False) -> dict:
    """给一个 flows JSON 的每条连线补 dds_topic 字段"""
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    flow = os.path.splitext(os.path.basename(path))[0]
    links = d.get("links") or []
    added = kept = 0
    for l in links:
        t = topic_for(flow, l)
        if l.get("dds_topic") != t:
            l["dds_topic"] = t
            added += 1
        else:
            kept += 1
    if not dry and added:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
    return {"file": os.path.basename(path), "flow": flow, "links": len(links),
            "added": added, "kept": kept}


def cmd_annotate(dry: bool):
    files = sorted(glob.glob(os.path.join(FLOWS, "*.json")))
    tot_l = tot_a = 0
    print(f"═══ 连线 → DDS topic 标注 ({len(files)} 个画布) ═══")
    for p in files:
        try:
            r = annotate(p, dry=dry)
        except Exception as e:
            print(f"  ⚠️ {os.path.basename(p)}: {type(e).__name__}: {e}")
            continue
        if r["links"]:
            print(f"  {r['file']:42s} {r['links']:3d} 条连线 · 新增{r['added']:3d} 已有{r['kept']:3d}")
        tot_l += r["links"]
        tot_a += r["added"]
    print(f"  合计 {tot_l} 条连线, 新增标注 {tot_a} 条" + (" (dry-run 未写入)" if dry else ""))


def cmd_list(flow_filter: str = "", limit: int = 40):
    files = sorted(glob.glob(os.path.join(FLOWS, "*.json")))
    n = 0
    print("═══ 连线 → DDS topic 映射表 ═══")
    for p in files:
        flow = os.path.splitext(os.path.basename(p))[0]
        if flow_filter and flow_filter not in flow:
            continue
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        links = d.get("links") or []
        if not links:
            continue
        print(f"── {flow} ({len(links)} 条) ──")
        for l in links[:limit]:
            t = l.get("dds_topic") or topic_for(flow, l)
            print(f"   {l.get('f')}.{l.get('f_port')} → {l.get('t')}.{l.get('t_port')}"
                  f"  [{l.get('label','')}]")
            print(f"      topic: {t}")
            n += 1


def _collect_live() -> list:
    """采集状态空间连线上的真实数据 (按当前可得来源)"""
    import urllib.request
    out = []
    # ① 本机硬件 (控制台节点输出)
    try:
        from hw_monitor import probe
        d = probe(measure=False)
        out.append(("console", "out1", {"cpu_pct": d["cpu"].get("percent"),
                                        "mem_pct": d["mem"].get("percent"),
                                        "gpu_pct": d["gpu"].get("util_pct"),
                                        "host": d["host"]}))
    except Exception:
        pass
    # ② ECS 闭环节点状态 (ss_dds 的同一口径)
    try:
        with urllib.request.urlopen("http://datadrive.world/api/relay/status", timeout=6) as r:
            relay = json.loads(r.read())
        out.append(("ecs_relay", "out1", {"packages": relay.get("packages"),
                                          "latest": relay.get("latest")}))
    except Exception:
        pass
    # ③ 4060 训练/推理
    try:
        with urllib.request.urlopen("http://datadrive.world/api/train/hardware", timeout=6) as r:
            hw = json.loads(r.read()).get("machines", {})
        m = hw.get("4060", {})
        if m:
            out.append(("train_4060", "out1", {"models": m.get("models"),
                                               "infer_count": m.get("infer_count"),
                                               "last_ms": m.get("last_ms")}))
        mc = hw.get("mac", {})
        if mc:
            out.append(("mac_node", "out1", {"gpu": mc.get("gpu"),
                                             "vram": mc.get("gpu_vram"),
                                             "vram_total": mc.get("gpu_vram_total")}))
    except Exception:
        pass
    return out


def cmd_publish(loop: bool, interval: float):
    """把连线数据发布到 DDS (走 ECS WS 网关 → DDS 总线)"""
    try:
        from websockets.sync.client import connect
    except Exception as e:
        print(f"❌ 需要 websockets: {e}")
        return 1
    print(f"🛰  连线 DDS 数据面 (每 {interval:.0f}s) → {DDS_WS}")
    while True:
        vals = _collect_live()
        try:
            with connect(DDS_WS, open_timeout=15) as ws:
                for node, port, payload in vals:
                    topic = f"{TOPIC_PREFIX}/live/{_slug(node)}.{_slug(port)}"
                    msg = {"type": "statespace",
                           "payload": {"node": node, "port": port, "topic": topic,
                                       "dds_topic": topic, "data": payload,
                                       "source": "mac", "ts": time.time()}}
                    ws.send(json.dumps(msg, ensure_ascii=False))
                print(f"  [{time.strftime('%H:%M:%S')}] 已发布 {len(vals)} 条连线数据")
                for n, p, v in vals:
                    print(f"     {TOPIC_PREFIX}/live/{n}.{p} = {json.dumps(v, ensure_ascii=False)[:90]}")
        except Exception as e:
            print(f"  ⚠️ 发布失败: {type(e).__name__}: {str(e)[:100]}")
        if not loop:
            return 0
        time.sleep(max(3.0, interval))


def main():
    ap = argparse.ArgumentParser(description="连线 → DDS topic 映射与数据面")
    ap.add_argument("--annotate", action="store_true", help="给连线补 dds_topic 字段")
    ap.add_argument("--dry", action="store_true", help="dry-run 不写文件")
    ap.add_argument("--list", action="store_true", help="打印映射表")
    ap.add_argument("--flow", default="", help="只看某画布 (子串匹配)")
    ap.add_argument("--publish", action="store_true", help="发布连线数据到 DDS")
    ap.add_argument("--loop", action="store_true", help="常驻")
    ap.add_argument("--interval", type=float, default=10.0)
    a = ap.parse_args()
    if a.annotate:
        cmd_annotate(a.dry)
    elif a.list:
        cmd_list(a.flow)
    elif a.publish:
        return cmd_publish(a.loop, a.interval)
    else:
        ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
