#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""画布节点 → 真实执行函数 / 文件:行 全表 (只读) —— VSCode 逐节点断点清单生成器。

为什么走注册表而不是正则: 与 GUI 双击分派逐字同源 (registry.match_node + sourceview),
自写 `_reg("key"` 正则会漏掉循环注册 (`for skid: _reg(skid, ...)` → SK01-08)。

用法: python3 tools/ss_node_debug_map.py [flows/state_space_obs.json]
输出: 终端表格 + reports/ss_node_debug_map.txt/.json
"""
import json
import os
import sys

def _find_repo() -> str:
    """仓库根 = 环境变量 ZMAX_REPO_ROOT → 当前目录往上找含 flows/ → 脚本位置往上找。
    (本脚本常被放在技能目录里跑, 不能拿脚本自身目录当仓库根。)"""
    env = os.environ.get("ZMAX_REPO_ROOT")
    if env and os.path.isdir(os.path.join(env, "flows")):
        return env
    for start in (os.getcwd(), os.path.dirname(os.path.abspath(__file__))):
        cur = start
        for _ in range(8):
            if os.path.isdir(os.path.join(cur, "flows")) and os.path.isdir(os.path.join(cur, "src")):
                return cur
            nxt = os.path.dirname(cur)
            if nxt == cur:
                break
            cur = nxt
    return os.getcwd()


ROOT = _find_repo()                                                    # 仓库根
sys.path.insert(0, os.path.join(ROOT, "src"))


def main() -> int:
    flow = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "flows", "state_space_obs.json")
    d = json.load(open(flow, encoding="utf-8"))
    nodes = [n for n in d.get("nodes", []) if isinstance(n, dict) and n.get("type") != "row_bg"]
    links = d.get("links", []) or []

    from lerobot.engineering.registry import NODE_LOGIC, match_node   # noqa: E402
    try:
        from lerobot.engineering.sourceview import get_node_location   # noqa: E402
    except Exception:                                                  # noqa: BLE001
        get_node_location = None

    deg = {}
    for l in links:
        if not isinstance(l, dict):
            continue
        for k in (l.get("f"), l.get("t")):
            if k:
                deg[k] = deg.get(k, 0) + 1

    rows, no_reg, island = [], [], []
    for n in nodes:
        name = n.get("name", "")
        key = match_node(name)
        fn = (NODE_LOGIC.get(key) or {}).get("fn") if key else None
        loc = ""
        try:
            if fn is not None and get_node_location is not None:
                loc = get_node_location(name) or ""
        except Exception:                                              # noqa: BLE001
            loc = ""
        if not loc and fn is not None:
            try:
                _f = sys.modules.get(fn.__module__)
                loc = "%s:%d" % (os.path.relpath(os.path.abspath(_f.__file__), ROOT), fn.__code__.co_firstlineno)
            except Exception:                                          # noqa: BLE001
                loc = getattr(fn, "__name__", "?")
        deg_n = deg.get(n.get("id"), 0)
        rows.append({"node": name, "id": n.get("id"), "key": key,
                     "fn": getattr(fn, "__name__", None), "loc": loc, "links": deg_n})
        if key is None:
            no_reg.append(name)
        if deg_n == 0:
            island.append(name)

    out = os.path.join(ROOT, "reports")
    os.makedirs(out, exist_ok=True)
    txt = os.path.join(out, "ss_node_debug_map.txt")
    with open(txt, "w", encoding="utf-8") as f:
        f.write("画布 %s · 节点 %d (不含色带) · 连线 %d · 注册表 %d 个 key\n\n"
                % (os.path.basename(flow), len(rows), len(links), len(NODE_LOGIC)))
        f.write("%-38s %-6s %5s %-16s %-22s %s\n" % ("节点", "连线", "key", "执行函数", "函数名", "文件:行"))
        for r in sorted(rows, key=lambda x: (x["links"] or 0), reverse=True):
            f.write("%-38s %-6s %5s %-16s %-22s %s\n"
                    % (r["node"][:36], r["links"], r["key"] or "-", r["fn"] or "-", r["fn"] or "-", r["loc"] or "-"))
        f.write("\n无执行注册: %d %s\n孤岛(连线=0): %d %s\n"
                % (len(no_reg), no_reg[:8], len(island), island[:8]))
    with open(os.path.join(out, "ss_node_debug_map.json"), "w", encoding="utf-8") as jf:
        json.dump({"flow": flow, "rows": rows, "no_reg": no_reg, "island": island,
                   "n_links": len(links)}, jf, indent=1, ensure_ascii=False)
    print("节点 %d · 连线 %d · 无注册 %d · 孤岛 %d\n落盘: %s"
          % (len(rows), len(links), len(no_reg), len(island), txt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
