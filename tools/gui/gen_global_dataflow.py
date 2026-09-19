#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_global_dataflow.py — 全局数据通路整合 (幂等) + INTACT 桥接真连线 + LLM 视觉通路

老倪 2026-09-19 (第二轮整合):
  「L4功能, INTACT意图解码器, 怎么丢失了数据源的输入线? 任务规划器 LLM 也要感知到视觉, 增加 Qwen2.5-VL / Qwen3-VL;
    L4 光模块插拔链之前是为了单独验证 INTACT 插拔策略, 现在已经完成了桥接, 所以也要考虑用实际的连线表达出怎么桥接 INTACT。
    整合全局数据通路 · INTACT 相关的所有节点都要整合 · 不能存在孤立节点。」

设计 (每条边都有数据含义):
  A. INTACT 意图解码器 (ssintact_dec) 三路新输入 —— 原先只有 [INTACT策略, 意图丛]:
     ssdata/dsz700 数据源真帧/真机帧 · ssvlm 视觉潜空间 · n_vlm_llm 视觉语义
  B. 👁 视觉语言大模型 (新节点 n_vlm_llm, Qwen2.5-VL / Qwen3-VL):
     环境帧(metaworld渲染) / 引擎真图 / 真机帧 → 场景理解 → {任务规划器, 异常推理器, 技能编排器, 意图解码器, 总装记忆}
  C. L4 光模块插拔链 (演示链 swds→swintact→swworld→swvideo) ↔ 主流程 **桥接真连线**:
     数据源→环境渲染 · L4策略→演示链策略(同一契约) · 同一物理引擎 · 演示渲染视频→操作视频 · 档位→演示链
  D. 可视化/验证支路补来源 (3D框→3D视图 · 前馈激活→直方图 · 调度→旁路可视化 · 43D→仿真波形 ·
     执行结果→用例执行 · 总装记忆→功能清单)
用法: gui-venv311/bin/python tools/gui/gen_global_dataflow.py [--dry-run]
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
    {"id": "n_vlm_llm", "type": "model", "name": "👁 视觉语言大模型 (Qwen2.5-VL / Qwen3-VL)",
     "x": 140, "y": 1200, "w": 320, "h": 68, "icon": "👁", "color": "#a371f7",
     "inputs": ["in1", "in2", "in3"], "outputs": ["out1"],
     "params": {
         "state_space": True, "vlm_llm": True,
         "model": "Qwen2.5-VL-3B-Instruct (本地, 无 key) / Qwen3-VL 可插拔",
         "desc": ("大模型层的**视觉通路**: 环境帧 (metaworld 渲染) / 引擎真图 / 真机帧 → 场景理解 JSON "
                  "(目标/在不在夹爪/画面质量/光照/标定建议) → 供 任务规划器·异常推理器·技能编排器·意图解码器·总装记忆 消费。 "
                  "本地 Qwen2.5-VL-3B (SS_VLM_MODEL 可换 Qwen3-VL), 或 SS_VLM_URL+KEY 走 OpenAI 兼容 API; "
                  "无模型时只给规则回退摘要并如实标注。源码 scene_vlm.py + tools/vlm_worker.py"),
         "source": "src/lerobot/policies/left_right/state_space/scene_vlm.py",
         "source_symbol": "class SceneVLM"}},
]

# (id, 源, 目标, 标签, 目标端口)
NEW_LINKS = [
    # A. INTACT 意图解码器: 补数据源/真机/视觉 输入线
    ("lkdec_ds", "ssdata", "ssintact_dec", "数据源真帧 224²+39D → 意图解码输入", "in3"),
    ("lkdec_rz", "ssz700", "ssintact_dec", "真机帧+编码器位姿 → 意图解码输入", "in5"),
    ("lkdec_vlm", "ssvlm", "ssintact_dec", "视觉潜空间 z → 解码条件", "in4"),
    # B. 视觉语言大模型 (Qwen2.5-VL / Qwen3-VL): 视觉通路
    ("lkvllm_ds", "ssdata", "n_vlm_llm", "环境帧 (metaworld 渲染) → 视觉理解", "in1"),
    ("lkvllm_sw", "swds", "n_vlm_llm", "引擎逐帧真图 → 视觉理解", "in2"),
    ("lkvllm_rz", "ssz700", "n_vlm_llm", "真机帧 → 视觉理解", "in3"),
    ("lkvllm_pl", "n_vlm_llm", "ssllm", "场景文字理解 → 任务规划 (LLM 感知视觉)", "in5"),
    ("lkvllm_rs", "n_vlm_llm", "ssreason", "场景理解 → 异常推理", "in4"),
    ("lkvllm_sk", "n_vlm_llm", "ssskill", "场景/型号理解 → 技能编排", "in4"),
    ("lkvllm_dec", "n_vlm_llm", "ssintact_dec", "视觉语义条件 → 意图解码", "in6"),
    ("lkvllm_mem", "n_vlm_llm", "ss_mem_share", "场景知识 → 总装记忆", "in6"),
    # C. L4 光模块插拔链 ↔ 主流程 桥接
    ("lkbr_env", "ssdata", "swds", "数据源场景/规格 → 环境渲染", "in2"),
    ("lkbr_act", "ssintact", "swintact", "**桥**: L4 策略同一契约 (微调权重/动作接口)", "in2"),
    ("lkbr_world", "ssworld", "swworld", "**桥**: 同一 Z-MAX 物理引擎 (真物理闭环)", "in2"),
    ("lkbr_vid", "swvideo", "ssvideo2", "演示链渲染视频 → 操作视频 (可视化统一)", "in2"),
    ("lkbr_cap", "sscap", "swintact", "档位 L4 → 演示链策略", "in3"),
    ("lkbr_yolo", "ssyolo", "swds", "检测目标清单 → 渲染标注", "in3"),
    # D. 可视化 / 验证 支路来源
    ("lkviz_3d", "ss2d3d", "ss3d_view", "3D 边界框 → 3D 视图", "in2"),
    ("lkviz_ff", "ssff", "ssff_hist", "前馈激活 → 直方图", "in2"),
    ("lkviz_bp", "sssched", "ssbypv", "阶段/调度 → 旁路实时可视化", "in2"),
    ("lkviz_wave", "ssobs", "ssvideo", "43D 状态 → 仿真波形", "in2"),
    ("lkver_act", "ssact", "sstest", "执行结果 → 用例执行", "in2"),
    ("lkver_mem", "ss_mem_share", "ssfeat", "总装记忆 → 功能清单核对", "in2"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    d = json.load(open(FLOW, encoding="utf-8"))
    ids_before = {n["id"] for n in d["nodes"]}
    links_before = {l["id"]: json.dumps(l, sort_keys=True, ensure_ascii=False) for l in d["links"]}

    added_nodes = []
    for nn in NEW_NODES:
        if nn["id"] not in ids_before:
            d["nodes"].append(dict(nn)); added_nodes.append(nn["id"])
    by_id = {n["id"]: n for n in d["nodes"]}
    have = {l["id"] for l in d["links"]}
    added = []
    for lid, f, t, label, tport in NEW_LINKS:
        if lid in have:
            continue
        assert f in by_id and t in by_id, f"{lid}: 端点不存在 {f}->{t}"
        d["links"].append({"id": lid, "f": f, "t": t, "f_port": "out1", "t_port": tport, "label": label})
        ports = [p for p in (by_id[t].get("inputs") or []) if p]
        if tport not in ports:
            ports.append(tport); by_id[t]["inputs"] = ports
        added.append(lid)
    # 新节点入线端口声明
    by_id["n_vlm_llm"]["inputs"] = ["in1", "in2", "in3"]

    out = json.dumps(d, ensure_ascii=False, indent=1)
    d2 = json.loads(out)
    assert {n["id"] for n in d2["nodes"]} >= ids_before, "老节点丢失"
    la = {l["id"]: json.dumps(l, sort_keys=True, ensure_ascii=False) for l in d2["links"]}
    assert all(la.get(k) == v for k, v in links_before.items()), "老连线被改动"
    N = {n["id"]: n for n in d2["nodes"]}
    din, dout = {i: 0 for i in N}, {i: 0 for i in N}
    for l in d2["links"]:
        dout[l["f"]] += 1; din[l["t"]] += 1
    iso = [i for i, n in N.items() if n.get("type") != "row_bg" and din[i] == 0 and dout[i] == 0]
    srcs = [i for i, n in N.items() if n.get("type") != "row_bg" and din[i] == 0]
    intact = [i for i, n in N.items() if "intact" in i or "INTACT" in (n.get("name") or "")]
    print(f"节点 {len(ids_before)} → {len(d2['nodes'])} (+{added_nodes}) · 连线 {len(links_before)} → {len(d2['links'])} (+{len(added)})")
    print(f"孤立节点 (无进无出): {iso or '无 ✓'}")
    print(f"无入线节点 (应为真源): {[(N[i]['name'][:18], dout[i]) for i in srcs]}")
    print("INTACT 相关节点连线:")
    for i in sorted(intact):
        print(f"   {i:16s} 入{din[i]:2d} 出{dout[i]:2d}  {N[i]['name'][:30]}")
    if a.dry_run:
        print("(--dry-run 未写盘)"); return 0
    bak = FLOW + ".bak." + time.strftime("%Y%m%d_%H%M%S")
    shutil.copy2(FLOW, bak)
    open(FLOW, "w", encoding="utf-8").write(out)
    print(f"✅ 写入 {FLOW} (备份 {bak})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
