#!/usr/bin/env python3
"""🎛 原子技能条件库 → Simulink DAG 画布 (2026-08-09 老倪)

把 flows/atomic_skills_conditions.json (242 条件) 转成 Simulink 可加载的 DAG:
- 每大类一行: row_bg 背景行 (🎨 分类名) + 该类的条件节点 (coord_overlay)
- 每节点 = 一个原子技能条件编码 (cond_id + 技能名 + 动作 + 模态)
- 行内节点横排, 双击节点可改条件 (节点 params.encoding 已注入)

输出: flows/atomic_conditions_flow.json (load_flow_file 可加载)
"""
import json
import os

RAW = os.path.join(os.path.dirname(__file__), "atomic_skills_conditions.json")
OUT = os.path.join(os.path.dirname(__file__), "atomic_conditions_flow.json")

def build():
    conds = json.load(open(RAW, encoding="utf-8"))
    # 按大类分组 (保持原始顺序)
    from collections import OrderedDict
    by_cat = OrderedDict()
    for c in conds:
        by_cat.setdefault(c["category"], []).append(c)

    nodes = []
    links = []
    nid_seq = [0]
    def nid():
        nid_seq[0] += 1
        return f"ncond{nid_seq[0]:04d}"

    y = 0
    ROW_H = 170
    for cat, items in by_cat.items():
        # 背景行
        bg = {
            "id": nid(), "type": "row_bg", "name": f"🎨 {cat}",
            "x": -20, "y": y, "w": 3000, "h": ROW_H,
            "icon": "▤", "color": "#3a3f4b",
            "params": {"bg": "#3a5a7a", "model": cat,
                       "desc": f"背景行: {cat} ({len(items)} 条原子技能条件)"},
            "inputs": [{"id": "in1", "label": "in", "dtype": "any"}],
            "outputs": [{"id": "out1", "label": "out", "dtype": "any"}],
            "actions": [],
        }
        nodes.append(bg)
        # 条件节点 (横排)
        x = 0
        for c in items:
            mods = "+".join(c.get("modalities", [])[:3])
            node = {
                "id": nid(), "type": "coord_overlay",
                "name": f"🧩 {c['cond_id']} {c['skill_name'][:14]}",
                "x": x, "y": y + 8, "w": 180,
                "icon": "🧩", "color": "#58a6ff",
                "params": {
                    "cond_ref": c["cond_id"],
                    "skill": c["skill_name"],
                    "topic": c["topic"],
                    "action": c["action"],
                    "modalities": c.get("modalities", []),
                    "encoding": c.get("encoding", {}),
                    "gate": c.get("gate", 0.5),
                    "desc": f"🧩 {c['skill_name']} · {mods} · {c['action']}",
                },
                "inputs": [{"id": "in1", "label": "in", "dtype": "any"}],
                "outputs": [{"id": "out1", "label": "out", "dtype": "any"}],
                "actions": [],
            }
            nodes.append(node)
            links.append({"id": f"l{nid_seq[0]}", "f": bg["id"], "t": node["id"],
                          "f_port": "out1", "t_port": "in1"})
            x += 195
        y += ROW_H + 30

    flow = {
        "format": "zmax-simulink",
        "version": "1.0",
        "name": "atomic_conditions",
        "sim": {"dt": 0.01, "t_end": 10.0, "solver": "fixed-step"},
        "nodes": nodes,
        "links": links,
    }
    json.dump(flow, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"✅ 生成 DAG: {OUT}")
    print(f"   {len(nodes)} 节点 ({len(by_cat)} 背景行 + {len(nodes)-len(by_cat)} 条件) + {len(links)} 连线")
    for cat, items in by_cat.items():
        print(f"   🎨 {cat}: {len(items)} 条件")

if __name__ == "__main__":
    build()
