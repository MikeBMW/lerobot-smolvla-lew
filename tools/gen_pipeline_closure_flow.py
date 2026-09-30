#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧵 Pipeline 穿线器 —— 生成状态空间画布的闭环 flow (节点 + **真实连线**)

老倪 2026-09-23: "总体跑一下pipeline, 在状态空间画布上要有实际的连线,
              运行到执行节点要高亮显示, 所有pipeline节点跑完就是执行完成整个数据闭环"

画布契约 (tools/gui/simulink_module.py):
  node = {id,type,name,x,y,w,icon,color,params,inputs[{id,label,dtype}],outputs[...]}
  link = {id,f,t,f_port,t_port,label}
  状态 = {"pending"|"running"|"success"|"failed"} → 画布自动上色/图标
         pending #57606a · running **#00d4aa(高亮)** · success #3fb950 · failed #ff4444
"""
import json
import os
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "flows", "pipeline_closure.json")

# (id, 名称, 图标, 颜色, x, y, 层实现, 说明)
LAYERS = [
    ("l5", "L5 定方向·造数据", "🧭", "#8b5cf6", 60, 60,
     "planner.rules.builtin", "任务分解 → 阶段/技能序列 + 变体方向生成"),
    ("mem", "记忆层 五层联络", "🧠", "#f59e0b", 400, 60,
     "memory.json", "L2肌肉/L3流程/L4工作/宏观 → 跨层检索与注入"),
    ("l2", "L2 检测反馈", "👁", "#06b6d4", 740, 60,
     "detect.yolo", "YOLO 2D → 3D 反投影 → 反馈一致性"),
    ("l4", "L4 认知预测", "🌍", "#3b82f6", 1080, 60,
     "node.unified", "统一主干(SigLIP+四头) 多模型可仲裁"),
    ("l3", "L3 状态调度", "🎛", "#22c55e", 1420, 60,
     "dispatch.k_act", "动作块 → u_ff (量纲逆运算 act×K_ACT)"),
    ("exec", "执行 · 数据闭环", "♻", "#ef4444", 1760, 60,
     "closure", "真机执行 → 采集回流 → 闭环完成判定"),
]

# 端口定义
def ports():
    return ([{"id": "in1", "label": "入", "dtype": "any"}],
            [{"id": "out1", "label": "出", "dtype": "any"}])


def build():
    nodes, links = [], []
    ids = {}
    for i, (k, nm, ic, col, x, y, impl, desc) in enumerate(LAYERS):
        nid = f"np{i}{k}"
        ids[k] = nid
        ins, outs = ports()
        nodes.append({
            "id": nid, "type": "row_bg", "name": nm, "x": x, "y": y, "w": 300,
            "icon": ic, "color": col,
            "params": {"impl": impl, "desc": desc, "status": "pending", "layer": k.upper()},
            "inputs": ins, "outputs": outs,
        })
    # ★ 真实连线 (穿线): L5→MEM→L2→L4→L3→执行 ; 另加两条**联络回边**(闭环反馈)
    chain = ["l5", "mem", "l2", "l4", "l3", "exec"]
    labels = ["任务/技能", "记忆注入", "感知反馈", "认知预测", "调度指令", ""]
    for i in range(len(chain) - 1):
        links.append({
            "id": f"lp{i}", "f": ids[chain[i]], "t": ids[chain[i + 1]],
            "f_port": "out1", "t_port": "in1", "label": labels[i],
        })
    links.append({  # 闭环回边①: 执行 → 记忆 (经验回流)
        "id": "lp_back1", "f": ids["exec"], "t": ids["mem"],
        "f_port": "out1", "t_port": "in1", "label": "经验回流",
    })
    links.append({  # 闭环回边②: L4 → 记忆 (工作记忆更新)
        "id": "lp_back2", "f": ids["l4"], "t": ids["mem"],
        "f_port": "out1", "t_port": "in1", "label": "工作记忆",
    })
    return {"format": "zmax_flow/1", "version": 1,
            "name": "Z-MAX 数据闭环 Pipeline (穿线版)",
            "sim": {"by": "Hermes", "ts": time.strftime("%Y-%m-%d %H:%M:%S")},
            "nodes": nodes, "links": links}


def main():
    d = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(d, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("✅ 穿线完成 → %s" % OUT)
    print("   节点 %d · 连线 %d (含 2 条闭环回边)" % (len(d["nodes"]), len(d["links"])))
    for n in d["nodes"]:
        print("   %-2s %-18s %s" % (n["icon"], n["name"], n["params"]["impl"]))
    print("   连线:")
    nm = dict((n["id"], n["name"]) for n in d["nodes"])
    for l in d["links"]:
        print("     %-14s → %-14s  %s" % (nm[l["f"]], nm[l["t"]], l["label"]))


if __name__ == "__main__":
    main()
