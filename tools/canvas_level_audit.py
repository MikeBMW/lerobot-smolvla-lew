#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔍 canvas_level_audit.py — 画布节点/连线**档位级**验收 (①-4 后续, 老倪"逐连线对账")

为什么: 运行时对账 (canvas_link_reconcile.py) 只回答"引擎默认档每帧真发哪些通道"。
剩下双端非运行时连线要逐条回答: **它到底是"档位链里的真接入", 还是"画上去没接线"?**

关键纪律 (2026-09-24 血教训): **不要自己写解析器猜注册** —— 静态正则漏掉循环注册
(`for _skid,… : _reg(_skid, …)` → SK01-08 被误判成"缺执行注册")。本脚本**直接 import
node_logic 调真 match_node(name)**, 与 GUI 双击时的分派逐字同源。

逐节点四件套 (全部可查):
  ① 执行注册   match_node(画布节点名) → key (None = 双击无执行函数 = 缺陷)
  ② 源码映射   _EXTERNAL_LOC[key] → 文件存在? 符号在文件里? (行差仅作提示, 源码增行会漂)
  ③ 引擎接线   引擎源 (state_space_sim*.py) 是否引用 key/节点名 (信息项, 数据源/播放类节点本就不在此)
  ④ 画布连线   links 数 = 0 → 孤岛 (老倪红线)

等级:
  R1 运行时每帧 · R2 档位级真接 (注册+映射) · R3 语义容器 · R4 可视化终端 · R5 待建 · ⚠ 无执行注册
输出: reports/canvas_level_audit_<ts>.json + .md
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import time
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUI = os.path.join(ROOT, "tools", "gui")
for _p in (ROOT, os.path.join(ROOT, "src"), os.path.join(ROOT, "tools"), GUI):
    if _p not in sys.path:
        sys.path.insert(0, _p)
NODE_LOGIC_SRC = os.path.join(GUI, "node_logic.py")
FLOW = os.path.join(ROOT, "flows", "state_space_obs.json")
ENGINE_FILES = [os.path.join(GUI, "state_space_sim_real.py"), os.path.join(GUI, "state_space_sim.py"),
                os.path.join(GUI, "simulink_module.py")]

# 语义容器/标注类 (记忆·图谱·词典·丛·档位·直读 — 设计上不产运行时 io)
SEMANTIC_KEYS = {"ss_mem_share", "ss_mem_l2", "ss_mem_l3", "ss_mem_l4", "ss_mem_field",
                 "ss_mem_links", "ss_skill_dict", "ss_intent_bundle", "ss_intent_direct",
                 "ss_cap", "n_eng_mem", "n_vlm_llm", "n_dsvl", "n_board_frame"}
# 终端/交互类 (播放·波形·3D·直方图·测试/清单·模式开关) — 合法终端, 不是缺陷
TERMINAL_KEYS = {"ss_scope", "ss_video", "ss_ff_hist", "ss_3d_view", "ss_video2", "sstest",
                 "ssfeat", "sw_video", "sw_ds", "mode_switch", "ssbypv", "ssvideo", "ssff_hist"}
PENDING_KEYS = {"ss_moe", "ss_lora_l4", "ss_lora_l3"}
SOURCE_KEYS = {"ssdata", "ssz700"}


def parse_ext(src: str) -> dict:
    """`_EXTERNAL_LOC["key"] = (…, line, "sym")` → {key: (lits, line, sym)}

    🐛 2026-09-24: 原正则 `\\(([^)]*)\\)` 在**嵌套括号** (os.path.join(...)) 处截断 →
    路径字面量拿不到 → 整片 57 条映射被误判 "失效"。改为**按行累积到括号配平**。
    """
    out, lines = {}, src.splitlines()
    for i, ln in enumerate(lines):
        m = re.match(r'\s*_EXTERNAL_LOC\["([^"]+)"\]\s*=\s*(.*)$', ln)
        if not m:
            continue
        key, body, depth, j = m.group(1), m.group(2), 0, i
        while j < len(lines) and j < i + 6:                      # 最多向下看 6 行
            txt = lines[j] if j > i else body
            txt = txt.split("#")[0] if j > i else txt
            depth += txt.count("(") - txt.count(")")
            if j > i:
                body += " " + txt
            if depth <= 0 and j >= i:
                break
            j += 1
        lits = re.findall(r'"([^"]+)"', body)
        nums = re.findall(r",\s*(\d+)\s*,", body)
        out[key] = (lits, int(nums[-1]) if nums else None, lits[-1] if lits else "")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tol", type=int, default=15, help="映射行差提示阈值 (不作硬判据)")
    a = ap.parse_args()
    ts = time.strftime("%Y%m%d_%H%M%S")

    from node_logic import match_node                                   # noqa: PLC0415
    ext = parse_ext(open(NODE_LOGIC_SRC, encoding="utf-8").read())
    engsrc = "\n".join(open(p, encoding="utf-8", errors="ignore").read()
                       for p in ENGINE_FILES if os.path.isfile(p))
    flow = json.load(open(FLOW, encoding="utf-8"))
    nodes = [x for x in flow["nodes"] if x.get("type") != "row_bg"]
    deg = defaultdict(int)
    for L in flow["links"]:
        deg[L["f"]] += 1
        deg[L["t"]] += 1

    rt, rt_src = set(), "无 (先跑 tools/canvas_link_reconcile.py)"
    rj = sorted(glob.glob(os.path.join(ROOT, "reports", "canvas_link_reconcile_*.json")))
    if rj:
        d = json.load(open(rj[-1], encoding="utf-8"))
        rt = set(d.get("runtime_channels") or [])
        rt_src = os.path.basename(rj[-1])

    def rt_hit(name: str):
        for k in rt:
            kk = k.replace("🛡 安全限幅", "安全执行边界").replace("🤖 执行器", "机器人执行器")
            if kk in name or name.split(" (")[0] in k:
                return k
        return None

    rows = []
    for x in nodes:
        nid, name, typ = x["id"], str(x.get("name", "")), str(x.get("type", ""))
        key = match_node(name)                    # ← 与 GUI 双击分派同源
        rec = {"id": nid, "name": name, "type": typ, "key": key, "links": deg.get(nid, 0),
               "reg_ok": bool(key)}
        if key and key in ext:
            lits, line, sym = ext[key]
            # 🐛 2026-09-24: 原来用 glob 按 basename 搜 → 命中 gui-venv311 里同名文件 (torch planner.py)。
            #   改为**按字面量片段顺序拼绝对路径** (取最长存在后缀), 且排除 venv/site-packages。
            segs = [l for l in lits if not l.startswith(("class ", "def ", "("))][:-1] or []
            segs = [s for s in segs if not s.lstrip(".").endswith(".py") or True]
            f, dline = None, None
            py = [s for s in lits if s.endswith(".py")]
            for start in range(len(segs)):
                cand = os.path.join(ROOT, *segs[start:])
                if os.path.isfile(cand) and "venv" not in cand and "site-packages" not in cand:
                    f = cand
                    break
            if f is None and py:
                for c in reversed(py):
                    hits = [p for p in glob.glob(os.path.join(ROOT, "**", os.path.basename(c)), recursive=True)
                            if "venv" not in p and "site-packages" not in p]
                    if hits:
                        f = hits[0]
                        break
            ok_sym = False
            if f and sym:
                for i, ln in enumerate(open(f, encoding="utf-8", errors="ignore").read().splitlines(), 1):
                    if sym in ln:
                        ok_sym, dline = True, abs(i - (line or i))
                        break
            rec.update({"map_file": os.path.relpath(f, ROOT) if f else None, "map_sym": sym,
                        "map_line": line, "map_line_delta": dline,
                        "map_ok": bool(f and ok_sym), "map_line_drift": bool(dline is not None and dline > a.tol)})
        else:
            if key and key.startswith("sssk"):
                # 8 个原子技能共用一套模板 (skills/atomic_skills.py) — 无独立映射属设计如此
                rec.update({"map_file": "skills/atomic_skills.py", "map_sym": "(共享模板)",
                            "map_ok": True, "map_line_drift": False})
            else:
                rec.update({"map_file": None, "map_sym": None, "map_ok": False, "map_line_drift": False})
        rec["engine_ref"] = bool(re.search(re.escape(key) + r"\b", engsrc)) if key else False
        m = rt_hit(name)
        if m:
            rec["grade"], rec["rt_channel"] = "R1-运行时每帧", m
        elif key in SOURCE_KEYS:
            rec["grade"] = "R1-源"
        elif key in PENDING_KEYS:
            rec["grade"] = "R5-待建"
        elif key in TERMINAL_KEYS:
            rec["grade"] = "R4-终端"
        elif key in SEMANTIC_KEYS:
            rec["grade"] = "R3-语义"
        elif rec["reg_ok"]:
            rec["grade"] = "R2-档位级真接"
        else:
            rec["grade"] = "⚠-无执行注册"
        # 硬判据 (老倪红线): ① 有执行注册 ② 不孤岛。源码映射缺失只作**展示回退提示** (合法: 回退显示节点函数)
        rec["defects"] = ([d for d, bad in (("缺执行注册", not rec["reg_ok"]),
                                            ("孤岛(0 连线)", deg.get(nid, 0) == 0)) if bad])
        rec["map_note"] = ("映射有效" if rec["map_ok"] else
                           ("源码展示回退到节点函数 (无独立映射)" if rec["reg_ok"] else "—"))
        rows.append(rec)

    gc = defaultdict(int)
    for r in rows:
        gc[r["grade"]] += 1
    link_rows = []
    for L in flow["links"]:
        rf = next((x for x in rows if x["id"] == L["f"]), None)
        rtt = next((x for x in rows if x["id"] == L["t"]), None)
        if rf and rtt and not (rf["grade"].startswith("R1") and rtt["grade"].startswith("R1")):
            link_rows.append({"from": rf["name"], "to": rtt["name"],
                              "from_grade": rf["grade"], "to_grade": rtt["grade"],
                              "gap": " + ".join(sorted(set(rf["defects"] + rtt["defects"]))) or
                                     "两端设计语义/档位级 (非运行时, 合法)"})
    out = {"ts": ts, "runtime_source": rt_src, "n_nodes": len(rows), "n_links": len(flow["links"]),
           "grade_count": dict(gc), "nodes": rows, "non_runtime_links": link_rows}
    p = os.path.join(ROOT, "reports", f"canvas_level_audit_{ts}.json")
    json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    md = [f"# 画布档位级验收 — {ts}", "",
          f"- 节点 {len(rows)} · 连线 {len(flow['links'])} · 运行时通道来源 `{rt_src}`",
          f"- 等级: " + " · ".join(f"{k} {v}" for k, v in sorted(gc.items())), "",
          "## 逐节点 (执行注册用真 match_node)", "",
          "| 节点 | 类型 | 等级 | key | 注册 | 源码映射 | 行差 | 引擎引用 | 连线 | 缺陷 |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda x: (x["grade"], x["name"])):
        md.append("| {} | {} | {} | {} | {} | {} | {} | {} | {} | {} |".format(
            r["name"][:32], r["type"], r["grade"], r["key"] or "—",
            "✅" if r["reg_ok"] else "❌", (r["map_file"] or "—").split("/")[-1] if r["map_ok"] else "❌",
            r.get("map_line_delta"), "✅" if r["engine_ref"] else "—", r["links"],
            " / ".join(r["defects"]) or "—"))
    md += ["", f"## 双端非运行时连线 ({len(link_rows)} 条)", "", "| 起点 | 终点 | 等级 | 缺口 |", "|---|---|---|---|"]
    for x in link_rows:
        md.append(f"| {x['from'][:26]} | {x['to'][:26]} | {x['from_grade']} → {x['to_grade']} | {x['gap']} |")
    pm = os.path.join(ROOT, "reports", f"canvas_level_audit_{ts}.md")
    open(pm, "w", encoding="utf-8").write("\n".join(md) + "\n")

    print("节点等级: " + " · ".join(f"{k}={v}" for k, v in sorted(gc.items())))
    bad = [r for r in rows if r["grade"].startswith("⚠")]
    print(f"⚠ 无执行注册节点 {len(bad)}:")
    for r in bad:
        print(f"   [{r['type']}] {r['name'][:40]} | 连线 {r['links']} | {' / '.join(r['defects'])}")
    print(f"双端非运行时连线 {len(link_rows)} 条")
    print(f"→ {p}\n→ {pm}")
    print("LEVEL_AUDIT_DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
