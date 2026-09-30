#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""状态空间画布 · 「每个主要节点 → 真代码在哪」+ 数据流可调试点 清单 (只读)

给老倪 VSCode 调试用: 每个画布节点 → 注册 key → **执行函数所在文件:行** → 该函数真实调用的
外部模型/文件 (registry + sourceview), 外加连线数 (孤岛判定) 与档位分层。

用法: cd /home/ubuntu/zmax && ./gui-venv311/bin/python tools/ss_node_debug_map.py [flow.json]
输出: 屏幕表格 + reports/ss_node_debug_map_<ts>.json
"""
from __future__ import annotations

import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src"), ROOT]
os.chdir(ROOT)

from lerobot.engineering import registry, sourceview  # noqa: E402
from lerobot.engineering import flows as E_flows  # noqa: E402

FLOW = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "flows", "state_space_obs.json")
d = json.load(open(FLOW, encoding="utf-8"))
nodes, links = d["nodes"], d.get("links", [])

# 连线统计 (孤岛判定)
deg = {}
for l in links:
    for k in ("f", "t"):
        v = l.get(k)
        if v:
            deg[v] = deg.get(v, 0) + 1


def level_of(name: str) -> str:
    for tag in ("L5", "L4", "L3", "L2", "L1"):
        if tag in name:
            return tag
    return "-"


rows = []
for n in nodes:
    if n.get("type") == "row_bg":
        continue
    nm = str(n.get("name", ""))
    key = registry.match_node(nm)
    info = registry.get(key) or {}
    fn = info.get("fn")
    file_ = registry.home_file(key) if key else None
    line = registry.home_line(key) if key else None
    ext = None
    try:
        if key:
            ext = sourceview.get_node_external_symbol(key) if hasattr(sourceview, "get_node_external_symbol") else None
    except Exception:
        ext = None
    rows.append({
        "id": n.get("id"), "name": nm, "type": n.get("type"),
        "w": n.get("w"), "h": n.get("h"), "links": deg.get(n.get("id"), 0),
        "level": level_of(nm), "key": key,
        "fn": getattr(fn, "__name__", None),
        "file": (os.path.relpath(file_, ROOT) if file_ else None),
        "line": line,
        "doc": (info.get("doc") or "")[:90],
        "external": ext,
        "params_keys": sorted((n.get("params") or {}).keys()),
    })

rows.sort(key=lambda r: (r["level"], str(r["name"])))
print(f"画布 {os.path.basename(FLOW)} · 节点 {len(rows)} (不含色带) · 连线 {len(links)}")
print(f"注册表: {registry.stats()['keys']} 个 key")
print()
hdr = f"{'节点':<34} {'档':<3} {'线':>3} {'key':<18} {'执行函数':<22} 文件:行"
print(hdr)
print("-" * len(hdr))
for r in rows:
    loc = f"{r['file']}:{r['line']}" if r["file"] else "—"
    fn = (r["fn"] or "—")[:20]
    print(f"{r['name'][:33]:<34} {r['level']:<3} {r['links']:>3} {(r['key'] or '❌未注册')[:18]:<18} {fn:<22} {loc}")
no_key = [r for r in rows if not r["key"]]
island = [r for r in rows if r["links"] == 0]
print()
print(f"无执行注册: {len(no_key)}" + ("".join(f"\n   · {r['name']}" for r in no_key[:12]) if no_key else ""))
print(f"孤岛(连线=0): {len(island)}" + ("".join(f"\n   · {r['name']}" for r in island[:12]) if island else ""))
os.makedirs(os.path.join(ROOT, "reports"), exist_ok=True)
out = os.path.join(ROOT, "reports", f"ss_node_debug_map_{time.strftime('%Y%m%d_%H%M%S')}.json")
json.dump({"flow": FLOW, "rows": rows, "no_key": [r["name"] for r in no_key],
           "island": [r["name"] for r in island], "links": len(links)},
          open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"\n落盘: {os.path.relpath(out, ROOT)}")
sys.stdout.flush()
