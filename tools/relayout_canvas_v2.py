#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📐 画布重排 v2 — 加宽 + 交叉最小化 + 反向/向上收束 (2026-09-24)

老倪 2026-09-24: "画布太挤了, 整体加宽, 中间的连线最好不要有交叉; 尽量减少从右侧向左侧的连线;
                 整体上的连线从左向右、从上向下; 简单整齐"

与 v1 (tools/relayout_canvas_forward.py) 的差别:
  v1 只做"右推"(保证前向) + 3 档 pitch 试参, **不做交叉最小化搜索** → 实测 505 交叉;
  v2 做真正的分层交叉最小化 (Sugiyama 重心法 + 多起点搜索):
    ① 断环得 DAG → rank = 最长路径 (流程层级)
    ② 行带 (row_bg) 语义不变; 行内顺序 = 搜索变量 (按前驱/后继重心排序)
    ③ 多起点 (orig id 序 + 若干随机扰动) × 多轮前后扫, 目标函数 = 直线近似交叉数
    ④ 每轮后 _repair: 保证 DAG 边严格左→右 (源右缘+MIN_CLEAR ≤ 目标左缘) + 同带不重叠
    ⑤ 参数网格 (PITCH 加宽 / GAP) 全局取最优; 最优解用贝塞尔采样精确复算交叉数
    ⑥ 行带 row_bg 自动放大包住本行节点 → 画布整体加宽
    ⑦ 反馈环边 (断环的那条) 保留并打 ↩ 标 (语义 = 回路, 不可删)
  --band-order causal: 实验模式, 把行带按因果序重排 (感知→认知→收口) 以减少"向上"边

用法:
  python3 tools/relayout_canvas_v2.py --measure                 # 纯静态体检 (不改任何坐标)
  python3 tools/relayout_canvas_v2.py                            # dry-run: 搜索 + 报前后对比
  python3 tools/relayout_canvas_v2.py --apply --pitch 480 --gap 220
  python3 tools/relayout_canvas_v2.py --band-order causal --apply   # 因果序实验
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import sys
import time
from collections import defaultdict, deque

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLOW = os.path.join(ROOT, "flows", "state_space_obs.json")
MIN_CLEAR = 220          # 渲染几何比 JSON 宽 (文字撑框) → 前置净空


def bezier(p0, p1, p2, p3, n=16):
    out = []
    for i in range(n + 1):
        t = i / n
        mt = 1 - t
        out.append((mt ** 3 * p0[0] + 3 * mt ** 2 * t * p1[0] + 3 * mt * t ** 2 * p2[0] + t ** 3 * p3[0],
                    mt ** 3 * p0[1] + 3 * mt ** 2 * t * p1[1] + 3 * mt * t ** 2 * p2[1] + t ** 3 * p3[1]))
    return out


def _o(p, q, r):
    return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])


def seg_cross(a, b, c, d):
    d1, d2, d3, d4 = _o(a, b, c), _o(a, b, d), _o(c, d, a), _o(c, d, b)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def _find_cycle(adj, ids):
    """DFS 找一个环。⚠️ 必须 sorted 迭代节点集合 —— set 的迭代顺序受字符串哈希随机化影响,
    跨进程会不同 → 断环集在两次运行间抖动 (2026-09-24 实锤: FAS 3~6 条乱跳)。"""
    color = {i: 0 for i in ids}
    stack, work = [], []
    for s in sorted(ids):
        if color[s]:
            continue
        color[s] = 1
        stack.append(s)
        work = [(s, iter(sorted(adj[s])))]
        while work:
            u, it = work[-1]
            adv = None
            for v in it:
                if color[v] == 1:
                    cyc = [v]
                    while stack and stack[-1] != v:
                        cyc.append(stack.pop())
                    cyc.reverse()
                    edges = [(cyc[k], cyc[k + 1]) for k in range(len(cyc) - 1)]
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
                work.append((adv, iter(sorted(adj[adv]))))
    return None


def break_cycles(ids, edges, labels, protected, preferred_back=()):
    """断环: 优先断语义反馈线(反馈/回流/偏好集), 保护主链。返回 (保留的DAG边, 断掉的反馈边)。"""
    adj = defaultdict(set)
    for f, t in edges:
        adj[f].add(t)
    pref = set(preferred_back)

    def prio(f, t):
        if (f, t) in protected:
            return 3
        if (f, t) in pref:
            return -1
        # ⚠️ 用**原始标签**算优先级 (剥掉我们自己打的 "↩ 反馈: " 前缀), 否则打标反噬优先级
        #    → 连续两次运行的断环集不同 = 不幂等 (2026-09-24 实锤: 3 条 ↔ 5 条来回抖)
        lab = labels.get((f, t), "").replace("↩ 反馈: ", "").replace("↩ 反馈回路", "")
        return 0 if ("反馈" in lab or "回流" in lab) else 1

    fb = []
    for _ in range(300):
        cyc = _find_cycle(adj, ids)
        if not cyc:
            break
        f, t = min(cyc, key=lambda e: (prio(*e),
                                       len(labels.get(e, "").replace("↩ 反馈: ", "").replace("↩ 反馈回路", "")),
                                       e[0], e[1]))
        adj[f].discard(t)
        fb.append((f, t))
    dags = {(f, t) for (f, t) in edges if (f, t) not in set(fb)}
    return dags, fb


class Layout:
    # 🎯 语义回流的边: 断环时**最先断**这几条 (它们本来就是"回到上游"的线, 视觉上反向是正常的)。
    # 2026-09-24 定档 (逐个都实锤过):
    #  ① sw 插拔链闭环 = 策略→引擎→渲染图像源→策略; 必须断"引擎→渲染图像源"(渲染回流),
    #     否则去断"策略→引擎"这条语义前向线, 三节点 x 顺序被拆散;
    #  ② 记忆环 = L2/L3/L4 记忆→记忆图谱→总装记忆→下发回 L2/L3/L4; 必须断"总装下发回下层"那三条
    #     (上层写回下层 = 语义反馈), 否则去断"记忆→图谱"会让图谱节点成断头。
    # ⚠️ 这里必须**显式声明**, 不能靠标签文本 (打标会反噬优先级 → 断环集在两次运行间抖动 = 不幂等)。
    PREFERRED_BACK = {("swworld", "swds"),
                      ("ss_mem_share", "ss_mem_l2"),
                      ("ss_mem_share", "ss_mem_l3"),
                      ("ss_mem_share", "ss_mem_l4")}

    def __init__(self, path):
        self.d = json.load(open(path, encoding="utf-8"))
        self.nodes = {n["id"]: n for n in self.d["nodes"]}
        self.links = self.d["links"]
        self.real = [n for n in self.d["nodes"] if n.get("type") != "row_bg"]
        self.bands = sorted([n for n in self.d["nodes"] if n.get("type") == "row_bg"], key=lambda n: n["y"])
        self.order_index = {n["id"]: i for i, n in enumerate(self.d["nodes"])}
        edges = [(L["f"], L["t"]) for L in self.links if L["f"] in self.nodes and L["t"] in self.nodes]
        self.labels = {(L["f"], L["t"]): str(L.get("label") or "") for L in self.links}
        self.protected = {("sssched", "sslimit")}
        self.dag, self.fb = break_cycles(set(self.nodes), edges, self.labels, self.protected,
                                         self.PREFERRED_BACK)
        self.fbset = set(self.fb)
        self.edges = edges
        # 行带归属
        self.group = defaultdict(list)
        for n in self.real:
            b = self.band_of(n)
            self.group[b["id"] if b else "__free__"].append(n)

    def band_of(self, n):
        """行 = **水平带**: 只按 y 判定归属 (2026-09-24 修: 原按 x+y 包含 → 行带宽度不够的节点被漏掉,
        实测原始文件就有 4 个节点落在带外 (动作调制器/安全执行边界 等), 导致行带框不住它们)。"""
        cy = n["y"] + n["h"] / 2
        best = None
        for b in self.bands:
            if b["y"] <= cy <= b["y"] + b["h"]:
                if best is None or b["h"] < best["h"]:
                    best = b
        return best

    # ── 指标 ────────────────────────────────────────────────────────────────
    def crossings(self, exact=True):
        segs = []
        for L in self.links:
            na, nb = self.nodes.get(L["f"]), self.nodes.get(L["t"])
            if not na or not nb:
                continue
            p0 = (na["x"] + na["w"], na["y"] + na["h"] / 2)
            p3 = (nb["x"], nb["y"] + nb["h"] / 2)
            if exact:
                dx = max(60, abs(p3[0] - p0[0]) * 0.45)
                segs.append(bezier(p0, (p0[0] + dx, p0[1]), (p3[0] - dx, p3[1]), p3))
            else:
                segs.append([p0, p3])
        c = 0
        for i in range(len(segs)):
            A = segs[i]
            for j in range(i + 1, len(segs)):
                B = segs[j]
                hit = False
                for k in range(len(A) - 1):
                    for m in range(len(B) - 1):
                        if seg_cross(A[k], A[k + 1], B[m], B[m + 1]):
                            hit = True
                            break
                    if hit:
                        break
                c += 1 if hit else 0
        return c

    def overlaps(self):
        n, c = self.real, 0
        for i in range(len(n)):
            for j in range(i + 1, len(n)):
                A, B = n[i], n[j]
                if (A["x"] < B["x"] + B["w"] and B["x"] < A["x"] + A["w"]
                        and A["y"] < B["y"] + B["h"] and B["y"] < A["y"] + A["h"]):
                    c += 1
        return c

    def metrics(self, exact=True):
        pos = {k: (n["x"], n["y"]) for k, n in self.nodes.items()}
        m = {"nodes": len(self.nodes), "links": len(self.links), "downright": 0, "down": 0,
             "horiz_right": 0, "horiz_left": 0, "up": 0, "left": 0, "back_dag": 0,
             "overlaps": 0, "cross": 0, "w": 0, "h": 0}
        for f, t in self.edges:
            dx, dy = pos[t][0] - pos[f][0], pos[t][1] - pos[f][1]
            if dx < 0:
                m["left"] += 1
                if (f, t) not in self.fbset:
                    m["back_dag"] += 1
            elif dy > 30 and dx > 30:
                m["downright"] += 1
            elif dy > 30:
                m["down"] += 1
            elif dy < -30:
                m["up"] += 1
            else:
                m["horiz_right"] += 1
        m["back_dag"] = sum(1 for (f, t) in self.dag if self.nodes[f]["x"] + self.nodes[f]["w"] > self.nodes[t]["x"])
        m["cross"] = self.crossings(exact)
        m["overlaps"] = self.overlaps()
        xs = [n["x"] for n in self.d["nodes"]]
        xe = [n["x"] + n["w"] for n in self.d["nodes"]]
        ys = [n["y"] for n in self.d["nodes"]]
        ye = [n["y"] + n["h"] for n in self.d["nodes"]]
        m["w"], m["h"] = max(xe) - min(xs), max(ye) - min(ys)
        return m

    # ── 层级 ────────────────────────────────────────────────────────────────
    def ranks(self):
        adj = defaultdict(list)
        indeg = {i: 0 for i in self.nodes}
        for f, t in self.dag:
            adj[f].append(t)
            indeg[t] += 1
        rank = {i: 0 for i in self.nodes}
        q = deque(sorted(i for i in self.nodes if indeg[i] == 0))
        while q:
            u = q.popleft()
            for v in adj[u]:
                rank[v] = max(rank[v], rank[u] + 1)
                indeg[v] -= 1
                if indeg[v] == 0:
                    q.append(v)
        return rank

    # ── 布局 ────────────────────────────────────────────────────────────────
    def assign(self, rank, pitch, gap, order, x_mode="grid"):
        for gid, ns in self.group.items():
            ns.sort(key=order)
            base = (min(rank[n["id"]] for n in ns) * pitch) if x_mode == "grid" else 0
            prev = None
            for n in ns:
                x = (rank[n["id"]] * pitch) if x_mode == "grid" else base
                if prev is not None:
                    x = max(x, prev + gap)
                n["x"] = x
                prev = x + n["w"]
        self.repair(rank)

    def repair(self, rank, rounds=60, gap=40):
        for _ in range(rounds):
            viol = [(f, t) for (f, t) in self.dag
                    if self.nodes[f]["x"] + self.nodes[f]["w"] + MIN_CLEAR > self.nodes[t]["x"]]
            moved = False
            for f, t in viol:
                self.nodes[t]["x"] = self.nodes[f]["x"] + self.nodes[f]["w"] + MIN_CLEAR
                moved = True
            # 同带内防重叠 (右推)
            for gid, ns in self.group.items():
                ns.sort(key=lambda n: n["x"])
                for i in range(1, len(ns)):
                    a, b = ns[i - 1], ns[i]
                    if b["x"] < a["x"] + a["w"] + gap:
                        b["x"] = a["x"] + a["w"] + gap
                        moved = True
            if not moved:
                break

    def kill_overlaps(self, rank, gap=40, rounds=40):
        """跨带残留重叠: 把右侧那个继续右推, 再修前向 (往复至 0)。"""
        for _ in range(rounds):
            hit = None
            for i in range(len(self.real)):
                for j in range(i + 1, len(self.real)):
                    A, B = self.real[i], self.real[j]
                    if (A["x"] < B["x"] + B["w"] and B["x"] < A["x"] + A["w"]
                            and A["y"] < B["y"] + B["h"] and B["y"] < A["y"] + A["h"]):
                        hit = (A, B) if B["x"] >= A["x"] else (B, A)
                        break
                if hit:
                    break
            if not hit:
                return True
            A, B = hit
            B["x"] = A["x"] + A["w"] + gap
            self.repair(rank)
        return self.overlaps() == 0

    def grow_bands(self, pad=40):
        for b in self.bands:
            ns = self.group.get(b["id"], [])
            if not ns:
                continue
            left = min(n["x"] for n in ns) - pad
            right = max(n["x"] + n["w"] for n in ns) + pad
            b["x"] = int(min(left, 0 if b["x"] <= 0 else b["x"]))
            b["w"] = int(right - b["x"])

    def solve(self, pitches, gaps, iters=5, restarts=4, seed=20260924, x_mode="grid"):
        rank = self.ranks()
        preds, succs = defaultdict(list), defaultdict(list)
        for f, t in self.dag:
            preds[t].append(f)
            succs[f].append(t)
        idx = self.order_index

        def bary(n, side):
            src = preds if side == "p" else succs
            xs = [self.nodes[q]["x"] for q in src.get(n["id"], [])]
            return (sum(xs) / len(xs)) if xs else float(rank[n["id"]] * 10000)

        best = None
        rng = random.Random(seed)
        for pitch in pitches:
            for gap in gaps:
                for r in range(restarts):
                    key = ((lambda n: (rank[n["id"]], idx[n["id"]])) if r == 0
                           else (lambda n: (rank[n["id"]], rng.random())))
                    self.assign(rank, pitch, gap, key, x_mode)
                    local = None
                    for it in range(iters):
                        side = "p" if it % 2 == 0 else "s"
                        for gid, ns in self.group.items():
                            ns.sort(key=lambda n: (bary(n, side), idx[n["id"]]))
                            base = (min(rank[n["id"]] for n in ns) * pitch) if x_mode == "grid" else 0
                            prev = None
                            for n in ns:
                                x = (rank[n["id"]] * pitch) if x_mode == "grid" else base
                                if prev is not None:
                                    x = max(x, prev + gap)
                                n["x"] = x
                                prev = x + n["w"]
                        self.repair(rank)
                        self.kill_overlaps(rank)
                        c = self.crossings(exact=False)
                        if local is None or c < local[0]:
                            local = (c, {n["id"]: n["x"] for n in self.d["nodes"]}, pitch, gap, r, it)
                    if best is None or local[0] < best[0]:
                        best = local
        for n in self.d["nodes"]:
            if n["id"] in best[1]:
                n["x"] = best[1][n["id"]]
        self.kill_overlaps(rank)
        fast = self.transpose(rank, best[2], best[3], x_mode)      # 局部搜索 (相邻交换)
        self.kill_overlaps(rank)
        self.grow_bands()
        return {"pitch": best[2], "gap": best[3], "restart": best[4], "iter": best[5],
                "cross_fast": fast, "x_mode": x_mode}

    def vspace(self, extra):
        """纵向留白: 行带自上而下重新堆叠, 每两行之间多留 extra px (节点随带平移, 行内相对位置不变)。"""
        y = 120
        for b in sorted(self.bands, key=lambda n: n["y"]):
            ns = self.group.get(b["id"], [])
            if not ns:
                b["y"] = int(y)
                y += b["h"] + 40 + extra
                continue
            top = min(n["y"] for n in ns)
            b["y"] = int(y)
            for n in ns:
                n["y"] = int(b["y"] + (n["y"] - top))
            y += b["h"] + 40 + extra

    def assign_bands(self, rank, pitch, gap, x_mode):
        """按 self.group 里各带的**列表顺序**赋 x (列表顺序 = 当前排序意图, 由搜索决定)。"""
        for gid, ns in self.group.items():
            base = (min(rank[n["id"]] for n in ns) * pitch) if x_mode == "grid" else 0
            prev = None
            for n in ns:
                x = (rank[n["id"]] * pitch) if x_mode == "grid" else base
                if prev is not None:
                    x = max(x, prev + gap)
                n["x"] = x
                prev = x + n["w"]
        self.repair(rank)

    def transpose(self, rank, pitch, gap, x_mode, passes=4):
        """相邻交换局部搜索 (Sugiyama transpose): 交换同带相邻两节点, 交叉数下降才保留。"""
        def sync_order_from_x():
            for gid, ns in self.group.items():
                ns.sort(key=lambda n: n["x"])
        sync_order_from_x()
        self.assign_bands(rank, pitch, gap, x_mode)
        cur = self.crossings(exact=False)
        for _ in range(passes):
            improved = False
            for gid, ns in list(self.group.items()):
                for i in range(len(ns) - 1):
                    ns[i], ns[i + 1] = ns[i + 1], ns[i]
                    self.assign_bands(rank, pitch, gap, x_mode)
                    self.kill_overlaps(rank)
                    c = self.crossings(exact=False)
                    if c < cur:
                        cur = c
                        improved = True
                    else:
                        ns[i], ns[i + 1] = ns[i + 1], ns[i]
                        self.assign_bands(rank, pitch, gap, x_mode)
                        self.kill_overlaps(rank)
            if not improved:
                break
        return cur

    # ── 因果序实验 (行带按 数据源→L2感知→L3→L4→L2收口→执行 重排) ──────────────
    def reorder_bands_causal(self):
        def key(b):
            nm = b.get("name", "")
            if "数据源" in nm:
                return (0, 0)
            if "分段感知" in nm:
                return (1, 0)
            if "感知融合" in nm:
                return (2, 0)
            if "L3 高级" in nm or "L3 记忆" in nm:
                return (3, 0)
            if "L4 专家" in nm or "L4 记忆" in nm or "L4 · 光模块" in nm:
                return (4, 0)
            if "大模型层" in nm:
                return (5, 0)
            if "分段控制" in nm:
                return (6, 0)
            if "状态机" in nm:
                return (7, 0)
            if "技能库" in nm:
                return (8, 0)
            if "肌肉记忆" in nm:
                return (9, 0)
            if "执行层" in nm:
                return (10, 0)
            if "验证层" in nm:
                return (11, 0)
            return (12, 0)

        ordered = sorted(self.bands, key=key)
        y = 120
        for b in ordered:
            ns = self.group.get(b["id"], [])
            if not ns:
                b["y"] = int(y)
                y += b["h"] + 46
                continue
            old_top = min(n["y"] for n in ns)
            b["y"] = int(y)
            for n in ns:                     # 节点跟行带走 (保持行内相对 y)
                n["y"] = int(b["y"] + (n["y"] - old_top))
            y += b["h"] + 46
        self.bands = ordered

    def mark_feedback(self):
        """给断环边打 ↩ 标; **并撤销**不再断环的边上的标 (否则标签反噬优先级 → 二次运行不幂等, 2026-09-24 实锤)。"""
        n = 0
        for L in self.links:
            lab = str(L.get("label") or "")
            e = (L["f"], L["t"])
            if e in self.fbset:
                if not lab.startswith("↩"):
                    L["label"] = ("↩ 反馈: " + lab) if lab else "↩ 反馈回路"
                    n += 1
            elif lab.startswith("↩ 反馈: "):
                L["label"] = lab[len("↩ 反馈: "):]
                n += 1
        return n


def run_combo(band_order, x_mode, pitch, gap, vgap, iters, restarts):
    lay = Layout(FLOW)
    if band_order == "causal":
        lay.reorder_bands_causal()
    info = lay.solve([pitch], [gap], iters=iters, restarts=restarts, x_mode=x_mode)
    lay.kill_overlaps(lay.ranks())
    if vgap:
        lay.vspace(vgap)
    marked = lay.mark_feedback()
    m = lay.metrics(exact=True)
    return lay, info, m, marked


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--measure", action="store_true")
    ap.add_argument("--band-order", default="keep", choices=["keep", "causal"])
    ap.add_argument("--x-mode", default="grid", choices=["grid", "pack"])
    ap.add_argument("--sweep", action="store_true", help="多组对照 (行序 × 排法 × 层距) 取最优")
    ap.add_argument("--pitch", type=int, default=0)
    ap.add_argument("--gap", type=int, default=200)
    ap.add_argument("--vgap", type=int, default=40, help="行带之间额外留白 px")
    ap.add_argument("--iters", type=int, default=4)
    ap.add_argument("--restarts", type=int, default=3)
    a = ap.parse_args()

    lay0 = Layout(FLOW)
    before = lay0.metrics(exact=True)
    print("=== 基线 (静态真值) ===")
    print("  " + json.dumps(before, ensure_ascii=False))
    print(f"  断环保留反馈边 {len(lay0.fb)} 条: {lay0.fb}")
    if a.measure:
        return 0

    if a.pitch:
        combos = [(a.band_order, a.x_mode, a.pitch)]
    elif a.sweep:
        combos = [(bo, xm, p) for bo in ("keep", "causal") for xm in ("grid", "pack")
                  for p in (540, 700)]
    else:
        combos = [(a.band_order, a.x_mode, 540), (a.band_order, a.x_mode, 700)]

    results = []
    for bo, xm, p in combos:
        lay, info, m, marked = run_combo(bo, xm, p, a.gap, a.vgap, a.iters, a.restarts)
        results.append((m["cross"], bo, xm, lay, info, m, marked))
        print(f"[{bo:6s}/{xm:4s}/P{p}] 交叉 {m['cross']:4d} · 右→左 {m['left']} (违反前向 {m['back_dag']}) · "
              f"向上 {m['up']} · 重叠 {m['overlaps']} · 画布 {m['w']}×{m['h']}")
    results.sort(key=lambda r: (r[0], r[5]["back_dag"], r[5]["overlaps"], -r[5]["w"]))
    c, bo, xm, lay, info, after, marked = results[0]
    print(f"\n=== 最优 = {bo}/{xm}/PITCH={info['pitch']} · 打 ↩ 标 {marked} 条 ===")
    print("  " + json.dumps(after, ensure_ascii=False))
    print(f"  ↓对比: 交叉 {before['cross']} → {after['cross']} · 右→左 {before['left']} → {after['left']} "
          f"(违反前向 {before['back_dag']} → {after['back_dag']}) · 向上 {before['up']} → {after['up']} · "
          f"重叠 {before['overlaps']} → {after['overlaps']}")
    print(f"  画布 宽 {before['w']} → {after['w']} · 高 {before['h']} → {after['h']}")

    if not a.apply:
        print("\n(dry-run; 加 --apply 写入)")
        return 0
    assert after["back_dag"] == 0, "仍有违反前向的 DAG 边, 拒绝写入"
    assert after["overlaps"] == 0, "仍方框重叠, 拒绝写入"
    assert len(lay.d["nodes"]) == before["nodes"] and len(lay.d["links"]) == before["links"]
    ids = {n["id"] for n in lay.d["nodes"]}
    bad = [(L["f"], L["t"]) for L in lay.d["links"] if L["f"] not in ids or L["t"] not in ids]
    assert not bad, f"连线端点缺失: {bad}"
    lay.d["links"] = lay.links
    bak = FLOW + time.strftime(".bak_%Y%m%d_%H%M%S")
    shutil.copy2(FLOW, bak)
    with open(FLOW, "w", encoding="utf-8") as f:
        json.dump(lay.d, f, ensure_ascii=False, indent=1)
    print(f"\n✅ 已写入 ({bo}/{xm}) · 备份 {os.path.relpath(bak, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
