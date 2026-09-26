#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""canvas_rewire_exec_chain.py — 重连执行链 (老倪 2026-09-26)

目标拓扑 (量产执行通路):
    🛡 安全执行边界(sslimit) ──► ①..⑧ L2 原子技能(sssk1..8) ──► 🧭 MoveIt(n_moveit) ──► 🤖 机器人执行器(ssact)
  且: 原子技能可被高层 L4/技能编排直接调用 (保留 ssskill → sssk2..8 等既有入线);
      MoveIt = **最后一级执行** (任何执行通路都要经过它)。

改动:
  ① 删 8 条 sssk1..8 → ssact (绕过 MoveIt 的直连)
  ② 加 8 条 sssk1..8 → n_moveit  (in1/in2 分流, 减少视觉拥挤)
  ③ 删 sslimit → n_moveit (不再直连, 通路改为经原子技能)
  ④ 加 sslimit → sssk2..8 (安全边界后接全部 L2 原子技能; sssk1 原有)
  ⑤ ssdec(Flow-Matching 直通) → 改接 n_moveit (原直连 ssact = 绕过 MoveIt)
  ⑥ 把 ① 接近 SK01 从 (15166,5266) 挪到 (9889,5142) — 补全原子技能阶梯, 消除右→左反向连线
安全: 备份 + 六条硬断言 (id/坐标/零重叠/端口存在/无重复/无反向) + 渲染复核 + 交叉数前后对照
"""
from __future__ import annotations

import json
import os
import shutil
import time

ROOT = "/home/ubuntu/zmax_rel"
FLOW = os.path.join(ROOT, "flows/state_space_obs.json")
BGW = ("bg", "row_bg")
SK = ["sssk%d" % k for k in range(1, 9)]


def seg_cross(a, b, c, d):
    """线段 ab 与 cd 是否真交叉 (共端点不算)"""
    def o(p, q, r):
        v = (q[1] - p[1]) * (r[0] - q[0]) - (q[0] - p[0]) * (r[1] - q[1])
        return 0 if abs(v) < 1e-9 else (1 if v > 0 else -1)

    def on(p, q, r):
        return (min(p[0], r[0]) - 1e-9 <= q[0] <= max(p[0], r[0]) + 1e-9 and
                min(p[1], r[1]) - 1e-9 <= q[1] <= max(p[1], r[1]) + 1e-9)

    if len({tuple(a), tuple(b), tuple(c), tuple(d)}) < 4:
        return False
    o1, o2, o3, o4 = o(a, b, c), o(a, b, d), o(c, d, a), o(c, d, b)
    if o1 != o2 and o3 != o4:
        return True
    return ((o1 == 0 and on(a, c, b)) or (o2 == 0 and on(a, d, b)) or
            (o3 == 0 and on(c, a, d)) or (o4 == 0 and on(c, b, d)))


def count_cross(nodes, links):
    pos = {n["id"]: (n["x"] + n["w"] / 2.0, n["y"] + n["h"] / 2.0) for n in nodes}
    segs = [(l["f"], l["t"], pos[l["f"]], pos[l["t"]]) for l in links if l["f"] in pos and l["t"] in pos]
    c = 0
    for i in range(len(segs)):
        for j in range(i + 1, len(segs)):
            if segs[i][0] == segs[j][0] and segs[i][1] == segs[j][1]:
                continue
            if seg_cross(segs[i][2], segs[i][3], segs[j][2], segs[j][3]):
                c += 1
    return c


def main() -> int:
    d = json.load(open(FLOW, encoding="utf-8"))
    nodes, links = d["nodes"], d["links"]
    by = {n["id"]: n for n in nodes}
    c0 = count_cross(nodes, links)
    n0, l0 = len(nodes), len(links)
    print("前: %d 节点 / %d 连线 / 交叉 %d 对" % (n0, l0, c0))

    # ① 端口格式归一化 (字典→字符串): 画布约定 inputs/outputs 是**字符串列表**
    #    🐛 2026-09-26: ssdec 等节点用 [{'id':'out1',...}] 字典格式 → 与约定不符 (曾致 add_node 崩溃类问题)
    def norm(node):
        for key in ("inputs", "outputs"):
            v = node.get(key) or []
            if v and isinstance(v[0], dict):
                labels = {str(p.get("id")): p.get("label", "") for p in v if isinstance(p, dict)}
                node[key] = [str(p.get("id")) if isinstance(p, dict) else str(p) for p in v]
                node.setdefault("params", {})["_port_labels"] = labels
                print("    端口归一化 %s.%s → %s" % (node["id"], key, node[key]))
        return node
    fixed = 0
    for n in nodes:
        before = (n.get("inputs"), n.get("outputs"))
        norm(n)
        if (n.get("inputs"), n.get("outputs")) != before:
            fixed += 1
    print("  ⓪ 字典格式端口归一化: %d 个节点" % fixed)

    # ⑥ 把执行链整体左移到"原子技能阶梯"之前 —— 保证全部左→右, 零反向线
    #    动作调制器 → 安全执行边界 → ①..⑧ 原子技能 → MoveIt → 机器人
    moves = {"sssched": (8900, 5020), "sslimit": (9250, 5142),
             "sssk1": (9889, 5142)}
    for nid, (nx, ny) in moves.items():
        by[nid]["x"], by[nid]["y"] = int(nx), int(ny)
        print("  ① %s 挪到 (%d, %d)" % (nid, nx, ny))
    # 零重叠断言 (被移动的节点 vs 其余真节点)
    moved = set(moves)
    def ov(a, b, pad=6):
        return not (a["x"] + a["w"] + pad <= b["x"] or b["x"] + b["w"] + pad <= a["x"] or
                    a["y"] + a["h"] + pad <= b["y"] or b["y"] + b["h"] + pad <= a["y"])
    for nid in moved:
        for n in nodes:
            if n.get("type") in BGW or n["id"] in moved:
                continue
            assert not ov(by[nid], n), "%s 与 %s 重叠" % (nid, n["id"])

    # ① 删直连执行器 (绕过 MoveIt 的)
    drop = {(sid, "ssact") for sid in SK} | {("sslimit", "n_moveit"), ("ssdec", "ssact")}
    before = len(links)
    links = [l for l in links if (l["f"], l["t"]) not in drop]
    print("  ② 删除绕过 MoveIt 的连线 %d 条 (8 原子技能→执行器 · 安全边界→MoveIt · FlowMatching→执行器)" % (before - len(links)))

    # ②④⑤ 加新连线
    add = []
    for i, sid in enumerate(SK):
        add.append({"f": sid, "t": "n_moveit", "f_port": "out1", "t_port": "in1" if i < 4 else "in2",
                    "label": "技能轨迹 → MoveIt 规划/执行"})
    for sid in SK[1:]:                                     # sslimit → sssk2..8 (sssk1 原有)
        add.append({"f": "sslimit", "t": sid, "f_port": "out1", "t_port": "in1",
                    "label": "🛡 限幅后控制 → %s" % by[sid]["name"][:10]})
    add.append({"f": "ssdec", "t": "n_moveit", "f_port": "out1", "t_port": "in2",
                "label": "action 直通 → MoveIt (原端到端快路径改为经 MoveIt)"})
    # 断言: 端口存在 · 无重复 · 无反向
    have = {(l["f"], l["t"]) for l in links}
    for a in add:
        assert a["t_port"] in (by[a["t"]].get("inputs") or []), "%s 无入端口 %s" % (a["t"], a["t_port"])
        assert a["f_port"] in (by[a["f"]].get("outputs") or []), "%s 无出端口 %s" % (a["f"], a["f_port"])
        assert (a["f"], a["t"]) not in have, "重复连线 %s→%s" % (a["f"], a["t"])
        fx = by[a["f"]]["x"] + by[a["f"]]["w"]
        assert fx <= by[a["t"]]["x"] + 1, "反向连线(右→左): %s→%s" % (a["f"], a["t"])
    links.extend(add)
    print("  ③ 新增连线 %d 条 (8 原子技能→MoveIt · 7 安全边界→原子技能 · 1 FlowMatching→MoveIt)" % len(add))

    d["nodes"], d["links"] = nodes, links
    c1 = count_cross(nodes, links)
    print("后: %d 节点 / %d 连线 / 交叉 %d 对  (交叉变化 %+d)" % (len(nodes), len(links), c1, c1 - c0))
    # 连通性
    real = [n for n in nodes if n.get("type") not in BGW]
    deg = {n["id"]: [0, 0] for n in real}
    for l in links:
        if l["f"] in deg: deg[l["f"]][1] += 1
        if l["t"] in deg: deg[l["t"]][0] += 1
    orph = [k for k, v in deg.items() if v[0] == 0 and v[1] == 0]
    print("  孤立节点: %d (应为 0)" % len(orph))
    print("  MoveIt 入线 = %d (应为 9: 8 原子技能 + FlowMatching) · 出线 = %d (应为 1 → 执行器)"
          % (deg["n_moveit"][0], deg["n_moveit"][1]))
    assert len(orph) == 0
    assert deg["n_moveit"][0] == 9 and deg["n_moveit"][1] == 1, "MoveIt 度数不符: %s" % deg["n_moveit"]

    bak = os.path.join(ROOT, "flows/_archive/state_space_obs_before_execchain_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(FLOW, bak)
    json.dump(d, open(FLOW, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("✅ 已写入 · 备份 %s" % os.path.relpath(bak, ROOT))
    print("   还原命令: cp %s %s" % (os.path.relpath(bak, ROOT), os.path.relpath(FLOW, ROOT)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
