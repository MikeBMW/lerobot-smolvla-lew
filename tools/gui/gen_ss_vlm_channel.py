#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_ss_vlm_channel.py — 给画布补「环境 → 📝 任务指令」数据通道 (幂等)

老倪 2026-09-19: 「增加一条从环境到 VEH.5.008 任务指令节点的数据通道, 即从仿真 metaworld 数据源,
或真机数据, 可以直接连到任务指令节点」

补三条入线 (与代码里的 _vlm_frame() 取图顺序一致 —— 画布上看得见, 代码里真有数据):
  📦 metaworld 数据源 (ssdata) → 📝 任务指令 (ssllm_in)   [仿真渲染帧]
  🧪 光模块插拔·环境渲染 (swds) → 📝 任务指令 (ssllm_in)   [引擎逐帧真图]
  🖥 Z700 真机信号 (ssz700)    → 📝 任务指令 (ssllm_in)   [真机帧/位姿通道]

安全: 备份 + 写前 json 校验 + 写后断言(节点集合不变 / 旧连线逐条不变 / 三条新线在位)
用法: gui-venv311/bin/python tools/gui/gen_ss_vlm_channel.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import os

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
FLOW = os.path.join(REPO, "flows", "state_space_obs.json")
NEW = [
    {"id": "lkvlm_in1", "f": "ssdata", "t": "ssllm_in", "f_port": "out1", "t_port": "in1",
     "label": "仿真 metaworld 渲染帧 → 场景理解 (VLM)"},
    {"id": "lkvlm_in2", "f": "swds", "t": "ssllm_in", "f_port": "out1", "t_port": "in2",
     "label": "引擎真图 → 场景理解 (VLM)"},
    {"id": "lkvlm_in3", "f": "ssz700", "t": "ssllm_in", "f_port": "out1", "t_port": "in3",
     "label": "真机帧/位姿 → 场景理解 (VLM)"},
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    d = json.load(open(FLOW, encoding="utf-8"))
    ids_before = {n["id"] for n in d["nodes"]}
    links_before = {l["id"]: json.dumps(l, sort_keys=True, ensure_ascii=False) for l in d["links"]}
    have = {l["id"] for l in d["links"]}
    add = [l for l in NEW if l["id"] not in have]
    # 入线口: 任务指令节点声明 in1..in3 (画布自解释: 每路入线什么数据)
    n = next(x for x in d["nodes"] if x["id"] == "ssllm_in")
    ports = [p for p in (n.get("inputs") or []) if p]
    for k in (1, 2, 3):
        if f"in{k}" not in ports:
            ports.append(f"in{k}")
    n["inputs"] = ports
    n["params"] = dict(n.get("params") or {},
                       desc=("大模型层·输入: MES 工单/自然语言指令 + **场景图通道** "
                             "(in1 仿真 metaworld 渲染帧 / in2 引擎真图 / in3 真机帧与位姿) → "
                             "视觉大模型(SceneVLM: 本地 Qwen2.5-VL-3B 或 API) 场景理解 → "
                             "🧠任务规划器 (planner.py); 无模型时规则回退并如实标注"))
    d["links"] = d["links"] + add
    out = json.dumps(d, ensure_ascii=False, indent=1)
    d2 = json.loads(out)
    assert {x["id"] for x in d2["nodes"]} == ids_before, "节点集合变了"
    la = {l["id"]: json.dumps(l, sort_keys=True, ensure_ascii=False) for l in d2["links"]}
    assert all(la.get(k) == v for k, v in links_before.items()), "旧连线被改动 (零回退红线)"
    assert {l["id"] for l in d2["links"]} >= {l["id"] for l in NEW}, "新线没在位"
    print(f"节点 {len(ids_before)} 不变 · 连线 {len(links_before)} → {len(d2['links'])} (+{len(add)})")
    for l in add:
        print(f"  + {l['f']} → {l['t']} [{l['t_port']}]  {l['label']}")
    if a.dry_run:
        print("(--dry-run: 未写盘)")
        return 0
    bak = FLOW + ".bak." + time.strftime("%Y%m%d_%H%M%S")
    shutil.copy2(FLOW, bak)
    open(FLOW, "w", encoding="utf-8").write(out)
    print(f"✅ 写入 {FLOW}\n   备份 {bak}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
