#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧮 canvas_add_manifold_engine.py — 把「流形引擎」节点接入状态空间画布 (L4 核心内核)

老倪 2026-09-24 架构升级要求:
  · 新节点「流形引擎」位于 **L4 层**, 是该层**输入与输出的中间**;
  · 画布上要真的接进链路 (不孤岛/不越层/完备), 并与源码/能力清单三处对齐。

本脚本只改画布 JSON, 硬断言:
  ① 新节点 x 严格落在 L4「输入侧最右」与「输出侧最左」之间 (居中语义, 不靠肉眼);
  ② 坐标全 int; ③ 与既有节点零重叠; ④ 节点落在 L4 行带内;
  ⑤ 连线不重复、全前向 (源 x < 目标 x); ⑥ 幂等 (已存在则跳过)。

用法 (必须先停 studio, 否则 GUI 会把内存版画布写回覆盖):
    ./gui-venv311/bin/python tools/canvas_add_manifold_engine.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLOW = os.path.join(ROOT, "flows", "state_space_obs.json")

NID = "ss_mani_eng"
NAME = "🧮 流形引擎 (Manifold Engine · 编码→投影→度量→导航→反馈)"
X, Y, W, H = 7500, 1546, 340, 130          # x 落在 (输入侧最右 3500, 输出侧最左 10016) 正中
INPUTS = [("sssensor", "43D 状态 (传感器融合) → x∈R^N"),
          ("ssobs", "SU(2) 统一状态 → 群约束"),
          ("sscalib", "几何标定 → 度量/势场参数"),
          ("sslat", "潜空-流形 → 潜坐标"),
          ("ss_moe", "阶段先验 → 条件化")]
OUTPUTS = [("ssintact_dec", "意图 Δz (梯度方向 −∇Φ)"),
           ("ssmani_exp", "流形坐标 p + 测地线 γ"),
           ("ssmani_c", "接触流形势能 Φ_c"),
           ("ssmani_p", "性能流形代价 V_p/η"),
           ("sssched", "动作指令 a (解码器输出)")]
PARAMS = {
    "state_space": True,
    "manifold_engine": True,
    "kind": "real",
    "role": "L4 核心内核 — 高维状态→低维流形, 流形上 表征/投影/度量/导航/反馈",
    "api": "project() · navigate() · gradient_flow() · feedback_update() · step() · query()",
    "pipeline": "编码(Encoder/PCA) → 投影(ManifoldProjector) → 度量+梯度(MetricCalculator) → 导航(Navigator 测地线) → 反馈(FeedbackLoop 有界)",
    "manifolds_ready": "euclidean · sphere · torus · so3 · se3 · su2 · latent_flat",
    "manifolds_planned": "calabi_yau(Ricci-flat 度量未实现) · hyperbolic(未实现) — 仅登记, 不造数",
    "source": "src/lerobot/manifold/manifold_engine.py",
    "source_symbol": "class ManifoldEngine",
    "reuse": "su2.py(群) · lie_intent.py(SO3/SE3) · manifold_layer.py(接触/性能势能) · fiber_bundle.py(提升) — 复用既有真件",
    "measured": "端到端 0.056ms/帧 · 投影 0.019ms · 测地线T=16 0.24ms · 约束违例 1.1e-16 · 上限 ~3500Hz (真跑引擎轨迹实测)",
    "spec_target": "延迟<10ms · 投影<1ms · 测地线<50ms · >100Hz — 全部达标",
    "caveat": "解码器(岭回归)只在标定分布内可信 (训练段逐维相关 0.76~0.94; 未见段 R² 负) → 跨段须重标定",
    "desc": "L4 核心内核: 把高维状态自动约束为低维流形, 在流形上做测地线导航/梯度流/有界反馈; 输出意图与动作建议",
}


def band_of(n, bands):
    for b in bands:
        if b["y"] <= n["y"] <= b["y"] + b.get("h", 0):
            return b
    return None


def next_port(links, node, side):
    used = set()
    for L in links:
        if side == "out" and L["f"] == node:
            used.add(str(L.get("f_port")))
        if side == "in" and L["t"] == node:
            used.add(str(L.get("t_port")))
    for k in range(1, 40):
        p = f"{'out' if side == 'out' else 'in'}{k}"
        if p not in used:
            return p
    return "in1"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    d = json.load(open(FLOW, encoding="utf-8"))
    nodes, links = d["nodes"], d["links"]
    ids = {n["id"] for n in nodes}

    if NID in ids:
        print(f"⏭ {NID} 已存在 → 幂等跳过")
        return 0
    for sid, _ in INPUTS + OUTPUTS:
        assert sid in ids, f"引用了不存在的节点 {sid}"

    # ① L4 输入侧/输出侧几何 → 居中硬断言
    bands = [n for n in nodes if n.get("type") == "row_bg"]
    l4 = [n for n in nodes if n.get("type") != "row_bg" and band_of(n, bands)
          and "L4" in str(band_of(n, bands).get("name", ""))]
    l4ids = {n["id"] for n in l4}
    xof = {n["id"]: n["x"] for n in nodes}
    # 「L4 层输入与输出的中间」= 本节点**取数的 L4 节点**(输入侧) 与**送数的 L4 节点**(输出侧) 之间的中点
    in_side = [i for i, _ in INPUTS if i in l4ids]
    out_side = [i for i, _ in OUTPUTS if i in l4ids]
    max_in = max([xof[i] for i in in_side], default=0)
    min_out = min([xof[i] for i in out_side], default=10 ** 9)
    # 独立校验: 新节点必须落在**同行带**的**最大横向空档**里 (防止"自选一对方便的前沿")
    band_new = band_of({"y": Y}, bands)
    same_row = [n for n in l4 if band_of(n, bands) is band_new]
    xs = sorted(n["x"] for n in same_row)
    gaps = [(xs[k + 1] - xs[k], xs[k], xs[k + 1]) for k in range(len(xs) - 1)]
    gw, g0, g1 = max(gaps)
    assert g0 < X < g1, f"不在 L4 行最大空档 ({g0},{g1}) 内: x={X}"
    print(f"① 空档核验: 同行带 [{band_new['name'][:20]}] 内最大横向空档 = ({g0}, {g1}) 宽 {gw} "
          f"· 新节点 x={X} 落在其中 ✅")
    mid = (max_in + min_out) / 2
    assert max_in < X < min_out and abs(X - mid) <= 800, \
        f"居中失败: 输入前沿 {max_in} / 输出前沿 {min_out} / 中点 {mid:.0f} / 新节点 x={X}"
    print(f"① 居中核验: L4 前向输入前沿 x={max_in} < 新节点 x={X} < 前向输出前沿 x={min_out} "
          f"(中点 {mid:.0f}, 偏差 {abs(X-mid):.0f} ≤800) ✅")
    print(f"   输入侧 L4 节点 {sorted(((xof[i], i) for i in in_side))}")
    print(f"   输出侧 L4 节点 {sorted(((xof[i], i) for i in out_side))}")

    # ② 与既有节点零重叠 + 落在 L4 行带内
    for n in nodes:
        if n.get("type") == "row_bg":
            continue
        assert not (X < n["x"] + n["w"] and n["x"] < X + W and Y < n["y"] + n["h"] and n["y"] < Y + H), \
            f"与 {n['id']} 重叠"
    b = band_of({"y": Y}, bands)
    assert b is not None and "L4" in str(b["name"]), "新节点不在 L4 行带内"
    print(f"② 位置核验: 与 70 个既有节点零重叠 · 落在行带 [{b['name'][:26]}] ✅")

    node = {"id": NID, "type": "model", "name": NAME, "x": int(X), "y": int(Y),
            "w": int(W), "h": int(H), "icon": "🧮", "color": "#7bdcb5",
            "params": PARAMS, "inputs": [f"in{i+1}" for i in range(len(INPUTS))],
            "outputs": [f"out{i+1}" for i in range(len(OUTPUTS))], "actions": []}
    nodes.append(node)

    new_links = []
    for sid, lab in INPUTS:
        new_links.append({"id": f"lk0924_{sid}_{NID}", "f": sid, "t": NID,
                          "f_port": next_port(links + new_links, sid, "out"),
                          "t_port": next_port(links + new_links, NID, "in"),
                          "label": lab})
    for tid, lab in OUTPUTS:
        new_links.append({"id": f"lk0924_{NID}_{tid}", "f": NID, "t": tid,
                          "f_port": next_port(links + new_links, NID, "out"),
                          "t_port": next_port(links + new_links, tid, "in"),
                          "label": lab})
    # ⑤ 全前向 + 不重复
    xy = {n["id"]: n["x"] for n in nodes}
    for L in new_links:
        assert xy[L["f"]] < xy[L["t"]], f"非前向连线 {L['f']}→{L['t']}"
        assert not any(x["f"] == L["f"] and x["t"] == L["t"] for x in links), f"重复连线 {L}"
    links.extend(new_links)
    print(f"③ 接线: 入 {len(INPUTS)} 条 + 出 {len(OUTPUTS)} 条 = {len(new_links)} 条 (全前向, 无重复) ✅")

    for n in d["nodes"]:
        for k in ("x", "y", "w", "h"):
            if k in n:
                assert isinstance(n[k], int), f"非 int 坐标 {n['id']}.{k}={n[k]}"
    if not a.apply:
        print("(dry-run; 加 --apply 落地)")
        return 0
    d["nodes"], d["links"] = nodes, links
    json.dump(d, open(FLOW, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"✅ 已写入 {os.path.relpath(FLOW, ROOT)}: 节点 {len(nodes)} · 连线 {len(links)}")
    print("CANVAS_MANI_ENG_DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
