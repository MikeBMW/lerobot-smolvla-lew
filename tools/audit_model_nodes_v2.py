#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_model_nodes_v2.py — 状态空间模型清单: 节点 ↔ 加载代码 ↔ 权重文件 (三段式证据)

老倪要求: 「所有模型相关节点, 有模型加载 load 的实际代码, 我可以从 vscode 里打开」

与 v1 的区别: v1 把"计算类节点"(流形/技能/可视化)也要求有 load 调用 → 假阴性一片。
v2 分三类, 各按各的判据:
  A. NN 模型节点  : 必须 (文件存在 + 符号命中 + 文件内有加载/推理调用 + **权重文件在盘**)
  B. 计算/技能节点: 必须 (文件存在 + 符号命中) — 无权重可言
  C. 其他模型节点: 只要求可定位

输出: reports/model_nodes_v2.json + docs/design/space_model_nodes_load_map.md (覆盖 v1 产物)
"""
from __future__ import annotations
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANVAS = os.path.join(ROOT, "flows", "state_space_obs.json")
OUT_JSON = os.path.join(ROOT, "reports", "model_nodes_v2.json")
OUT_MD = os.path.join(ROOT, "docs", "design", "space_model_nodes_load_map.md")

# 真·NN 模型节点 (有权重、要加载) —— 逐个点名, 并给出权重候选 glob
NN_NODES = {
    "ssyolo":       (["models/yolo_peg_live.pt", "models/yolo*.pt"], "YOLO 检测器"),
    "ssvlm":        (["**/SmolVLM*", "~/.cache/huggingface/**/SmolVLM*"], "SmolVLM 视觉编码器"),
    "ssdec":        (["outputs/train/smolvla_lew_sim/**/*.safetensors", "outputs/train/**/model.safetensors"], "Flow-Matching Action Head (DiT)"),
    "ssmani_exp":   (["models/l4_mani_predictor_v*.pt"], "流形专家预测器 (JEPA)"),
    "ssff":         (["models/ss_left_brain*.npz"], "前馈加速器 MLP"),
    "ssintact":     (["/home/ubuntu/stable-wm-cache/checkpoints/intact_l4_current/weights.pt"], "INTACT L4 策略"),
    "swintact":     (["/home/ubuntu/stable-wm-cache/checkpoints/intact_goal_optical_insert_v6*_s3072/weights_epoch_1.pt"], "INTACT 插拔策略(本域微调)"),
    "n_vlm_llm":    ([], "Qwen-VL 场景理解 (本地/远端 VLM)"),
    "n_dsvl":       ([], "DeepSeek-VL 场景理解 (API)"),
    "sspred":       ([], "先验动力学预测器"),
    "ssmani_c":     ([], "接触流形"),
    "ssmani_p":     ([], "性能流形"),
}
COMPUTE_NODES = {"ssc", "sssk1", "sssk2", "sssk3", "sssk4", "sssk5", "sssk6", "sssk7", "sssk8",
                 "ssskill", "ssllm", "ssreason", "sscalib", "sslat", "ssinnov", "ssbypv", "ssz700",
                 "ssff_hist", "ssintact_dec"}

LOAD_PATTERNS = [
    (r"\.from_pretrained\s*\(", "from_pretrained"),
    (r"torch\.load\s*\(", "torch.load"),
    (r"\bYOLO\s*\(", "ultralytics YOLO()"),
    (r"\bAutoModel[A-Za-z]*\s*\(", "AutoModel*"),
    (r"hf_hub_download\s*\(", "hf_hub_download"),
    (r"np\.load\s*\(", "np.load"),
    (r"load_pretrained\s*\(", "load_pretrained"),
    (r"import\s+stable_worldmodel", "stable_worldmodel"),
    (r"\bONNX|onnxruntime\b", "onnxruntime"),
    (r"\brequests\.post\b|\bopenai\b", "远端 API 调用"),
]


def resolve_line(path: str, symbol: str):
    if not symbol:
        return None, ""
    try:
        src = open(path, encoding="utf-8", errors="ignore").read().splitlines()
    except OSError:
        return None, ""
    m = re.match(r"(class|def)\s+([A-Za-z_][A-Za-z_0-9]*)", symbol.strip())
    if m:
        pat = re.compile(r"^\s*" + m.group(1) + r"\s+" + re.escape(m.group(2)) + r"\b")
    else:
        pat = re.compile(r"^\s*" + re.escape(symbol.split("(")[0].split(" ")[0]) + r"\b")
    for i, ln in enumerate(src, 1):
        if pat.search(ln):
            return i, ln.strip()[:110]
    return None, ""


def calls_in(path: str):
    out = []
    try:
        src = open(path, encoding="utf-8", errors="ignore").read().splitlines()
    except OSError:
        return out
    for i, ln in enumerate(src, 1):
        if ln.strip().startswith("#"):
            continue
        for rx, label in LOAD_PATTERNS:
            if re.search(rx, ln):
                out.append({"line": i, "api": label, "code": ln.strip()[:140]})
                break
    return out


def glob_any(pats):
    import glob as _g
    for p in pats:
        hit = sorted(_g.glob(p if os.path.isabs(p) else os.path.join(ROOT, p), recursive=True))
        if hit:
            return hit
    return []


def main() -> int:
    d = json.load(open(CANVAS, encoding="utf-8"))
    nodes = {n["id"]: n for n in d.get("nodes", [])}
    rows = []
    for nid, n in nodes.items():
        if n.get("type") != "model":
            continue
        p = n.get("params") or {}
        src = str(p.get("source", "")).strip()
        sym = str(p.get("source_symbol", "")).strip()
        absp = os.path.join(ROOT, src)
        ex = os.path.isfile(absp)
        line, decl = resolve_line(absp, sym) if ex else (None, "")
        calls = calls_in(absp) if ex else []
        kind = "A_nn" if nid in NN_NODES else ("B_compute" if nid in COMPUTE_NODES else "C_other")
        wfiles = glob_any(NN_NODES[nid][0]) if nid in NN_NODES else []
        ok = bool(ex and (line or not sym) and (calls or kind != "A_nn"))
        if kind == "A_nn":
            ok = ok and bool(wfiles)
        rows.append({"node_id": nid, "name": n.get("name"), "kind": kind, "source": src, "symbol": sym,
                     "exists": ex, "line": line, "decl": decl,
                     "vscode": f"{src}:{line}" if line else src,
                     "load_calls": calls[:8], "n_calls": len(calls),
                     "weights": wfiles[:4], "n_weights": len(wfiles),
                     "role": NN_NODES.get(nid, ("", ""))[1], "ok": ok})
    rows.sort(key=lambda r: (r["kind"], not r["ok"], r["node_id"]))
    json.dump({"canvas": os.path.relpath(CANVAS, ROOT), "rows": rows,
               "n_ok": sum(1 for r in rows if r["ok"]), "n": len(rows)},
              open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    nn = [r for r in rows if r["kind"] == "A_nn"]
    cp = [r for r in rows if r["kind"] != "A_nn"]
    L = ["# 状态空间 · 模型节点 ↔ 加载代码 ↔ 权重 (v5.11.4 审计)",
         "",
         "老倪: 「所有模型相关节点, 有模型加载 load 的实际代码, 我可以从 vscode 里打开」",
         "",
         f"- **A. 神经网络模型节点**: {sum(1 for r in nn if r['ok'])}/{len(nn)} 全部可定位到加载代码 + 权重在盘",
         f"- **B/C. 计算/技能/其他模型节点**: {sum(1 for r in cp if r['ok'])}/{len(cp)} 可定位 (无权重可言)",
         "",
         "VSCode 打开: `Ctrl+P` 输入 `相对路径:行号`, 或终端 `code -g <相对路径>:<行号>`", "",
         "## A. 神经网络模型 (要加载权重)", "",
         "| 节点 | 角色 | 代码入口 (VSCode 可开) | 命中加载调用 | 权重文件 |",
         "|---|---|---|---|---|"]
    for r in nn:
        apis = " · ".join(sorted({c["api"] for c in r["load_calls"]})) or "—"
        w = " · ".join(os.path.relpath(x, ROOT) if x.startswith(ROOT) else x for x in r["weights"]) or "—"
        L.append(f"| {r['node_id']} {r['name']} | {r['role']} | `{r['vscode']}` | {apis} | `{w}` |")
    L += ["", "## B/C. 计算 / 技能 / 其他", "", "| 节点 | 代码入口 (VSCode 可开) | 符号 |", "|---|---|---|"]
    for r in cp:
        L.append(f"| {r['node_id']} {r['name']} | `{r['vscode']}` | `{r['symbol'] or '—'}` |")
    L += ["", "## 加载调用明细", ""]
    for r in rows:
        if not r["load_calls"]:
            continue
        L.append(f"### {r['node_id']} · {r['name']}  (`{r['vscode']}`)")
        for c in r["load_calls"]:
            L.append(f"- L{c['line']} [{c['api']}] `{c['code']}`")
        L.append("")
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(L))

    print(f"✅ 模型节点 {len(rows)} 个 · 可定位 {sum(1 for r in rows if r['ok'])} · 缺口 {sum(1 for r in rows if not r['ok'])}")
    print(f"   A. NN 模型: {len(nn)} 个 → {sum(1 for r in nn if r['ok'])} OK")
    for r in nn:
        w = (os.path.relpath(r["weights"][0], ROOT) if r["weights"] and r["weights"][0].startswith(ROOT) else (r["weights"][0] if r["weights"] else "无权重"))
        print(f"      {'✅' if r['ok'] else '❌'} {r['node_id']:>12} {r['role'][:22]:22s} {r['vscode'][:46]:46s} w={w[:34]}")
    print(f"   → {os.path.relpath(OUT_MD, ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
