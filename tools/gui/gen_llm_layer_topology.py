#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_llm_layer_topology.py — 补全「大模型层 + 记忆层」连接拓扑 (幂等, 可重跑)

老倪 2026-09-19: 「先修改大模型层的连线问题, 技能编排器怎么没有输入呢? 环境数据要输入给技能编排层
的大语言模型啊, 而且其它节点怎么都是悬浮在那呢? 你要设计好连接拓扑关系」

设计口径 (每条边都有数据含义; ✓=代码里已有真实读写, ⚙=本次新接的代码, ◦=设计态拓扑待接代码):
  环境 → 大模型层
    ① ssdata  → ssskill   环境/型号规格 (metaworld 数据源) → 技能编排        ⚙
    ② ssz700  → ssskill   真机实况 (帧+位姿) → 技能编排                     ⚙
    ③ ssobs   → ssreason  43D 状态/阶段 → 异常归因                          ⚙
    ④ sslimit → ssreason  安全否决/限幅计数 → 异常归因                      ⚙
    ⑤ ssreason→ ssskill   异常归因 → 技能修正 (编排器按现场问题改技能)       ◦
    ⑥ ssreason→ ssllm     恢复建议 → 重规划                                ✓(已有 →sssched)
  记忆 → 总装记忆节点 (用户: "当前的工程记忆要同步到大模型层的总装记忆节点")
    ⑦ ss_mem_l2 → ss_mem_share   肌肉记忆 → 总装                          ✓
    ⑧ ss_mem_l3 → ss_mem_share   流程记忆 → 总装                          ✓
    ⑨ ss_mem_l4 → ss_mem_share   筹划记忆 → 总装                          ✓
    ⑩ n_mem_links → ss_mem_share 记忆图谱 links → 总装                    ✓
    ⑪ n_eng_mem → ss_mem_share   **工程记忆 (docs/memory + 技能库) → 总装**  ⚙(新节点)
    ⑫ ss_mem_l2/3/4 → n_mem_links 三层记忆 → 记忆图谱 (建链)                ✓
  意图/技能词典层 (原先全悬空)
    ⑬ ssskill → n_skill_dict     新技能注册 → 技能词典                     ✓(代码真源 memory_graph)
    ⑭ n_skill_dict → sssched     技能 kNN 直读 → 动作调制                  ◦
    ⑮ ssintact_dec → n_intent_direct  Δz → 意图直读                        ✓
    ⑯ n_intent_direct → sssched   技能直读 (无搜索) → 动作调制             ◦
    ⑰ ssllm → n_intent_bundle     规划 → 意图四槽 (goal/from/skill/gate)   ✓
    ⑱ n_intent_bundle → ssintact_dec 意图四槽 → 解码器                     ✓
  数据源/档位/标定 (原先悬空)
    ⑲ ssdata → ssmode  环境数据源 → 训练/推理模式                          ⚙
    ⑳ ssmode → sscap   模式 → 能力档位                                    ✓
    ㉑ sscap → ssintact 档位 L4 → INTACT 策略                              ✓
    ㉒ sscap → ssvlm    档位 L3 → VLM 编码                                 ✓
    ㉓ sscap → ssff     档位 L2 → 前馈加速器                                ✓
    ㉔ ss2d3d → sscalib 检测框 → 标定层校验                                ⚙
    ㉕ sscalib → ss2d3d 标定 (内参 K/手眼/尺寸) → 3D 反投影                 ⚙
    ㉖ sscalib → sslat  几何标定 → 潜空间标定                              ✓
    ㉗ ssvlm → sslat    VLM 潜空间 → 几何/速度场标定                        ✓
    ㉘ sslat → ssmani_exp 潜空间地图 → 流形导航预测                        ✓
    ㉙ sslat → ssdec   潜空间 → 动作头条件                                 ✓
用法: gui-venv311/bin/python tools/gui/gen_llm_layer_topology.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
FLOW = os.path.join(REPO, "flows", "state_space_obs.json")

NEW_NODES = [
    {"id": "n_eng_mem", "type": "model", "name": "📚 工程记忆 · 技能与经验库",
     "x": 140, "y": 1324, "w": 300, "h": 68, "icon": "📚", "color": "#a371f7",
     "inputs": ["in1"], "outputs": ["out1"],
     "params": {
         "state_space": True, "eng_memory": True,
         "desc": ("工程记忆 = docs/memory/*.md (跨端同步记忆) + Hermes 记忆 (MEMORY/USER) + 技能库清单; "
                  "读真实文件 → 汇总条数/落盘时间 → 同步进 🧠总装记忆中枢 (顶层宏观记忆, macro_memory.uplink)"),
         "source": "src/lerobot/memory/eng_memory.py · collect/sync_to_macro",
         "source_symbol": "class EngMemory"}},
]

# (id, 源, 目标, 标签, 端口)
NEW_LINKS = [
    ("lkenv_skill1", "ssdata", "ssskill", "环境/型号规格 → 技能编排", "in1"),
    ("lkenv_skill2", "ssz700", "ssskill", "真机实况 (帧+位姿) → 技能编排", "in2"),
    ("lkrea1", "ssobs", "ssreason", "43D 状态/阶段 → 异常归因", "in2"),
    ("lkrea2", "sslimit", "ssreason", "安全否决/限幅计数 → 异常归因", "in3"),
    ("lkrea3", "ssreason", "ssskill", "异常归因 → 技能修正", "in3"),
    ("lkrea4", "ssreason", "ssllm", "恢复建议 → 重规划", "in4"),
    ("lkmem1", "ss_mem_l2", "ss_mem_share", "肌肉记忆 (固化标杆) → 总装", "in1"),
    ("lkmem2", "ss_mem_l3", "ss_mem_share", "流程记忆 (跨段序列) → 总装", "in2"),
    ("lkmem3", "ss_mem_l4", "ss_mem_share", "筹划记忆 (预测/恢复) → 总装", "in3"),
    ("lkmem4", "n_mem_links", "ss_mem_share", "记忆图谱 links → 总装", "in4"),
    ("lkmem5", "n_eng_mem", "ss_mem_share", "工程记忆 (docs/memory+技能) → 总装", "in5"),
    ("lkmem6", "ss_mem_l2", "n_mem_links", "L2 记忆 → 图谱建链", "in1"),
    ("lkmem7", "ss_mem_l3", "n_mem_links", "L3 记忆 → 图谱建链", "in2"),
    ("lkmem8", "ss_mem_l4", "n_mem_links", "L4 记忆 → 图谱建链", "in3"),
    ("lkdict1", "ssskill", "n_skill_dict", "新技能注册 → 技能词典", "in1"),
    ("lkdict2", "n_skill_dict", "sssched", "技能 kNN 直读 → 动作调制", "in6"),
    ("lkid1", "ssintact_dec", "n_intent_direct", "Δz → 意图直读", "in1"),
    ("lkid2", "n_intent_direct", "sssched", "技能直读 (无搜索) → 动作调制", "in7"),
    ("lkib1", "ssllm", "n_intent_bundle", "规划 → 意图四槽 (goal/from/skill/gate)", "in1"),
    ("lkib2", "n_intent_bundle", "ssintact_dec", "意图四槽 → 解码器", "in2"),
    ("lkmode1", "ssdata", "ssmode", "环境数据源 → 训练/推理模式", "in1"),
    ("lkmode2", "ssmode", "sscap", "模式 → 能力档位", "in1"),
    ("lkcap1", "sscap", "ssintact", "档位 L4 → INTACT 策略", "in4"),
    ("lkcap2", "sscap", "ssvlm", "档位 L3 → VLM 编码", "in1"),
    ("lkcap3", "sscap", "ssff", "档位 L2 → 前馈加速器", "in1"),
    ("lkcal1", "ss2d3d", "sscalib", "检测框/反投影 → 标定层校验", "in1"),
    ("lkcal2", "sscalib", "ss2d3d", "标定 (内参K/手眼/尺寸) → 3D 反投影", "in2"),
    ("lkcal3", "sscalib", "sslat", "几何标定 → 潜空间标定", "in1"),
    ("lkcal4", "ssvlm", "sslat", "VLM 潜空间 → 几何/速度场标定", "in2"),
    ("lkcal5", "sslat", "ssmani_exp", "潜空间地图 → 流形导航预测", "in1"),
    ("lkcal6", "sslat", "ssdec", "潜空间 → 动作头条件", "in2"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    d = json.load(open(FLOW, encoding="utf-8"))
    ids_before = {n["id"] for n in d["nodes"]}
    links_before = {l["id"]: json.dumps(l, sort_keys=True, ensure_ascii=False) for l in d["links"]}

    # ① 新增节点 (缺哪个补哪个)
    added_nodes = []
    for nn in NEW_NODES:
        if nn["id"] not in ids_before:
            d["nodes"].append(dict(nn))
            added_nodes.append(nn["id"])
    ids_now = {n["id"] for n in d["nodes"]}

    # ② 新增连线 (幂等) + 端口声明
    have = {l["id"] for l in d["links"]}
    by_id = {n["id"]: n for n in d["nodes"]}
    added = []
    for lid, f, t, label, tport in NEW_LINKS:
        if lid in have:
            continue
        assert f in ids_now and t in ids_now, f"{lid}: 端点不存在 {f}->{t}"
        d["links"].append({"id": lid, "f": f, "t": t, "f_port": "out1", "t_port": tport, "label": label})
        ports = [p for p in (by_id[t].get("inputs") or []) if p]
        if tport not in ports:
            ports.append(tport)
            by_id[t]["inputs"] = ports
        added.append(lid)

    # ③ 校验: 老节点/老连线一条不动
    out = json.dumps(d, ensure_ascii=False, indent=1)
    d2 = json.loads(out)
    assert ids_before - {n["id"] for n in d2["nodes"]} == set(), "老节点丢失"
    la = {l["id"]: json.dumps(l, sort_keys=True, ensure_ascii=False) for l in d2["links"]}
    assert all(la.get(k) == v for k, v in links_before.items()), "老连线被改动"
    print(f"节点 {len(ids_before)} → {len(d2['nodes'])} (+{len(added_nodes)}: {added_nodes})")
    print(f"连线 {len(links_before)} → {len(d2['links'])} (+{len(added)})")
    # 悬空复查
    din, dout = {i: 0 for i in ids_now}, {i: 0 for i in ids_now}
    for l in d2["links"]:
        if l["f"] in dout:
            dout[l["f"]] += 1
        if l["t"] in din:
            din[l["t"]] += 1
    fn = lambda n: n.get("type") != "row_bg"                   # noqa: E731
    float_both = [i for i, n in by_id.items() if fn(n) and din[i] == 0 and dout[i] == 0]
    no_in = [i for i, n in by_id.items() if fn(n) and din[i] == 0 and dout[i] > 0]
    print(f"仍悬空 (无进无出): {[by_id[i]['name'][:18] for i in float_both] or '无 ✓'}")
    print(f"只有输出/无输入 (源或漏接): {[(by_id[i]['name'][:18], dout[i]) for i in no_in] or '无'}")
    if a.dry_run:
        print("(--dry-run 未写盘)")
        return 0
    bak = FLOW + ".bak." + time.strftime("%Y%m%d_%H%M%S")
    shutil.copy2(FLOW, bak)
    open(FLOW, "w", encoding="utf-8").write(out)
    print(f"✅ 写入 {FLOW} (备份 {bak})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
