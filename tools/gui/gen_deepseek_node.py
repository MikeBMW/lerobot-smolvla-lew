#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_deepseek_node.py — 新增 🧿 DeepSeek-V4-Flash 视觉语言节点 (人机在环) + 重接线 (幂等)

老倪 2026-09-19: 「做一个 deepseek-v4-flash 节点, 显示的连接线, 接入当前的状态空间流程, 你来设计 UI,
让用户明确感觉到, 这个工程是在人机在环的使用 deepseek 视觉语言大模型的方案。」

设计 (让"用 DeepSeek VL"这件事在拓扑上看得见):
  · **重接**(re-route): 原来 3 条 帧→👁 的边改为 帧→🧿 (环境帧/引擎真图/真机帧 先进 DeepSeek)
  · 新增: 🧿 → 👁  "DeepSeek-V4-Flash 判读结果 → 场景理解层" (🧿=当前生效 provider, 👁=场景理解分发)
  · 新增: 📝任务指令 → 🧿 "MES 工单/指令 → 判读上下文" (人机在环: 判读围绕当前任务)
  · 🧿 节点 params.vlm_llm=True → 右键出现「视觉语言判读结果」(tools/gui/vlm_panel.py)
用法: gui-venv311/bin/python tools/gui/gen_deepseek_node.py [--dry-run]
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

NODE = {"id": "n_dsvl", "type": "model",
        "name": "🧿 DeepSeek-V4-Flash 视觉语言 (人机在环)",
        "x": 140, "y": 1200, "w": 330, "h": 68, "icon": "🧿", "color": "#a371f7",
        "inputs": ["in1", "in2", "in3", "in4"], "outputs": ["out1"],
        "params": {
            "state_space": True, "vlm_llm": True,
            "model": "deepseek-flash (DeepSeek-V4.1-Flash, Vision ✓, 本机 key 已配)",
            "desc": ("**当前生效的视觉语言大模型**: 环境帧/引擎真图/真机帧 + MES 工单 → 场景判读 "
                     "(目标/位置/在不在夹爪/朝向/画面质量/光照/背景/标定建议) → 场景理解层 👁 → LLM 层。 "
                     "人机在环: 模型只出『判读+建议』, 机械臂动作一律由操作员确认后下发。 "
                     "右键 = 打开判读结果窗口 (场景理解字段表 + 实时画面 + 历史 + 三个动作按钮); "
                     "实测冷启动 60~134s / 缓存命中 ~1s (DeepSeek thinking 默认 high); "
                     "可切 Qwen (SS_VLM_URL/KEY/MODEL) 或本地 Qwen2.5-VL-3B/Qwen3-VL"),
            "source": "src/lerobot/policies/left_right/state_space/scene_vlm.py",
            "source_symbol": "class SceneVLM (provider=deepseek)"}}

REROUTE = [("lkvllm_ds", "ssdata"), ("lkvllm_sw", "swds"), ("lkvllm_rz", "ssz700")]
NEW_LINKS = [
    ("lkdsvl_hub", "n_dsvl", "n_vlm_llm", "DeepSeek-V4-Flash 判读结果 → 场景理解层 (人机在环)", "in4"),
    ("lkdsvl_ins", "ssllm_in", "n_dsvl", "MES 工单/指令 → 判读上下文", "in4"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    d = json.load(open(FLOW, encoding="utf-8"))
    ids_before = {n["id"] for n in d["nodes"]}
    if NODE["id"] not in ids_before:
        d["nodes"].append(dict(NODE))
    by_id = {n["id"]: n for n in d["nodes"]}
    # ① 重接: 3 条 帧→👁 改为 帧→🧿 (保留 id 与 label, 只换目标)
    rered = []
    for lid, src in REROUTE:
        lk = next((l for l in d["links"] if l["id"] == lid), None)
        assert lk is not None, f"找不到要重接的连线 {lid}"
        if lk["t"] == "n_vlm_llm":
            lk["t"] = "n_dsvl"
            rered.append(lid)
    by_id["n_dsvl"]["inputs"] = ["in1", "in2", "in3", "in4"]
    for i, (lid, src) in enumerate(REROUTE, 1):
        for l in d["links"]:
            if l["id"] == lid:
                l["t_port"] = f"in{i}"
    # ② 新增连线
    have = {l["id"] for l in d["links"]}
    added = []
    for lid, f, t, label, tport in NEW_LINKS:
        if lid in have:
            continue
        assert f in by_id and t in by_id, f"{lid}: 端点缺失"
        d["links"].append({"id": lid, "f": f, "t": t, "f_port": "out1", "t_port": tport, "label": label})
        ports = [p for p in (by_id[t].get("inputs") or []) if p]
        if tport not in ports:
            ports.append(tport); by_id[t]["inputs"] = ports
        added.append(lid)
    out = json.dumps(d, ensure_ascii=False, indent=1)
    d2 = json.loads(out)
    N = {n["id"]: n for n in d2["nodes"]}
    din, dout = {i: 0 for i in N}, {i: 0 for i in N}
    for l in d2["links"]:
        dout[l["f"]] += 1; din[l["t"]] += 1
    print(f"节点 {len(ids_before)} → {len(d2['nodes'])} · 连线重接 {len(rered)} 条 · 新增 {len(added)} 条")
    for nid in ("n_dsvl", "n_vlm_llm"):
        print(f"   {nid}: 入{din[nid]} 出{dout[nid]}  {N[nid]['name'][:34]}")
        for l in d2["links"]:
            if l["t"] == nid:
                print(f"        ← {N[l['f']]['name'][:26]:28s} [{l['t_port']}] {l.get('label','')[:34]}")
            if l["f"] == nid:
                print(f"        → {N[l['t']]['name'][:26]:28s} {l.get('label','')[:34]}")
    iso = [i for i, n in N.items() if n.get("type") != "row_bg" and din[i] == 0 and dout[i] == 0]
    print(f"孤立节点: {iso or '无 ✓'}")
    if a.dry_run:
        print("(--dry-run 未写盘)"); return 0
    shutil.copy2(FLOW, FLOW + ".bak." + time.strftime("%Y%m%d_%H%M%S"))
    open(FLOW, "w", encoding="utf-8").write(out)
    print("✅ 已写盘")
    return 0


if __name__ == "__main__":
    sys.exit(main())
