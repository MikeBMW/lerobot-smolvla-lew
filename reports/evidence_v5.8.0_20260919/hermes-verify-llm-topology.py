#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hermes-verify-llm-topology.py — 验收: 大模型层拓扑 + 环境输入 + 工程记忆→总装同步

断言:
  ① 技能编排器能拿到**环境输入** (环境帧来源/帧龄 或 如实报缺)
  ② 任务规划器能读到 场景/总装 上下文 (取不到时明确写"仅用指令文本")
  ③ 工程记忆节点真读文件并同步进总装 (macro_memory.engineering, 回读校验)
  ④ 画布: 大模型层每个节点都有入线 (除 数据源/工程记忆 两个源节点) + 无悬空节点
"""
import json
import os
import sys

REPO = "/home/ubuntu/lerobot-smolvla-lew"
sys.path.insert(0, os.path.join(REPO, "tools", "gui"))
sys.path.insert(0, os.path.join(REPO, "src"))

import node_logic as nl                                                          # noqa: E402

print("── ① 技能编排器 (环境输入) ──")
logs = []
ok = nl.node_ss_skill({"log": logs.append, "params": {}, "name": "🛠 技能编排器 (LLM)", "root": REPO})
for ln in logs[:6]:
    print("   ", ln)
print(f"   返回 {ok}")

print("\n── ② 任务规划器 (上下文) ──")
logs2 = []
ok2 = nl.node_ss_llm({"log": logs2.append, "params": {"instruction": "把 800G 光模块插入 1 号位"},
                       "name": "🧠 任务规划器 (LLM)", "root": REPO})
for ln in logs2[:5]:
    print("   ", ln)

print("\n── ③ 工程记忆 → 总装记忆 ──")
logs3 = []
ok3 = nl.node_ss_eng_mem({"log": logs3.append, "params": {}, "name": "📚 工程记忆 · 技能与经验库", "root": REPO})
for ln in logs3:
    print("   ", ln)
st = json.load(open(os.path.join(REPO, "data", "macro_memory.json"), encoding="utf-8"))
eng = st.get("engineering") or {}
print(f"   回读: macro_memory.engineering 文件条目 {len(eng.get('files') or [])} · "
      f"fp={eng.get('fingerprint')} · llm={eng.get('llm')} · 其它键保留={sorted(set(st) - {'engineering'})}")

print("\n── ④ 画布拓扑 (大模型层) ──")
d = json.load(open(os.path.join(REPO, "flows", "state_space_obs.json"), encoding="utf-8"))
nodes = {n["id"]: n for n in d["nodes"]}
din = {i: 0 for i in nodes}
dout = {i: 0 for i in nodes}
for l in d["links"]:
    if l["f"] in dout:
        dout[l["f"]] += 1
    if l["t"] in din:
        din[l["t"]] += 1
llm_row = ["ssllm_in", "n_eng_mem", "ss_mem_share", "ssreason", "ssskill", "ssllm",
           "n_mem_links", "n_intent_direct", "n_intent_bundle", "n_skill_dict"]
for i in llm_row:
    print(f"   {i:16s} in={din[i]:2d} out={dout[i]:2d}  {nodes[i]['name'][:30]}")
no_in = [i for i, n in nodes.items() if n.get("type") != "row_bg" and din[i] == 0]
print(f"   入线为 0 的节点: {[(nodes[i]['name'][:16], dout[i]) for i in no_in]}")
floating = [i for i, n in nodes.items() if n.get("type") != "row_bg" and din[i] == 0 and dout[i] == 0]
print(f"   完全悬空: {floating or '无 ✓'}")

ok_all = True
for name, cond in [("①编排器有环境输入", "环境" in "".join(logs) or "环境数据缺" in "".join(logs)),
                   ("②规划器有上下文", any("规划上下文" in x for x in logs2)),
                   ("③工程记忆同步", bool(ok3) and bool(eng.get("fingerprint"))),
                   ("④无悬空节点", not floating and len(no_in) <= 2)]:
    print(f"   {'✅' if cond else '❌'} {name}")
    ok_all &= bool(cond)
print("\n" + ("✅ 大模型层拓扑验收通过" if ok_all else "❌ 有断言未过"))
sys.exit(0 if ok_all else 1)
