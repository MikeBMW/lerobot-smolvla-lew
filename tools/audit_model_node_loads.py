#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_model_node_loads.py — 状态空间「模型节点 ↔ 真实加载代码」审计 (可 VSCode 打开)

老倪要求: 「我要看到在状态空间里的所有模型相关节点, 有模型加载 load 的实际代码, 我可以从 vscode 里打开」

做法:
  1. 读画布 flows/state_space_obs.json → 取 type=model 的节点 (含 params.source / source_symbol)
  2. 把 symbol 解析成**真实行号** (在源文件里定位 `class X` / `def X` / 赋值)
  3. 在源文件里扫描**模型加载类调用** (from_pretrained / torch.load / ultralytics YOLO( /
     AutoModel* / hf_hub_download / stable_worldmodel / INTACT load_pretrained / np.load 权重 ...)
  4. 输出: 每节点的 file:line (可直接 `code -g file:line` 打开) + 命中的加载 API + 代码片段
  5. 落盘 reports/model_nodes_load_map.json + 人类可读 docs/design/space_model_nodes_load_map.md

判据: 文件存在 + symbol 命中 + ≥1 条真实加载调用 (否则标 ❌ 并在报告里点出来, 不粉饰)
"""
from __future__ import annotations
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANVAS = os.path.join(ROOT, "flows", "state_space_obs.json")
OUT_JSON = os.path.join(ROOT, "reports", "model_nodes_load_map.json")
OUT_MD = os.path.join(ROOT, "docs", "design", "space_model_nodes_load_map.md")

# 模型加载类调用 (正则, 命中即记录)
LOAD_PATTERNS = [
    (r"\.from_pretrained\s*\(", "from_pretrained (HF 权重)"),
    (r"torch\.load\s*\(", "torch.load (ckpt)"),
    (r"\bYOLO\s*\(", "ultralytics YOLO(...)"),
    (r"\bAutoModel[A-Za-z]*\s*\(", "transformers AutoModel*"),
    (r"hf_hub_download\s*\(", "hf_hub_download (Hub 拉权重)"),
    (r"\bfrom_pretrained\b", "from_pretrained"),
    (r"np\.load\s*\(", "np.load (npz 权重)"),
    (r"load_pretrained\s*\(", "load_pretrained (INTACT 官方)"),
    (r"import\s+stable_worldmodel", "stable_worldmodel 导入"),
    (r"\bLeRobotDataset\b", "LeRobotDataset (HF 数据集)"),
    (r"\bONNX|onnxruntime\b", "onnxruntime"),
    (r"cv2\.dnn", "cv2.dnn"),
    (r"ultralytics", "ultralytics 导入"),
]


def resolve_symbol_line(path: str, symbol: str) -> tuple[int | None, str]:
    """把 'class X' / 'def f(' / 'VAR' 解析成真实行号 (1-based)."""
    if not symbol:
        return None, ""
    try:
        src = open(path, encoding="utf-8", errors="ignore").read().splitlines()
    except OSError:
        return None, ""
    sym = symbol.strip()
    # class X / def x
    m = re.match(r"(class|def)\s+([A-Za-z_][A-Za-z_0-9]*)", sym)
    if m:
        pat = re.compile(r"^\s*" + re.escape(m.group(1)) + r"\s+" + re.escape(m.group(2)) + r"\b")
    else:
        pat = re.compile(r"^\s*" + re.escape(sym.split("(")[0].split(" ")[0]) + r"\b")
    for i, ln in enumerate(src, 1):
        if pat.search(ln):
            return i, ln.strip()[:120]
    return None, ""


def load_calls(path: str) -> list[dict]:
    hits = []
    try:
        src = open(path, encoding="utf-8", errors="ignore").read().splitlines()
    except OSError:
        return hits
    for i, ln in enumerate(src, 1):
        s = ln.strip()
        if s.startswith("#"):
            continue
        for rx, label in LOAD_PATTERNS:
            if re.search(rx, ln):
                hits.append({"line": i, "api": label, "code": s[:150]})
                break
    return hits


def main() -> int:
    d = json.load(open(CANVAS, encoding="utf-8"))
    nodes = [n for n in d.get("nodes", [])
             if n.get("type") == "model" and (n.get("params") or {}).get("source")]
    rows = []
    missing = []
    for n in nodes:
        p = n["params"]
        src_rel = str(p.get("source", "")).strip()
        sym = str(p.get("source_symbol", "")).strip()
        abspath = os.path.join(ROOT, src_rel)
        exists = os.path.isfile(abspath)
        line, decl = (None, "")
        calls = []
        if exists:
            line, decl = resolve_symbol_line(abspath, sym)
            calls = load_calls(abspath)
        ok = bool(exists and (line or not sym) and calls)
        if not ok:
            missing.append({"node": n["id"], "name": n.get("name"), "source": src_rel,
                            "symbol": sym, "exists": exists, "line": line, "n_load_calls": len(calls)})
        rows.append({
            "node_id": n["id"], "name": n.get("name"), "source": src_rel, "symbol": sym,
            "exists": exists, "line": line, "decl": decl,
            "vscode": (f"{src_rel}:{line}" if line else src_rel),
            "load_calls": calls[:6], "n_load_calls": len(calls), "ok": ok,
        })
    rows.sort(key=lambda r: (not r["ok"], r["node_id"]))
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    json.dump({"canvas": os.path.relpath(CANVAS, ROOT), "n_nodes": len(rows),
               "n_ok": sum(1 for r in rows if r["ok"]), "rows": rows},
              open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    lines = ["# 状态空间 · 模型节点 ↔ 真实加载代码 对照表",
             "",
             f"来源: `{os.path.relpath(CANVAS, ROOT)}` (type=model 节点) · 审计器 `tools/audit_model_node_loads.py`",
             f"结论: **{sum(1 for r in rows if r['ok'])}/{len(rows)} 个模型节点可定位到真实加载代码**"
             + (f" · 缺口 {len(missing)} 个(见文末)" if missing else " · 无缺口"),
             "",
             "打开方式: VSCode 里 `Ctrl+P` 输入 `文件:行号` 即可直达; 或命令行 `code -g <相对路径>:<行>`", "",
             "| 节点 | 源码 (VSCode 可开) | 符号 | 命中加载调用 |", "|---|---|---|---|"]
    for r in rows:
        apis = " · ".join(sorted({c["api"] for c in r["load_calls"]})) or "—"
        mark = "" if r["ok"] else " ❌"
        lines.append(f"| {r['name']}{mark} | `{r['vscode']}` | `{r['symbol'] or '—'}` | {apis} |")
    if missing:
        lines += ["", "## ❌ 缺口 (需修)", ""]
        for m in missing:
            why = []
            if not m["exists"]:
                why.append("文件不存在")
            if m["line"] is None:
                why.append("符号未命中")
            if m["n_load_calls"] == 0:
                why.append("文件内无模型加载调用")
            lines.append(f"- `{m['node']}` {m['name']} → `{m['source']}` ({'·'.join(why)})")
    lines += ["", "## 明细 (每节点的加载调用行)", ""]
    for r in rows:
        lines.append(f"### {r['node_id']} · {r['name']}")
        lines.append(f"- 入口: `{r['vscode']}`" + (f"  ← `{r['decl']}`" if r["decl"] else ""))
        for c in r["load_calls"]:
            lines.append(f"- L{c['line']} [{c['api']}] `{c['code']}`")
        lines.append("")
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"✅ 审计 {len(rows)} 个模型节点 · 可定位 {sum(1 for r in rows if r['ok'])} · 缺口 {len(missing)}")
    for r in rows:
        apis = ",".join(sorted({c["api"] for c in r["load_calls"]}))[:44]
        print(f"  {'✅' if r['ok'] else '❌'} {r['node_id']:>12} {r['name'][:26]:26s} {r['vscode'][:52]:52s} {apis}")
    print(f"   → {os.path.relpath(OUT_JSON, ROOT)} · {os.path.relpath(OUT_MD, ROOT)}")
    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())
