#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 nodes/by_level.py —— 按 L2/L3/L4/L5 组织节点逻辑的"档位视图"。

只做索引, 不搬代码: 每条 key → (注册函数, 所在文件, 该档位节点)。
物理拆分(每档一个文件)是下一步, 保留在同一份 library.py 里是当前唯一真源。
"""
import json
import os
import sys

REPO = "/home/ubuntu/zmax"
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "tools", "gui"))

from lerobot.engineering import flows, levels, registry  # noqa: E402

canvas = flows._read()
names = {n.get("id"): str(n.get("name") or "") for n in canvas["nodes"]}
bm = levels.band_map(canvas)

out = {}
for lv in ("L2", "L3", "L4", "L5", "meta"):
    rows = []
    for nid in levels.level_nodes(lv, band=bm):
        key = registry.match_node(names.get(nid, ""))
        info = registry.get(key) or {}
        rows.append((nid, names.get(nid, ""), key, os.path.basename(registry.home_file(key) or "?"),
                     info.get("fn").__name__ if info.get("fn") else None))
    out[lv] = rows

HEADER = '''# -*- coding: utf-8 -*-
"""档位视图 (by_level) —— 按 L2/L3/L4/L5 把节点逻辑索引出来 (自动生成, 勿手改)。

生成: `gui-venv311/bin/python tools/verify_engineering.py --regen-by-level`
真源: `..nodes.library` (逻辑) + `..registry` (key↔函数) + `..flows.state_space_obs.json` (画布) + `..levels` (档位归属)

用途: 一眼看清"这一档有哪些节点、每个节点落到哪个函数、函数在哪个文件" ——
GUI 只显示, 逻辑在包里, 这份索引就是把两边对上的那张表。
"""

LEVELS_INDEX = {
'''
lines = [HEADER]
for lv in ("L2", "L3", "L4", "L5", "meta"):
    lines.append('    "%s": [\n' % lv)
    for nid, nm, key, f, fn in out[lv]:
        lines.append('        ("%s", "%s", %r, "%s", %r),\n'
                     % (nid, nm.replace('"', "'"), key, f, fn))
    lines.append("    ],\n")
lines.append('''}


def keys_of(level):
    """该档位的逻辑 key 列表 (可执行/可查源码)"""
    return [r[2] for r in LEVELS_INDEX.get(level, []) if r[2]]


def funcs_of(level):
    """该档位 key → 真函数"""
    from ..registry import get
    return {k: (get(k) or {}).get("fn") for k in keys_of(level)}


def summary():
    return {lv: {"nodes": len(rows), "with_logic": len([r for r in rows if r[2]])}
            for lv, rows in LEVELS_INDEX.items()}


if __name__ == "__main__":
    import json as _j
    print(_j.dumps(summary(), ensure_ascii=False, indent=2))
''')
open(os.path.join(REPO, "src/lerobot/engineering/nodes/by_level.py"), "w", encoding="utf-8").write("".join(lines))
print("生成:", os.path.join(REPO, "src/lerobot/engineering/nodes/by_level.py"))
for lv in ("L2", "L3", "L4", "L5", "meta"):
    print("  %-5s %2d 节点 · %2d 有逻辑" % (lv, len(out[lv]), len([r for r in out[lv] if r[2]])))
