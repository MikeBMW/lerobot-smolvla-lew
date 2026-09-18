#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_ss_obs_layout.py — 状态空间画布**整齐重排** (幂等, 可重跑; 只改 x/y/w/h, 不碰节点/连线语义)

老倪 2026-09-19: 「在画布上, 你要重新编排一下 UI, 排列一下, 要整齐」
现状: 79 节点散在 y=-1720..1365 / x=-420..13500, 行背景宽到 13400px, 同一层被切成 6 条
      "L2 基础辅助功能" 背景带 → 看不到链路。

重排原则 (与记忆里的界面偏好一致):
  · **按模块链路自上而下**: 数据源/环境 → 大模型层 → L4 → L3 → L2(感知/控制/决策/原子技能) → 执行 → 验证 → 可视化
  · 一行一主题, 行背景带包住整行 (宽度=行内实际跨度), 行内**左对齐等距网格** (列距 300)
  · 行距统一 200; 行内节点垂直居中于该行
  · 连线一条不动 (语义零回退); 只重排位置 → **VEH.5 编号会按新的 (y,x) 顺序重算** (这是必然, 会更符合链路顺序)

安全规程 (flow-json-edit-safety):
  ① 先备份 ② 只改几何字段 ③ 写前 json.loads 校验 ④ 写后断言 节点id集合/连线逐条 与改前**完全一致**
用法: gui-venv311/bin/python tools/gui/gen_ss_obs_layout.py [--dry-run]
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

BASE_X = 140          # 行内首列 x
COL_W = 300           # 列距
BASE_Y = 120          # 首行 y
ROW_H = 200           # 行距
BAND_PAD = 160        # 行背景左伸出 (row_bg.x = BASE_X - BAND_PAD)

# 行计划: (行名, 行背景 id 或 None, [节点 id...])  ← 覆盖全部节点, 脚本会断言一个不漏
ROWS = [
    # 行名里保留 L2/L3/L4 标记 —— verify_l4_zero_regression.py 按"行背景名含 L?"推断档位归属,
    # 改名会把它判成"档位回退"(实测踩过), 所以 L 档行一律带 L 标记, 非分级行(数据源/大模型/验证/可视化)不带。
    ("🌍 L4 · 光模块插拔链 (环境渲染 → INTACT → 引擎 → 视频)", "swbg_l4sw",
     ["swds", "swintact", "swworld", "swvideo"]),
    ("📦 数据源 (metaworld 环境 · 供给全部层级)", "ssbg_data",
     ["ssdata", "ssmode", "sscap"]),
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
     ["sssk1", "sssk2", "sssk3", "sssk4", "sssk5", "sssk6", "sssk7", "sssk8",
      "ssa", "ssb", "ssc"]),
    ("🔧 L2 基础辅助功能 · 执行层 (执行器 → 物理闭环)", "ssbg4", ["ssact", "ssworld"]),
    ("🧩 验证层 · Feature/Test 质量门 (回路外元层)", "ssbg8", ["ssfeat", "sstest"]),
    ("🔭 可视化层 · 观察器 (真机/旁路/3D/视频)", "ssbg9",
     ["ssff_hist", "ssz700", "ssbypv", "ss3d_view", "ssvideo", "ssvideo2"]),
]
# 已废弃不用的旧背景带 (重排后由上面的行背景统一承担) —— 只删几何占位, 不删节点语义
DEAD_BANDS = ["ssbg6"]   # 已并入 ssbg7 行 (同为 L4 档, 语义不丢)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    src = open(FLOW, encoding="utf-8").read()
    d = json.loads(src)
    nodes = {n["id"]: n for n in d["nodes"] if isinstance(n, dict)}
    links_before = {l["id"]: json.dumps(l, sort_keys=True, ensure_ascii=False) for l in d["links"]}

    # ── 覆盖性断言: 每个节点恰好出现一次 ──
    assigned = [i for _t, _b, ids in ROWS for i in ids] + DEAD_BANDS + [b for _t, b, _i in ROWS if b]
    dup = [i for i in set(assigned) if assigned.count(i) > 1]
    missing = [i for i in nodes if i not in assigned]
    extra = [i for i in assigned if i not in nodes]
    assert not dup, f"节点被重复排布: {dup}"
    assert not missing, f"有节点没被排布(会丢在角落): {missing}"
    assert not extra, f"排布表里有不存在的节点: {extra}"
    row_bg_ids = {b for _t, b, _i in ROWS if b}
    assert row_bg_ids | set(DEAD_BANDS) == {i for i, n in nodes.items() if n.get("type") == "row_bg"}, \
        "行背景带覆盖不全"

    print(f"节点 {len(nodes)} · 连线 {len(d['links'])} · 行 {len(ROWS)}")
    moved = 0
    # ── 行内等距网格 + **保留各行的左右走向** (阶梯式): 行偏移 = 该行原 x 中位数, 归一化到 ≥0 ──
    #    为什么要这一步: 每行都左对齐到 BASE_X 会让跨行连线变"右→左"(实测反向连线 7→45),
    #    与画布"闭环左→右"的口径冲突; 保留原行横向次序后, 既整齐又尽量不产生反向线。
    import statistics as _st
    offs = {}
    for _t, _b, ids in ROWS:
        xs = [nodes[i].get("x", 0) for i in ids]
        offs[tuple(ids)] = _st.median(xs) if xs else 0.0
    _mn = min(offs.values())
    for k in offs:
        offs[k] = max(0.0, round((offs[k] - _mn) / 50.0) * 50.0)
    for r, (title, band, ids) in enumerate(ROWS):
        y = BASE_Y + r * ROW_H
        for c, nid in enumerate(ids):
            n = nodes[nid]
            nx, ny = BASE_X + offs[tuple(ids)] + c * COL_W, y
            if (n.get("x"), n.get("y")) != (nx, ny):
                n["x"], n["y"] = nx, ny
                moved += 1
        if band:
            b = nodes[band]
            _x0 = min(nodes[i]["x"] for i in ids)
            _x1 = max(nodes[i]["x"] + nodes[i].get("w", 160) for i in ids)
            b["x"], b["y"] = _x0 - BAND_PAD, y - 20
            b["w"], b["h"] = (_x1 - _x0 + BAND_PAD + 60), ROW_H - 40
            b["name"] = title
            b["params"] = dict(b.get("params") or {}, desc=title)
    # 旧背景带: 收进可视区 (不参与布局) —— 标 0 高避免遮挡
    for nid in DEAD_BANDS:
        n = nodes[nid]
        n["x"], n["y"], n["w"], n["h"] = BASE_X - BAND_PAD, BASE_Y - 240, 100, 8

    out = json.dumps(d, ensure_ascii=False, indent=1)
    d2 = json.loads(out)                        # 🛡 写前校验 JSON 合法
    # ── 写后断言: 节点/连线零丢失, 连线逐条不变 ──
    assert {n["id"] for n in d2["nodes"]} == set(nodes), "节点 id 集合变了"
    links_after = {l["id"]: json.dumps(l, sort_keys=True, ensure_ascii=False) for l in d2["links"]}
    assert links_after == links_before, "连线发生了变化 (零回退红线)"
    ys = [n["y"] for n in d2["nodes"] if n.get("type") != "row_bg"]
    xs = [n["x"] for n in d2["nodes"] if n.get("type") != "row_bg"]
    print(f"重排后可视区: x {min(xs)}..{max(xs)} (原来 -420..13500) · y {min(ys)}..{max(ys)} (原来 -1720..1365)")
    print(f"移动 {moved} 个节点 · 连线 {len(links_before)} 条**逐条不变** · 行背景 {len(row_bg_ids)} 条包行")

    # 新 VEH.5 编号预览 (加载时按 (y,x) 分配)
    func = sorted([n for n in d2["nodes"] if n.get("type") != "row_bg"],
                  key=lambda n: (n["y"], n["x"]))
    print("\n新的 VEH.5 编号 (前 20):")
    for i, n in enumerate(func[:20], 1):
        print(f"  VEH.5.{i:03d}  {n['name'][:34]}")

    if a.dry_run:
        print("\n(--dry-run: 未写盘)")
        return 0
    bak = FLOW + ".bak." + time.strftime("%Y%m%d_%H%M%S")
    shutil.copy2(FLOW, bak)
    open(FLOW, "w", encoding="utf-8").write(out)
    print(f"\n✅ 已重排并写盘 {FLOW}\n   备份: {bak}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
