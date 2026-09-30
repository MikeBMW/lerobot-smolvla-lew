#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🎯 给画布节点补 `params.source_symbol` —— 右键从"打开文件第 1 行"变成"跳到具体类/函数"

背景 (老倪 2026-09-14: "DiT 的右键怎么没有进入源代码呢?"):
  节点只写了 `params.source` = 文件路径, 没有符号 → 右键只能打开**第 1 行**;
  用户看到的是文件顶部而不是实现处, 观感 = "没进源码"。而 registry (_EXTERNAL_LOC)
  里其实已经**人工核对过**每个 key 的真实符号 (如 ssdec → class SmolVLALewActionHead)。

规则 (保守, 只在证据充分时才写):
  ① 节点有 params.source 且**是真文件**; ② 按节点名 match_node 能命中 registry key;
  ③ registry 里该 key 的**文件与 params.source 指向同一个文件**; ④ 该符号在文件里真实存在
  → 才写入 source_symbol。任何一条不满足就跳过并打印原因 (宁缺勿错)。

用法: python3 tools/fill_node_source_symbols.py [--apply]   (默认 dry-run, 只打印)
"""
import argparse
import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
import node_logic as nl                                      # noqa: E402

FLOW = os.path.join(ROOT, "flows", "state_space_obs.json")


def sym_exists(path, sym):
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            return any(ln.lstrip().startswith(sym) for ln in f)
    except OSError:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真写入 (默认只 dry-run)")
    a = ap.parse_args()
    d = json.load(open(FLOW, encoding="utf-8"))
    ext = nl._EXTERNAL_LOC                                   # noqa: SLF001
    todo, skip = [], []
    for n in d["nodes"]:
        if n.get("type") == "row_bg":
            continue
        p = n.setdefault("params", {})
        src = str(p.get("source") or "")
        if not src or p.get("source_symbol"):
            continue
        head = src.replace("·", " ").split()[0] if src.replace("·", " ").split() else ""
        full = head if os.path.isabs(head) else os.path.join(ROOT, head)
        if not (head and os.path.isfile(full)):
            skip.append((n["id"], f"source 不是文件 ({src[:36]})"))
            continue
        key = nl.match_node(n.get("name") or "")
        e = ext.get(key) if key else None
        if not e:
            skip.append((n["id"], f"registry 无 key ({key})"))
            continue
        epath, _eline, esym = e[0], e[1], (e[2] if len(e) > 2 else "")
        if os.path.abspath(epath) != os.path.abspath(full):
            skip.append((n["id"], f"registry 文件不同 ({os.path.relpath(epath, ROOT)})"))
            continue
        if not esym or not sym_exists(full, esym):
            skip.append((n["id"], f"符号不可用 ({esym!r})"))
            continue
        todo.append((n, key, full, esym))

    print(f"将补 source_symbol: {len(todo)} 个 · 跳过 {len(skip)} 个")
    for n, key, full, esym in todo:
        print(f"  ✚ {n['id']:16s} {(n.get('name') or '')[:40]:42s} [{key}] → "
              f"{os.path.relpath(full, ROOT)} :: {esym}")
    print("\n跳过明细 (宁缺勿错):")
    for i, why in skip:
        print(f"  · {i:16s} {why}")

    if not a.apply:
        print("\n(dry-run; 加 --apply 才写入)")
        return 0
    bak = FLOW + time.strftime(".bak_%Y%m%d_%H%M%S")
    shutil.copy2(FLOW, bak)
    for n, key, full, esym in todo:
        n["params"]["source_symbol"] = esym
    with open(FLOW, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)        # 与 GUI 保存格式一致
    print(f"\n✅ 已写入 {len(todo)} 个 source_symbol · 备份 {os.path.relpath(bak, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
