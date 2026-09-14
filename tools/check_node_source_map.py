#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔍 画布节点「右键 → 打开 VSCode」逐节点体检

老倪: "DiT 的右键怎么没有进入源代码呢?" —— 右键定位有**三条路**, 任何一条断都会表现为"没跳进源码":
  ① 节点 `params.source` (+ 可选 `params.source_symbol`) —— 相对路径按**仓库根**解析;
  ② 兜底: `match_node(节点名)` → 语义 key → `_EXTERNAL_LOC[key]` (真实外部源码) 或 NODE_LOGIC 自身 (node_logic.py);
  ③ 都没有 → 只能打开工程根 → 用户观感 = "没进源码"。

本脚本逐节点报: 走哪条路 · 定位到哪个文件哪一行 · 该文件/符号是否真实存在,
并把"落到 GUI 自身 (node_logic.py) 而非模型实现"的节点单独标出来 (这类最容易被误认为坏了)。

用法: python3 tools/check_node_source_map.py [--only 关键词] [--verbose]
退出码 0 = 所有"声明了源码"的节点都能定位。
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
import node_logic as nl                                     # noqa: E402  (无 PyQt 依赖, headless 可导入)

FLOW = os.path.join(ROOT, "flows", "state_space_obs.json")


def _find_symbol(path, sym):
    if not sym:
        return None
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            for i, ln in enumerate(f, 1):
                if ln.lstrip().startswith(sym):
                    return i
    except OSError:
        return None
    return None


def resolve(node):
    """→ (via, path, line, note) —— 与 GUI open_in_vscode 的判定顺序保持一致:
    ① params.source (支持"路径 · 符号"/"路径 符号"/"路径 --flag" 描述式写法) → 失败/只落到 GUI 自身则继续;
    ② match_node(节点名) → _EXTERNAL_LOC/真实外部实现 → 优先非 GUI 自身的候选。
    """
    p = dict(node.get("params") or {})
    src, sym = str(p.get("source") or ""), str(p.get("source_symbol") or "")
    gui_self = os.path.abspath(nl.__file__)
    cand = None
    note = ""
    if src:
        parts = [x.strip() for x in src.replace("·", " ").split() if x.strip()]
        head = parts[0] if parts else ""
        sym2 = sym or (parts[1] if len(parts) > 1 and not parts[1].startswith("--") else "")
        if head and not head.startswith("--"):
            full = head if os.path.isabs(head) else os.path.join(ROOT, head)
            if os.path.isfile(full):
                ln = _find_symbol(full, sym2)
                if os.path.abspath(full) == gui_self:
                    note = "params.source 指向 GUI 自身 (继续找真实实现)"
                else:
                    return "params.source", full, ln, ("" if not sym2 or ln else f"符号 '{sym2}' 未找到")
            else:
                note = f"params.source 不是文件 ({head})"
        else:
            note = f"params.source 不是路径 ({src[:40]})"
    key = nl.match_node(node.get("name") or "")
    if key:
        lp, ln, _m = nl.get_node_location(key)
        if lp and os.path.exists(lp):
            if os.path.abspath(lp) == gui_self:
                return f"registry:{key}", lp, ln, "⚠️ 落到 GUI 自身 node_logic.py (该节点无真实外部实现映射)"
            return f"registry:{key}", lp, ln, note
    return "", "", None, note or "无可用源码映射 → 只能打开工程根"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    d = json.load(open(FLOW, encoding="utf-8"))
    bad = gui_self = ok = 0
    print(f"画布: {os.path.relpath(FLOW, ROOT)} · 节点 {len(d['nodes'])} 个")
    for n in d["nodes"]:
        if n.get("type") == "row_bg":
            continue
        name = (n.get("name") or "")[:52]
        if a.only and a.only not in name:
            continue
        via, path, line, note = resolve(n)
        mark = "✅" if path else "❌"
        if path:
            ok += 1
        else:
            bad += 1
        if "GUI 自身" in note:
            gui_self += 1
        if path or a.verbose or a.only:
            loc = f"{os.path.relpath(path, ROOT)}:{line or 1}" if path else "(无)"
            print(f"  {mark} {n.get('id','?'):16s} {name:54s} {via or '—':28s} {loc} {note}")
    print(f"\n可定位 {ok} · 不可定位 {bad} · 落到 GUI 自身 {gui_self}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
