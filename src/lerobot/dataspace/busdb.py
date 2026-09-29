#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🚌 DDS 总线数据库 (Bus Database) —— 对标 Vector CANoe 的 DBC/数据库视图

老倪 2026-09-29: 「所有的数据都要有 topic; 从状态空间工程开始, 所有节点之间的数据要可视化、
能够被检测、被观察; 量产期间我可以不序列化为 topic, 但工程上我可以随时探测系统, 保证数据质量。
参考 Vector CANoe, 做一个 DDS 总线, 全面检查系统数据; 状态空间工程导出的 json 可以加载到
DDS 总线上, 实现全局数据可视化。」

CANoe 概念 → 本系统:
  DBC 数据库     → 本文件(busdb): 报文(话题) + 信号(画布连线) + 节点(画布节点/进程)
  Message        → DDS topic      (例: zmax/ss/link_l2)
  Signal         → 画布上的一条连线(f→t, 端口), 是一条报文里的一个信号
  ECU / Node     → 画布节点(89 个) 与 真实发布者进程(4060发布端/数据空间守护/连线总线)
  Restbus/回灌    → tools/dds_bus.py --simulate: 把工程 json 的值发到总线上, 让没有真机时也能"看到"全图
  Measurement    → probe 的 Trace/统计(报文数·实测Hz·抖动·丢包估算·载荷)

真源(不许另写一份):
  画布工程: src/lerobot/engineering/flows/state_space_obs.json   (89 节点 / 182 连线)
  档位归属: src/lerobot/engineering/nodes/by_level.py::LEVELS_INDEX
  话题注册: src/lerobot/dataspace/topics.py::TOPICS
"""
import json
import os
import time

REPO = os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax_rel")
CANVAS = os.path.join(REPO, "src/lerobot/engineering/flows/state_space_obs.json")
OUT = os.environ.get("ZMAX_BUSDB", "/home/ubuntu/zmax_data/dataspace/busdb.json")

# 画布上"不是数据节点"的类型(背景行/纯装饰) —— 它们不参与总线
NON_NODE_TYPES = {"row_bg"}

# 层 → 总线话题(每条连线按**源节点所在层**上车)
LAYERS = ("L5", "L4", "L3", "L2", "meta")


def _level_map():
    """节点 id → 层(L2/L3/L4/L5/meta) —— 用工程自己的档位索引, 不猜"""
    try:
        import sys
        if os.path.join(REPO, "src") not in sys.path:
            sys.path.insert(0, os.path.join(REPO, "src"))
        from lerobot.engineering.nodes.by_level import LEVELS_INDEX
        m = {}
        for lv, items in LEVELS_INDEX.items():
            for it in items:
                if it and it[0]:
                    m[it[0]] = lv
        return m
    except Exception:                                                        # noqa: BLE001
        return {}


def build(canvas=CANVAS):
    """构建总线数据库: 节点 / 信号 / 报文(话题)"""
    with open(canvas, encoding="utf-8") as f:
        d = json.load(f)
    lv = _level_map()
    nodes, sigs = {}, []
    for n in d.get("nodes", []):
        if n.get("type") in NON_NODE_TYPES:
            continue
        nid = n.get("id")
        nodes[nid] = {
            "id": nid, "name": (n.get("name") or "").strip(), "type": n.get("type"),
            "layer": lv.get(nid, "meta"), "icon": n.get("icon") or "",
            "x": n.get("x"), "y": n.get("y"),
            "tx": 0, "rx": 0,
        }
    dropped = 0
    for i, l in enumerate(d.get("links", [])):
        f, t = l.get("f"), l.get("t")
        if f not in nodes or t not in nodes:
            dropped += 1
            continue
        layer = nodes[f]["layer"]
        topic = "zmax/link_value"        # 全图连线走**同一条已注册报文**; 信号身份=(src, port), 层由库查
        sig = {
            "sid": "S%03d" % (i + 1), "link_id": l.get("id"),
            "src": f, "src_name": nodes[f]["name"], "src_port": l.get("f_port"),
            "dst": t, "dst_name": nodes[t]["name"], "dst_port": l.get("t_port"),
            "label": l.get("label") or "", "layer": layer, "topic": topic,
        }
        sigs.append(sig)
        nodes[f]["tx"] += 1
        nodes[t]["rx"] += 1

    # 报文清单 = 注册表里的类型化话题 + 由连线派生的 link 话题
    try:
        from lerobot.dataspace import topics as T
        typed = {k: {"topic": T.full_name(k), "type": T.TOPICS[k]["type"],
                     "hz_design": T.TOPICS[k]["rate_hz"], "qos": T.TOPICS[k]["qos"],
                     "kind": "typed", "producer": T.TOPICS[k].get("producer", "")[:70]}
                 for k in T.TOPICS}
    except Exception:                                                        # noqa: BLE001
        typed = {}
    messages = dict(typed)
    _per_layer = {l: sum(1 for s in sigs if s["layer"] == l) for l in LAYERS}
    messages["link_value"] = {"topic": "zmax/link_value", "type": "zmax::LinkValue",
                              "hz_design": 5.0, "qos": "beat", "kind": "canvas_link",
                              "n_signals": len(sigs), "signals_by_layer": _per_layer,
                              "producer": "画布连线总线(dds_link_bus) / 工程回灌器(dds_bus --simulate)"}

    by_layer = {}
    for nid, n in nodes.items():
        by_layer.setdefault(n["layer"], []).append(nid)
    return {
        "format": "zmax-dds-busdb", "version": "1.0.0", "built": time.time(),
        "canvas": {"file": os.path.relpath(canvas, REPO), "format": d.get("format"),
                   "version": d.get("version"), "name": (d.get("name") or "")[:120]},
        "counts": {"nodes": len(nodes), "signals": len(sigs), "messages": len(messages),
                   "links_dropped": dropped,
                   "nodes_by_layer": {k: len(v) for k, v in sorted(by_layer.items())}},
        "nodes": nodes, "signals": sigs, "messages": messages,
    }


def load(path=OUT):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                        # noqa: BLE001
        return {}


def save(db, path=OUT):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=1)
    os.replace(path + ".tmp", path)
    return path


def signals_of(db, topic):
    return [s for s in db.get("signals", []) if s["topic"] == topic]


def stats_rows(db, live=None, stats=None):
    """报文统计行: 设计值(库) × 实测(probe) 合并 —— CANoe 的 Statistics 窗口数据"""
    live = live or {}
    lt = (live.get("topics") or {})
    st = ((stats or {}).get("topics") or {})
    rows = []
    for key, m in (db.get("messages") or {}).items():
        k = key
        lv = lt.get(k) or {}
        sv = st.get(k) or {}
        rows.append({
            "key": key, "topic": m["topic"], "type": m["type"], "kind": m["kind"],
            "n_signals": m.get("n_signals"), "hz_design": m.get("hz_design"),
            "hz": lv.get("hz", sv.get("hz", -1.0)),
            "count": lv.get("count", sv.get("count", 0)),
            "jitter_ms": sv.get("jitter_ms"), "loss_pct": sv.get("loss_pct"),
            "bytes": sv.get("bytes"), "matched": lv.get("matched_pubs"),
            "verdict": lv.get("verdict", "-"),
        })
    rows.sort(key=lambda r: (r["kind"] != "typed", r["topic"]))
    return rows


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="DDS 总线数据库 (CANoe DBC 等价物)")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--dump", action="store_true")
    a = ap.parse_args()
    db = build()
    if a.build or not a.dump:
        print("已写:", save(db))
    if a.dump:
        print(json.dumps({k: db[k] for k in ("counts", "canvas")}, ensure_ascii=False, indent=1))
        for k, m in db["messages"].items():
            print("  报文 %-16s %-14s 信号 %-4s 设计 %sHz  %s" %
                  (m["topic"], m["type"], m.get("n_signals", "-"), m.get("hz_design"), m["kind"]))
