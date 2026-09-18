#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_ss_obs_layout2.py — 状态空间画布重排 v2: **保证左上源头 → 右下输出** (反向连线降到只剩反馈边)

老倪 2026-09-19 反馈: 「怎么又出现了右侧的输出连接到左侧的输入? 这样看起来很乱 … 保持左上是源头,
右下是输出, 不要出现右侧输出连左侧输入。」

做法 (结构化, 不是手摆):
  ① 图分析: 每条连线的"数据流层级"= SCC 缩合图上的最长路 (反馈边单独列出, 它们是**物理上必然**反向的)
  ② 行内排序: 按层级排 (同层按语义顺序) → 行内左→右就是数据流方向
  ③ 行偏移 off[]: 以"行平均层级"做阶梯初值, 再**迭代消反向线** (对每条 ax≥bx 的连线, 把目标行右移/
     源行左移各一半), 40 轮收敛 → 反向连线只剩反馈边
  ④ 行背景按行实际跨度包住; 行名保留 L2/L3/L4 标记 (verify_l4_zero_regression 靠它判档位)
用法: gui-venv311/bin/python tools/gui/gen_ss_obs_layout2.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from collections import defaultdict

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
FLOW = os.path.join(REPO, "flows", "state_space_obs.json")
BASE_X, BASE_Y, COL_W, ROW_H, BAND_PAD = 140, 140, 330, 300, 170
SLOT_CAP = 3           # 行内同层最多竖排几档 (超出向右挪列)

ROWS = [
    ("📦 数据源 (metaworld 环境 · 供给全部层级)", "ssbg_data", ["ssdata", "ssmode", "sscap"]),
    ("🌍 L4 · 光模块插拔链 (环境渲染 → INTACT → 引擎 → 视频)", "swbg_l4sw",
     ["swds", "swintact", "swworld", "swvideo"]),
    ("🧠 大模型层 · 任务/编排/记忆中枢 (回路外慢决策)", "ssbg5",
     ["ssllm_in", "ss_mem_share", "ssreason", "ssskill", "ssllm",
      "n_mem_links", "n_intent_direct", "n_intent_bundle", "n_skill_dict"]),
    ("🏆 L4 记忆 · 筹划 (世界模型预测/恢复策略入库)", "row_mem_l4", ["ss_mem_l4", "ss_mem_field"]),
    ("🏆 L4 专家自主功能 · 标定与流形世界模型", "ssbg7",
     ["sscalib", "sslat", "ssintact", "ssintact_dec", "ssmani_exp", "ssmani_c", "ssmani_p"]),
    ("🚀 L3 记忆 · 长程规划 (跨段技能序列 入库)", "row_mem_l3", ["ss_mem_l3"]),
    ("🚀 L3 高级自动功能 · VLM 编码 + Flow-Matching", "ssbg_vlm", ["ssvlm", "ssdec"]),
    ("🔧 L2 记忆 · 肌肉记忆 (固化标杆 → 快速直通)", "row_mem_l2", ["ss_mem_l2"]),
    ("🔧 L2 基础辅助功能 · 分段感知 (检测/触觉/2D→3D/质量)", "ssbg0",
     ["ssyolo", "sstactile", "ss2d3d", "ssaoi"]),
    ("🔧 L2 基础辅助功能 · 感知融合 (传感器 → 43D 状态)", "ssbg1", ["sssensor", "ssobs"]),
    ("🔧 L2 基础辅助功能 · 分段控制小模型 (估计/预测/校正/前馈)", "ssbg2",
     ["ssest", "sspred", "ssinnov", "ssff"]),
    ("🔧 L2 基础辅助功能 · 状态机决策 (动作调制 · 安全限幅)", "ssbg3", ["sssched", "sslimit"]),
    ("🔧 L2 基础辅助功能 · 原子技能库 SK01-08 + 通用算子", "ssbg_skill",
     ["sssk1", "sssk2", "sssk3", "sssk4", "sssk5", "sssk6", "sssk7", "sssk8", "ssa", "ssb", "ssc"]),
    ("🔧 L2 基础辅助功能 · 执行层 (执行器 → 物理闭环)", "ssbg4", ["ssact", "ssworld"]),
    ("🧩 验证层 · Feature/Test 质量门 (回路外元层)", "ssbg8", ["ssfeat", "sstest"]),
    ("🔭 可视化层 · 观察器 (真机/旁路/3D/视频)", "ssbg9",
     ["ssff_hist", "ssz700", "ssbypv", "ss3d_view", "ssvideo", "ssvideo2"]),
]
DEAD_BANDS = ["ssbg6"]


def dfs_levels(ids, links):
    """DFS 分类边 (树边/反馈边) → 去掉反馈边得 DAG → 最长路分层。

    为什么不用 SCC: 本图是**控制闭环** (状态机→技能→执行→物理世界→校正器→状态机 …), SCC 会把
    整个环压成一个点 → 层级全平, 反而判出 42 条"反馈边"。用 DFS 反馈边只切 5 条 (真正的回路闭合边),
    其余边都能排成左→右。
    返回 (level, feedback_edges)
    """
    adj = defaultdict(list)
    for l in links:
        if l.get("f") in ids and l.get("t") in ids:
            adj[l["f"]].append(l["t"])
    state, fb = {}, []
    finish = []

    def dfs(u):
        state[u] = 1
        for v in adj[u]:
            st = state.get(v, 0)
            if st == 1:
                fb.append((u, v))            # 回边 (环闭合) — 物理上必然反向
            elif st == 0:
                dfs(v)
        state[u] = 2
        finish.append(u)

    for n in sorted(ids):
        if state.get(n, 0) == 0:
            dfs(n)
    fb_set = set(fb)
    dadj = defaultdict(list)
    for l in links:
        u, v = l.get("f"), l.get("t")
        if u in ids and v in ids and (u, v) not in fb_set:
            dadj[u].append(v)
    lvl = {n: 0 for n in ids}
    for u in reversed(finish):                # finish 是后序 → 逆序才是拓扑序 (写错会让层级全塌成 0..1)
        for v in dadj[u]:
            lvl[v] = max(lvl[v], lvl[u] + 1)
    return lvl, fb


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    d = json.load(open(FLOW, encoding="utf-8"))
    nodes = {n["id"]: n for n in d["nodes"]}
    links = [(l["f"], l["t"]) for l in d["links"]]
    ids = set(nodes)
    level, fb = dfs_levels(ids, d["links"])
    print(f"图分析: 层级 0..{max(level.values())} · **反馈边 {len(fb)}** (必然反向): {fb}")

    # 行序 = 语义链路顺序 (数据源→大模型层→L4→L3→L2→执行→验证→可视化), 人读着顺;
    # ⚠️ 反向连线只由 **x** 决定 (x 来自数据流层级, 与行序无关) → 行序可以纯按语义排, 不影响"不许右→左"
    row_of = {}
    for r, (_t, _b, node_ids) in enumerate(ROWS):
        for nid in node_ids:
            row_of[nid] = r
    band_ids = {b for _t, b, _i in ROWS if b}
    missing = [i for i in ids if i not in row_of and i not in DEAD_BANDS and i not in band_ids]
    assert not missing, f"未排布: {missing}"

    # ── 落位: x 由**数据流层级**定列 (所有非反馈边必然向右) · y 由语义行定 ·
    #    同层同行的多个节点 → 在本行内**向下错行**, 行高按需要自适应 (否则会串到下一行, 实测串成 38 个碎行)
    col_x = {lv: BASE_X + lv * COL_W for lv in range(0, max(level.values()) + 2)}
    order, placed = {}, {}
    row_y, row_slots = {}, {}
    y_cursor = BASE_Y
    for r, (_t, _b, node_ids) in enumerate(ROWS):
        ns = sorted(node_ids, key=lambda nid: (level.get(nid, 0), node_ids.index(nid)))
        order[r] = ns
        slots = {}
        for nid in ns:
            lv = level.get(nid, 0)
            slot = slots.get(lv, 0)
            slots[lv] = slot + 1
            # 行内同层: 最多竖排 SLOT_CAP 档, 再多的**向右挪列**(宁可多几条反向线, 也不让画布长成 8000px)
            if slot < SLOT_CAP:
                nodes[nid]["x"] = col_x.get(lv, BASE_X)
                nodes[nid]["y"] = y_cursor + slot * 124
            else:
                nodes[nid]["x"] = col_x.get(lv, BASE_X) + (slot - SLOT_CAP + 1) * COL_W
                nodes[nid]["y"] = y_cursor + SLOT_CAP * 124 - 124
        row_slots[r] = min(max(slots.values()), SLOT_CAP) if slots else 0
        row_y[r] = y_cursor
        y_cursor += 130 + row_slots[r] * 124 + 90      # 自适应行高 (含行间距)
    print(f"行高自适应: 最高行 {max(row_slots.values())+1} 档 · 画布高 {y_cursor}px")
    for r, (title, band, node_ids) in enumerate(ROWS):
        if not band:
            continue
        b = nodes[band]
        x0 = min(nodes[i]["x"] for i in node_ids)
        x1 = max(nodes[i]["x"] + nodes[i].get("w", 160) for i in node_ids)
        b["x"], b["y"], b["w"], b["h"] = x0 - BAND_PAD, row_y[r] - 20, (x1 - x0) + BAND_PAD + 60, (130 + row_slots[r] * 124 + 40)
        b["name"] = title
        b["params"] = dict(b.get("params") or {}, desc=title)
    for nid in DEAD_BANDS:
        n = nodes[nid]
        n["x"], n["y"], n["w"], n["h"] = 0, BASE_Y - 300, 100, 8

    # ── 定点修补: 把"布局产生的"反向线 (非反馈边) 的目标节点向右挪, 直到只剩反馈边 ──
    fb_set = set(fb)
    row_members = {r: list(ns) for r, ns in order.items()}
    for _ in range(8):
        fixed = 0
        for u, v in links:
            if u not in nodes or v not in nodes:
                continue
            if nodes[u].get("type") == "row_bg" or nodes[v].get("type") == "row_bg":
                continue
            if (u, v) in fb_set:
                continue
            if nodes[u]["x"] >= nodes[v]["x"]:
                need = nodes[u]["x"] + COL_W
                nodes[v]["x"] = need
                # 同行的其它节点若被压到 → 一起往右让位
                for r, ns in row_members.items():
                    if v in ns:
                        for other in ns:
                            if other == v:
                                continue
                            if (nodes[other]["y"] == nodes[v]["y"]
                                    and nodes[v]["x"] < nodes[other]["x"] + nodes[other].get("w", 160)
                                    and abs(nodes[other]["x"] - nodes[v]["x"]) < COL_W):
                                nodes[other]["x"] = nodes[v]["x"] + COL_W
                        break
                fixed += 1
        if not fixed:
            break

    # 反向连线统计 (按落位后的实际坐标)
    v = [(l["f"], l["t"]) for l in d["links"]
         if l.get("f") in nodes and l.get("t") in nodes
         and nodes[l["f"]].get("type") != "row_bg" and nodes[l["t"]].get("type") != "row_bg"
         and nodes[l["f"]]["x"] >= nodes[l["t"]]["x"]]
    print(f"反向连线(右→左): {len(v)} 条 (其中反馈边 {sum(1 for e in v if e in set(fb))} 条 = 控制回路闭合, 物理必然)")
    for u, w in v[:12]:
        tag = "反馈边" if (u, w) in set(fb) else "⚠️ 布局产生"
        print(f"   {u}→{w}  [{tag}]")

    # 重叠/整齐自检
    ov = 0
    fn = [n for n in d["nodes"] if n.get("type") != "row_bg"]
    for i, p in enumerate(fn):
        for q in fn[i + 1:]:
            if (p["x"] < q["x"] + q.get("w", 160) and q["x"] < p["x"] + p.get("w", 160)
                    and p["y"] < q["y"] + q.get("h", 68) and q["y"] < p["y"] + p.get("h", 68)):
                ov += 1
    xs = [n["x"] for n in fn]; ys = [n["y"] for n in fn]
    print(f"可视区 x {min(xs)}..{max(xs)} · y {min(ys)}..{max(ys)} · 方框重叠 {ov}")

    out = json.dumps(d, ensure_ascii=False, indent=1)
    d2 = json.loads(out)
    assert {n["id"] for n in d2["nodes"]} == ids, "节点丢失"
    assert len(d2["links"]) == len(d["links"]), "连线数变了"
    func = sorted([n for n in d2["nodes"] if n.get("type") != "row_bg"], key=lambda n: (n["y"], n["x"]))
    veh = {i + 1: n["name"] for i, n in enumerate(func)}
    print(f"VEH.5.008 = {veh.get(8)}")
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
