#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧮 canvas_add_manifold_calib.py — 把「流形引擎标定」节点接入状态空间画布

老倪 2026-09-29 要求: 「质量不是本质, 而是能量的聚集形式/是结构的副产物; 在状态空间工程里,
流形引擎就是整个工程的核心结构; 向**标定层**暴露一个主标定参数 M(类似发动机标定的质量 M)。」

⇒ 画布新增 **L4 标定层** 节点「流形引擎标定 · 主参数 M」并**真的接进工程网络**:
   入: 标定层(sscalib) · 潜空-流形(sslat)
   出: 流形引擎(ss_mani_eng) · 接触流形(ssmani_c) · 流形专家(ssmani_exp)

硬断言 (照 tools/canvas_add_manifold_engine.py 的六条范式):
  ① id 唯一; ② 坐标全 int; ③ 与既有非背景节点零重叠; ④ 落在 L4 行带内;
  ⑤ 连线全前向 (源 x < 目标 x) 且不重复; ⑥ 幂等 (已存在则跳过, 不重复接线)。
写盘前打印还原命令; 写盘后复核 node/edge 计数 + 新连线 id (证据)。

用法 (必须先停 studio, 否则 GUI 会把内存版画布写回覆盖):
    ./gui-venv311/bin/python tools/canvas_add_manifold_calib.py [--apply]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# ⚠ 仓库根 flows/state_space_obs.json 是**软链** → 真源在 src/lerobot/engineering/flows/。
#   原子写必须落**真源路径** (对软链做 os.replace 会把软链本身换成普通文件, 破坏工程结构)。
FLOW = os.path.realpath(os.path.join(ROOT, "flows", "state_space_obs.json"))

NID = "n_calib_mani"
NAME = "🧮 流形引擎标定 · 主参数 M (状态空间结构参数 · 等效惯量)"
X, Y, W, H = 6000, 1546, 340, 130          # L4 行带内; 落在 ss_moe(5020) 与 ss_mani_eng(7500) 之间的最大空档
INPUTS = [("sscalib", "标定层单一真源 → M 注册口 (引力/斥力/潜空间三域)"),
          ("sslat", "潜空间几何 → 曲率/维度尺度 (M 的结构来源)")]
OUTPUTS = [("ss_mani_eng", "M = 状态空间结构参数 (等效惯量) → 流形引擎主核"),
           ("ssmani_c", "M → 接触流形势能 Φ_c 的惯性尺度"),
           ("ssmani_exp", "M → 流形梯度流/动量 (JEPA 流形预测器)")]
PARAMS = {
    "state_space": True,
    "manifold_calib": True,
    "kind": "real",
    "role": "L4 标定层 — 流形引擎主标定参数 M (状态空间结构参数 / 等效惯量)",
    "M": 1.0,
    "M_default": 1.0,
    "M_range": [0.0, 8.0],
    "M_unit": "等效惯量尺度 (无量纲归一化; 物理类比 kg, 信息类比 Fisher/Hessian 曲率尺度)",
    "M_meaning": ("a = F/M ⇒ Δx = F·dt²/M (有惯性二阶); M→0 ⇒ 无惯性/速度∝力 (旧 GD 过阻尼); "
                  "M>0 ⇒ 状态带动量, 过渡更平滑、对突变有抑制"),
    "M_info": ("信息论类比: 交叉熵 H(p,q) 度量“用 q 编码 p”的代价; M 是把“信息代价梯度”换成"
               "“状态加速度”的单位换算/曲率尺度 (Fisher 信息/Hessian 尺度的单标量代理)"),
    "M_not_free": "M 不是拟合出来的自由参数, 而是从流形结构导出的结构参数 (曲率/维度/尺度); 现场以单标量暴露",
    "inertia": False,
    "inertia_default": False,
    "zero_regression": "inertia=false 或 M≤0 ⇒ 引擎行为与旧版一阶过阻尼逐位相同 (零回归)",
    "source": "src/lerobot/manifold/manifold_engine.py (ManifoldEngine.manifold_M / inertia · manifold_M_spec())",
    "calib_source": "config/calib/zmax_manifold.json → tools/zmax_params.py::manifold_M()/write_manifold_M()",
    "desc": "流形引擎向标定层暴露的唯一主标定标量 M; 双击/右键真跑: 同一起点同一场, 有惯性(M>0) vs 过阻尼(M→0) 两臂对比",
}


def band_of(n, bands):
    for b in bands:
        if b["y"] <= n["y"] <= b["y"] + b.get("h", 0):
            return b
    return None


def used_ports(links, node, side):
    if side == "out":
        return {str(l.get("f_port")) for l in links if l.get("f") == node}
    return {str(l.get("t_port")) for l in links if l.get("t") == node}


def next_port(links, node, side):
    used = used_ports(links, node, side)
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

    # ② 与既有节点零重叠 (排除背景行条) + ④ 落在 L4 行带内
    for n in nodes:
        if n.get("type") in ("bg", "row_bg"):
            continue
        assert not (X < n["x"] + n["w"] and n["x"] < X + W and Y < n["y"] + n["h"] and n["y"] < Y + H), \
            f"与 {n['id']} 重叠"
    bands = [n for n in nodes if n.get("type") == "row_bg"]
    b = band_of({"y": Y}, bands)
    assert b is not None and "L4" in str(b.get("name", "")), "新节点不在 L4 行带内"
    # ③ 语义+几何: 落在「标定层(sscalib) → 流形引擎(ss_mani_eng)」区间内, 且处该区间**最大横向空档**
    #    (M 是标定层给引擎的主参数 ⇒ 必须排在标定层之后、引擎之前; 这是本节点**专属**的落位判据,
    #     不是全域最大空档 —— 全域最大空档在 (13166,16839), 那里到引擎已是反向线, 语义不成立)
    _x0, _x1 = next(n["x"] for n in nodes if n["id"] == "sscalib"), \
        next(n["x"] for n in nodes if n["id"] == "ss_mani_eng")
    assert _x0 < X < _x1, f"新节点 x={X} 不在 标定层({_x0}) → 流形引擎({_x1}) 之间"
    same = sorted(n["x"] for n in nodes
                  if n.get("type") not in ("bg", "row_bg") and band_of(n, bands) is b
                  and _x0 <= n["x"] <= _x1)
    gaps = [(same[k + 1] - same[k], same[k], same[k + 1]) for k in range(len(same) - 1)]
    gw, g0, g1 = max(gaps, key=lambda g: g[0])
    assert g0 < X and X + W < g1, f"不在 [标定层→引擎] 区间最大空档 ({g0},{g1}) 内: x={X}..{X+W}"
    print(f"③ 落位核验: 区间 [标定层 {_x0} → 流形引擎 {_x1}] 最大空档 ({g0},{g1}) 宽 {gw}"
          f" · 新节点 {X}..{X+W} 落在其中 ✅")

    node = {"id": NID, "type": "model", "name": NAME, "x": int(X), "y": int(Y),
            "w": int(W), "h": int(H), "icon": "🧮", "color": "#d2a8ff",
            "params": PARAMS, "inputs": [f"in{i+1}" for i in range(len(INPUTS))],
            "outputs": [f"out{i+1}" for i in range(len(OUTPUTS))], "actions": []}
    nodes.append(node)

    new_links = []
    for sid, lab in INPUTS:
        new_links.append({"id": f"lk0929_{sid}_{NID}", "f": sid, "t": NID,
                          "f_port": next_port(links + new_links, sid, "out"),
                          "t_port": next_port(links + new_links, NID, "in"),
                          "label": lab})
    for tid, lab in OUTPUTS:
        new_links.append({"id": f"lk0929_{NID}_{tid}", "f": NID, "t": tid,
                          "f_port": next_port(links + new_links, NID, "out"),
                          "t_port": next_port(links + new_links, tid, "in"),
                          "label": lab})

    # ⑤ 全前向 + 不重复
    xy = {n["id"]: n["x"] for n in nodes}
    for L in new_links:
        assert xy[L["f"]] < xy[L["t"]], f"非前向连线 {L['f']}→{L['t']}"
        assert not any(x["f"] == L["f"] and x["t"] == L["t"] for x in links), f"重复连线 {L}"

    # 目标节点若是新端口 (如 ss_mani_eng 的 in6), 把端口声明补上 (字符串列表, 不破坏既有)
    for n in nodes:
        need = [L["t_port"] for L in new_links if L["t"] == n["id"] and L["t_port"] not in (n.get("inputs") or [])]
        if need:
            n["inputs"] = list(n.get("inputs") or []) + sorted(set(need))
            print(f"   ↳ {n['id']} 端口声明补 {sorted(set(need))} → {n['inputs']}")

    links.extend(new_links)
    for n in d["nodes"]:
        for k in ("x", "y", "w", "h"):
            if k in n:
                assert isinstance(n[k], int), f"非 int 坐标 {n['id']}.{k}={n[k]}"
    for L in new_links:
        assert L["f_port"] is not None and L["t_port"] is not None

    print(f"①②④ 位置核验: 零重叠 · L4 行带 [{b['name'][:26]}] ✅")
    print(f"⑤ 接线: 入 {len(INPUTS)} + 出 {len(OUTPUTS)} = {len(new_links)} 条 (全前向/不重复) ✅")
    for L in new_links:
        print(f"     {L['id']}: {L['f']}:{L['f_port']} → {L['t']}:{L['t_port']}  「{L['label']}」")

    if not a.apply:
        print("(dry-run; 加 --apply 落地)")
        return 0
    ad = os.path.join(ROOT, "flows", "_archive")          # 与本仓库既有备份约定一致 (flows/_archive)
    os.makedirs(ad, exist_ok=True)
    bak = os.path.join(ad, "state_space_obs_before_manifold_calib_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(FLOW, bak)
    print("   ↩️ 还原: cp %s %s" % (bak, FLOW))
    d["nodes"], d["links"] = nodes, links
    tmp = FLOW + ".tmp"
    json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, FLOW)
    print(f"✅ 已写入 {os.path.relpath(FLOW, ROOT)}: 节点 {len(nodes)} · 连线 {len(links)}")
    print("CANVAS_MANI_CALIB_DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
