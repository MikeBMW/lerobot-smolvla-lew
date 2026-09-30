#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📐 状态空间画布「前向布局」重排 —— 保证每条线都是 左(源) → 右(目标)

老倪 2026-09-14: "现在的布局太容易看不清了; 不要出现右侧是输入、左侧是输出的位置; 可以增大画布的面积"

做法 (分层拓扑排布, 只动几何, 不动语义):
  1. 依赖图 = links (去掉**反馈环**边: 参与环的边天然必须有一条反向, 单独标注保留);
  2. `rank(n)` = DAG 最长路径层级 → 每个节点有个"流程层级";
  3. 节点仍留在**原来的行带**里 (保持 L2/L3/L4 语义带不变), 行内按 rank 排序后逐个右排:
     `x = max(rank * PITCH, 前一个节点右缘 + GAP)`;
  4. 迭代修正: 若有边 `a→b` 不满足 `a.右缘 < b.左缘` → 把 b 及其同行后继右推, 直到全部前向 (收敛);
  5. 行带 (row_bg) 跟着放大到刚好包住本行节点 (左右留 padding); 画布总面积自然扩大。
  6. 体检: 反向线 / 方框重叠 / 贝塞尔交叉 / 节点数与连线数零丢失。

用法:
  python3 tools/relayout_canvas_forward.py            # dry-run: 只报数
  python3 tools/relayout_canvas_forward.py --apply    # 写入 (自动备份)
"""
import argparse
import json
import os
import shutil
import sys
import time
from collections import defaultdict, deque

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLOW = os.path.join(ROOT, "flows", "state_space_obs.json")
PITCH = int(os.environ.get("RL_PITCH", "380"))     # 层级间距 (比原来 336 宽, 线更好看)
GAP = int(os.environ.get("RL_GAP", "170"))         # 同行相邻节点最小间隙
PAD = 30


def bezier(p0, p1, p2, p3, n=24):
    out = []
    for i in range(n + 1):
        t = i / n
        mt = 1 - t
        out.append((mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0],
                    mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1]))
    return out


def seg_cross(a, b, c, d):
    def o(p, q, r):
        return (q[0]-p[0])*(r[1]-p[1]) - (q[1]-p[1])*(r[0]-p[0])
    d1, d2, d3, d4 = o(a, b, c), o(a, b, d), o(c, d, a), o(c, d, b)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def _find_cycle(adj, ids):
    """DFS 找一个环, 返回构成环的边列表 (无环返回 None)。"""
    color = {i: 0 for i in ids}          # 0=白 1=灰 2=黑
    stack = []
    parent = {}
    for s in ids:
        if color[s]:
            continue
        work = [(s, iter(adj[s]))]
        color[s] = 1
        stack.append(s)
        while work:
            u, it = work[-1]
            adv = None
            for v in it:
                if color[v] == 1:                     # 回边 → 环
                    cyc = [v]
                    while stack and stack[-1] != v:
                        cyc.append(stack.pop())
                    cyc.reverse()
                    path = cyc + [v] if v == cyc[0] else cyc
                    edges = [(path[k], path[k + 1]) for k in range(len(path) - 1)]
                    return edges or [(u, v)]
                if color[v] == 0:
                    adv = v
                    break
            if adv is None:
                color[u] = 2
                work.pop()
                stack.pop()
            else:
                color[adv] = 1
                stack.append(adv)
                work.append((adv, iter(adj[adv])))
    return None


def feedback_arc_set(ids, edges, labels):
    """按**优先级**断环: 优先断语义反馈线 (标签含"反馈/回流"), **绝不**断保护边 (主链)。

    返回 (fas 列表, 每个元素 (f,t,label))。控制回路本质需要有一条反向, 关键是让反向落在
    "反馈/回流"那条线上 —— 而不是落在 调制器→安全边界 这种主链线上。
    """
    protected = {("sssched", "sslimit")}                  # 主链, 老倪点名要看清的那条
    def prio(f, t):
        lab = labels.get((f, t), "")
        if (f, t) in protected:
            return 3                                       # 最高代价 = 尽量别断
        if ("反馈" in lab) or ("回流" in lab):
            return 0                                       # 首选断这里 (语义就是回路)
        return 1
    adj = defaultdict(set)
    for f, t in edges:
        adj[f].add(t)
    fas = []
    guard = 0
    while guard < 200:
        guard += 1
        cyc = _find_cycle(adj, ids)
        if not cyc:
            break
        f, t = min(cyc, key=lambda e: (prio(*e), len(labels.get(e, ""))))
        adj[f].discard(t)
        fas.append((f, t, labels.get((f, t), "")))
    return fas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--measure", action="store_true", help="只体检当前布局, 不改坐标")
    a = ap.parse_args()
    d = json.load(open(FLOW, encoding="utf-8"))
    nodes = {n["id"]: n for n in d["nodes"]}
    orig_x = {n["id"]: n["x"] for n in d["nodes"]}     # 作者原意左右序 (稳定排序的基准)
    links = d["links"]
    edges = [(L["f"], L["t"]) for L in links if L["f"] in nodes and L["t"] in nodes]
    labels = {(L["f"], L["t"]): str(L.get("label") or "") for L in links}
    fas = feedback_arc_set(set(nodes), edges, labels)   # 按优先级断环 (优先断"反馈/回流"线)
    fb = {(f, t) for f, t, _ in fas}
    dag = [(f, t) for (f, t) in edges if (f, t) not in fb]
    # ① 层级 = 去环后 DAG 的最长路径 (层级少 → 画布不会被拉成 2 万像素宽)
    adj = defaultdict(list); indeg = {i: 0 for i in nodes}
    for f, t in dag:
        adj[f].append(t); indeg[t] += 1
    rank = {i: 0 for i in nodes}
    q = deque([i for i in nodes if indeg[i] == 0])
    while q:
        u = q.popleft()
        for v in adj[u]:
            rank[v] = max(rank[v], rank[u] + 1)
            indeg[v] -= 1
            if indeg[v] == 0:
                q.append(v)

    DO_LAYOUT = not a.measure
    if DO_LAYOUT:
      pass
    # ② 行带归属 (row_bg 几何包含)
    bands = [n for n in d["nodes"] if n.get("type") == "row_bg"]
    def band_of(n):
        cx, cy = n["x"] + n["w"] / 2, n["y"] + n["h"] / 2
        best = None
        for b in bands:
            if b["x"] <= cx <= b["x"] + b["w"] and b["y"] <= cy <= b["y"] + b["h"]:
                if best is None or b["h"] < best["h"]:
                    best = b
        return best
    group = defaultdict(list)
    for n in d["nodes"]:
        if n.get("type") == "row_bg":
            continue
        b = band_of(n)
        group[b["id"] if b else "__free__"].append(n)

    # ③ 行内按 rank 排, 逐个右排 (x = max(rank*PITCH, 前右缘+GAP))
    for gid, ns in ([] if not DO_LAYOUT else group.items()):
        ns.sort(key=lambda n: orig_x[n["id"]])
        prev_right = None
        for n in ns:
            x = rank[n["id"]] * PITCH
            if prev_right is not None:
                x = max(x, prev_right + GAP)
            n["x"] = x
            prev_right = x + n["w"]

    # ④ 迭代修正: 保证每条 DAG 边 源右缘+MIN_CLEAR <= 目标左缘
    MIN_CLEAR = 220          # 渲染几何比 JSON 宽度大 (文字撑框) → 留足净空
    for _ in range(200 if DO_LAYOUT else 0):
        viol = [(f, t) for (f, t) in dag if nodes[f]["x"] + nodes[f]["w"] + MIN_CLEAR > nodes[t]["x"]]
        if not viol:
            break
        for f, t in viol:
            tgt = nodes[t]
            tgt["x"] = nodes[f]["x"] + nodes[f]["w"] + MIN_CLEAR
            gid = next((g for g, ns in group.items() if tgt in ns), None)
            if gid:                                     # 同组内右侧全部右推, 防重叠
                ns = sorted(group[gid], key=lambda n: n["x"])
                for i, n in enumerate(ns):
                    if i == 0:
                        continue
                    prev = ns[i - 1]
                    if n["x"] < prev["x"] + prev["w"] + GAP:
                        n["x"] = prev["x"] + prev["w"] + GAP
    else:
        print("⚠️ 迭代未收敛 (仍有可能反向的边), 见下方体检")

    # ④b 消重叠: 同带内方框重叠 → 把右侧那个继续右推, 再回到 ④ 修前向 (往复至收敛)
    real = [n for n in d["nodes"] if n.get("type") != "row_bg"]
    for _ in range(80 if DO_LAYOUT else 0):
        moved = False
        for i in range(len(real)):
            for j in range(len(real)):
                if i == j:
                    continue
                A, B = real[i], real[j]
                if (A["x"] < B["x"] + B["w"] and B["x"] < A["x"] + A["w"]
                        and A["y"] < B["y"] + B["h"] and B["y"] < A["y"] + A["h"]):
                    if B["x"] >= A["x"]:
                        B["x"] = A["x"] + A["w"] + GAP
                        moved = True
        for f, t in dag:                       # 右推后可能破前向, 再修一轮
            if nodes[f]["x"] + nodes[f]["w"] + MIN_CLEAR > nodes[t]["x"]:
                nodes[t]["x"] = nodes[f]["x"] + nodes[f]["w"] + MIN_CLEAR
                moved = True
        if not moved:
            break

    # ③b 重心迭代 (Sugiyama 式): 按"前驱 x 的重心"给同行节点排序 → 少交叉; 取交叉最少的方案
    preds = defaultdict(list)
    for f, t in dag:
        preds[t].append(f)

    def _assign(grp, pitch):
        for gid, ns in grp.items():
            ns.sort(key=lambda n: orig_x[n["id"]])      # 🔒 稳定: 保持原来左右序, 只做右推
            prev_right = None
            for n in ns:
                x = rank[n["id"]] * pitch
                if prev_right is not None:
                    x = max(x, prev_right + GAP)
                n["x"] = x
                prev_right = x + n["w"]

    def _repair():
        for _ in range(200):
            viol = [(f, t) for (f, t) in dag if nodes[f]["x"] + nodes[f]["w"] + MIN_CLEAR > nodes[t]["x"]]
            if not viol:
                break
            for f, t in viol:
                nodes[t]["x"] = nodes[f]["x"] + nodes[f]["w"] + MIN_CLEAR
        realn = [n for n in d["nodes"] if n.get("type") != "row_bg"]
        for _ in range(80):
            moved = False
            for i in range(len(realn)):
                for j in range(len(realn)):
                    if i == j:
                        continue
                    A, B = realn[i], realn[j]
                    if (A["x"] < B["x"] + B["w"] and B["x"] < A["x"] + A["w"]
                            and A["y"] < B["y"] + B["h"] and B["y"] < A["y"] + A["h"]):
                        if B["x"] >= A["x"]:
                            B["x"] = A["x"] + A["w"] + GAP
                            moved = True
            for f, t in dag:
                if nodes[f]["x"] + nodes[f]["w"] + MIN_CLEAR > nodes[t]["x"]:
                    nodes[t]["x"] = nodes[f]["x"] + nodes[f]["w"] + MIN_CLEAR
                    moved = True
            if not moved:
                break

    def _crossings():
        ps = []
        for L in links:
            na, nb = nodes.get(L["f"]), nodes.get(L["t"])
            if not na or not nb:
                continue
            p0 = (na["x"] + na["w"], na["y"] + na["h"] / 2)
            p3 = (nb["x"], nb["y"] + nb["h"] / 2)
            dx = max(60, abs(p3[0] - p0[0]) * 0.45)
            ps.append(bezier(p0, (p0[0] + dx, p0[1]), (p3[0] - dx, p3[1]), p3))
        c = 0
        for i in range(len(ps)):
            for j in range(i + 1, len(ps)):
                A, B = ps[i], ps[j]
                hit = False
                for k in range(len(A) - 1):
                    for m in range(len(B) - 1):
                        if seg_cross(A[k], A[k + 1], B[m], B[m + 1]):
                            hit = True
                            break
                    if hit:
                        break
                if hit:
                    c += 1
        return c

    best = None
    for pitch in (380, 340, 300):
        for it in range(6):
            if it == 0:
                _assign(group, pitch)
            else:                                   # 重心重排: 按前驱 x 均值
                for gid, ns in group.items():
                    def key(n):
                        ps = [nodes[q]["x"] for q in preds.get(n["id"], [])]
                        return (sum(ps) / len(ps)) if ps else float(n["x"])
                    ns.sort(key=lambda n: (key(n), orig_x[n["id"]]))
                    prev_right = None
                    for n in ns:
                        x = rank[n["id"]] * pitch
                        if prev_right is not None:
                            x = max(x, prev_right + GAP)
                        n["x"] = x
                        prev_right = x + n["w"]
            _repair()
            c = _crossings()
            snap = {n["id"]: n["x"] for n in d["nodes"]}
            if best is None or c < best[0]:
                best = (c, dict(snap), pitch, it)
    for n in d["nodes"]:
        if n["id"] in best[1]:
            n["x"] = best[1][n["id"]]
    print(f"  ⚙️ 参数寻优: 最优 PITCH={best[2]} · 迭代 {best[3]} · 交叉 {best[0]}")

    # ⑤ 行带放大到包住本行节点
    for b in bands:
        if not DO_LAYOUT:
            break
        ns = group.get(b["id"], [])
        if not ns:
            continue
        left = min(n["x"] for n in ns) - PAD
        right = max(n["x"] + n["w"] for n in ns) + PAD
        b["x"], b["w"] = min(left, b["x"]), max(right, b["x"] + b["w"]) - min(left, b["x"])

    # ⑥ 体检 (含贝塞尔采样交叉数 — "看不清"的主要来源)
    back = [(f, t) for (f, t) in edges if nodes[f]["x"] + nodes[f]["w"] > nodes[t]["x"]]
    overl = 0
    real = [n for n in d["nodes"] if n.get("type") != "row_bg"]
    for i in range(len(real)):
        for j in range(i + 1, len(real)):
            A, B = real[i], real[j]
            if (A["x"] < B["x"] + B["w"] and B["x"] < A["x"] + A["w"]
                    and A["y"] < B["y"] + B["h"] and B["y"] < A["y"] + A["h"]):
                overl += 1
    paths = []
    for L in links:
        na, nb = nodes.get(L["f"]), nodes.get(L["t"])
        if not na or not nb:
            continue
        p0 = (na["x"] + na["w"], na["y"] + na["h"] / 2)
        p3 = (nb["x"], nb["y"] + nb["h"] / 2)
        dx = max(60, abs(p3[0] - p0[0]) * 0.45)
        paths.append(bezier(p0, (p0[0] + dx, p0[1]), (p3[0] - dx, p3[1]), p3))
    cross = 0
    for i in range(len(paths)):
        for j in range(i + 1, len(paths)):
            A, B = paths[i], paths[j]
            for k in range(len(A) - 1):
                for m in range(len(B) - 1):
                    if seg_cross(A[k], A[k + 1], B[m], B[m + 1]):
                        cross += 1
                        break
                else:
                    continue
                break
    xs = [n["x"] for n in d["nodes"]]; xe = [n["x"] + n["w"] for n in d["nodes"]]
    ys = [n["y"] for n in d["nodes"]]; ye = [n["y"] + n["h"] for n in d["nodes"]]
    print(f"层级 PITCH={PITCH}·GAP={GAP} · 反馈环边 {len(fb)} 条 (天然反向, 保留并标注): {sorted(fb)}")
    print(f"体检: 反向线 {len(back)} 条 (期望 = {len(fb)}) · 方框重叠 {overl} · 线交叉 {cross} · 节点 {len(nodes)} · 连线 {len(links)}")
    if back:
        for f, t in back:
            tag = "反馈环(允许)" if (f, t) in fb else "❌ 仍反向"
            print(f"   {tag}: {f} → {t}  (源右缘 {nodes[f]['x']+nodes[f]['w']} > 目标左缘 {nodes[t]['x']})")
    print(f"画布: x {min(xs)} … {max(xe)} (宽 {max(xe)-min(xs)}) · y {min(ys)} … {max(ye)} (高 {max(ye)-min(ys)})")

    if not a.apply:
        print("\n(dry-run; 加 --apply 才写入)")
        return 0
    bak = FLOW + time.strftime(".bak_%Y%m%d_%H%M%S")
    shutil.copy2(FLOW, bak)
    with open(FLOW, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 已写入前向布局 · 备份 {os.path.relpath(bak, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
